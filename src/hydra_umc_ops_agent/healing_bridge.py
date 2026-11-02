# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/healing_bridge.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""From a node's live state to a tracked incident: the transitions the node watchdog journals become incidents.

The watchdog writes every change of state of a watched node to its journal (one JSON object a line). This module
reads that journal from where it stopped last time and, for each transition:

* into one of the trigger statuses (by default `UNREACHABLE` and `INVALID`) it opens an incident on the node, or
  updates the open one, in the same durable store `edge collect` uses, so detection in real time and the incident
  cycle are one record;
* into one of the resolve statuses (by default `HEALTHY`) it closes the open incident of that node;
* anything else (degraded, unknown, misconfigured) is left alone.

Two line shapes are understood: the structured `{"event": "transition", "node", "from", "to", "detail"}` and the
text of the watchdog's own log line (`[node-healing] <node>: <from> -> <to> (<detail>)`, recorded as a `log`
event). The position read so far is kept in a small state file, so running this again never opens an incident
twice, and a journal that was rotated (it got smaller) is read from its start.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ._atomic import atomic_write_text, exclusive_lock
from .config import HealingConfig
from .incident import REDACTION_LEVEL_SANITIZED, MaintenanceIncident
from .incident_store import (
    IncidentStoreError,
    TrackedIncident,
    incident_key,
    load_incident_store,
    reconcile_incidents,
    save_incident_store,
)
from .log_redaction import redact_secrets

COMPONENT_PREFIX = "node-healing:"
SYMPTOM_PREFIX = "node-healing transition: "
_LOG_LINE = re.compile(r"^\[node-healing\]\s+(?P<node>[^:]+):\s+(?P<from>[A-Z]+)\s+->\s+(?P<to>[A-Z]+)(?:\s+\((?P<detail>.*)\))?\s*$")
MAX_LINES_PER_RUN = 5000


@dataclass(frozen=True)
class Transition:
    node: str
    from_status: str
    to_status: str
    detail: str
    time: str


def parse_transition(line: str) -> Transition | None:
    """The transition a journal line records, or None for any other line (a malformed line is skipped, not an error)."""
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    stamp = str(data.get("time", ""))
    if data.get("event") == "transition":
        node, before, after = data.get("node"), data.get("from"), data.get("to")
        if isinstance(node, str) and node and isinstance(before, str) and isinstance(after, str):
            return Transition(node, before.upper(), after.upper(), str(data.get("detail", "")), stamp)
        return None
    if data.get("event") == "log" and isinstance(data.get("message"), str):
        match = _LOG_LINE.match(data["message"])
        if match:
            return Transition(match["node"].strip(), match["from"], match["to"], match["detail"] or "", stamp)
    return None


def _load_offset(path: Path) -> int:
    try:
        offset = json.loads(path.read_text(encoding="utf-8")).get("offset", 0)
    except (OSError, ValueError, AttributeError):
        return 0
    return offset if isinstance(offset, int) and offset >= 0 else 0


def read_new_transitions(journal: Path, state_file: Path) -> tuple[list[Transition], int]:
    """The transitions written since the last run, and the offset to store once they are handled."""
    if not journal.is_file():
        return [], _load_offset(state_file)
    size = journal.stat().st_size
    offset = _load_offset(state_file)
    if size < offset:
        offset = 0  # rotated or replaced
    with journal.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(size - offset)
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset  # a line still being written
    complete = chunk[: end + 1]
    transitions = [item for item in (parse_transition(line) for line in complete.decode("utf-8", "replace").splitlines()[:MAX_LINES_PER_RUN]) if item]
    return transitions, offset + len(complete)


def _incident_for(transition: Transition, correlation_id: str, severity: str) -> MaintenanceIncident:
    detail = f" ({transition.detail})" if transition.detail else ""
    return MaintenanceIncident(
        incident_id=str(uuid.uuid4()), source_node=transition.node,
        detected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), severity=severity,
        component=f"{COMPONENT_PREFIX}{transition.node}",
        symptom=redact_secrets(f"{SYMPTOM_PREFIX}{transition.from_status} -> {transition.to_status}{detail}"),
        evidence_refs=(f"node-healing journal: {transition.node} {transition.from_status} -> {transition.to_status} at {transition.time}",),
        redaction_level=REDACTION_LEVEL_SANITIZED, requested_by="node-healing:auto", correlation_id=correlation_id,
    )


@dataclass(frozen=True)
class BridgeResult:
    transitions: int
    opened_or_updated: int
    resolved: int


def ingest(config: HealingConfig, store_path: Path, *, notifier: object | None = None) -> BridgeResult:
    """Reads the journal named in the configuration and applies its new transitions to the incident store."""
    if not config.enabled:
        raise IncidentStoreError("the node-healing bridge is switched off in the configuration (healing.enabled)")
    if not config.journal_file or not config.state_file:
        raise IncidentStoreError("healing.journal_file and healing.state_file must both be set")
    journal, state_file = Path(config.journal_file), Path(config.state_file)
    transitions, new_offset = read_new_transitions(journal, state_file)
    triggers, resolves = set(config.trigger_statuses), set(config.resolve_statuses)
    correlation_id = str(uuid.uuid4())
    opened = resolved = 0
    with exclusive_lock(store_path):
        before = load_incident_store(store_path)
        store = before
        for transition in transitions:
            key = (transition.node, f"{COMPONENT_PREFIX}{transition.node}")
            if transition.to_status in triggers:
                store = reconcile_incidents(store, [_incident_for(transition, correlation_id, config.severity)], set())
                opened += 1
            elif transition.to_status in resolves and any(
                item.resolved_at is None and item.dedup_key == incident_key(*key) for item in store
            ):
                store = reconcile_incidents(store, [], {key})
                resolved += 1
        if transitions:
            save_incident_store(store, store_path)
    if notifier is not None and transitions:
        notifier.notify_changes(before, store)  # type: ignore[attr-defined]
    atomic_write_text(state_file, json.dumps({"offset": new_offset}))
    return BridgeResult(len(transitions), opened, resolved)


def open_healing_incidents(store: list[TrackedIncident]) -> list[TrackedIncident]:
    return [item for item in store if item.resolved_at is None and item.incident.component.startswith(COMPONENT_PREFIX)]
