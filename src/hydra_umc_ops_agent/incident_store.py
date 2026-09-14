# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/incident_store.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""PROM-OPS-E01's own real fix: `incident.py`'s own `IncidentBatch`
generates a fresh `uuid4()` every single time `collect_snapshot()` runs -
a service that stays down across ten consecutive edge-collection passes
used to become ten separate, unrelated `MaintenanceIncident`s instead of
one real, ongoing problem a control-plane viewer could track and
eventually see resolved.

This module adds the missing durable, deduplicated layer on top of
`incident.py` - it never replaces it, and `collect_snapshot()`'s own
behavior is unchanged unless a caller opts in with a real `store_path`.

Dedup key: `(source_node, component)` - the same systemd unit, manifest
path, or health URL having ANY open problem counts as the same real,
ongoing incident, even if the exact symptom text drifts between
occurrences (`"not active: failed"` -> `"not active: exited"` is still
the same unit being down). A different symptom on the SAME component
updates that one open record's own `symptom`/`severity`/`evidenceRefs`
to the latest observation rather than spawning a second, parallel
incident for the same real thing - mirrors how this ecosystem's own
`log_redaction.py`/`certification.py` favor one real, updated record
over silently-multiplying near-duplicates.

Resolution is scoped, not blanket: an open tracked incident is only ever
auto-resolved when its own `(source_node, component)` was genuinely
re-checked this run and came back clean - never just because a caller
happened to omit that check this time (e.g. ran without
`http_health_urls` this pass). `reconcile_incidents()` takes the real
set of components this run actually checked (`checked_components`) so
it can tell "checked and now healthy" from "not checked this time"
apart.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .incident import MaintenanceIncident


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IncidentStoreError(RuntimeError):
    """Raised for a real, distinct reason a store file could not be
    loaded - mirrors control_plane.py's own SnapshotLoadError shape."""


@dataclass(frozen=True)
class TrackedIncident:
    """One real, persistent incident record - `incident` carries the
    LATEST observed symptom/severity/evidence for this same real
    problem, `incident_id` never changes across occurrences (set once,
    at first observation), and `occurrence_count`/`first_seen_at`/
    `last_seen_at`/`resolved_at` are this module's own real lifecycle
    fields layered on top of `incident.py`'s own immutable contract."""

    incident: MaintenanceIncident
    first_seen_at: str
    last_seen_at: str
    occurrence_count: int
    resolved_at: str | None = None

    @property
    def dedup_key(self) -> tuple[str, str]:
        return (self.incident.source_node, self.incident.component)

    def to_dict(self) -> dict[str, object]:
        return {
            "incident": self.incident.to_dict(),
            "firstSeenAt": self.first_seen_at,
            "lastSeenAt": self.last_seen_at,
            "occurrenceCount": self.occurrence_count,
            "resolvedAt": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TrackedIncident":
        return cls(
            incident=MaintenanceIncident.from_dict(data["incident"]),
            first_seen_at=str(data["firstSeenAt"]),
            last_seen_at=str(data["lastSeenAt"]),
            occurrence_count=int(data["occurrenceCount"]),
            resolved_at=str(data["resolvedAt"]) if data.get("resolvedAt") is not None else None,
        )


def reconcile_incidents(
    store: list[TrackedIncident],
    new_incidents: list[MaintenanceIncident],
    checked_components: set[tuple[str, str]],
    *,
    now: str | None = None,
) -> list[TrackedIncident]:
    """Returns a NEW list (never mutates `store` in place) reconciling
    `store`'s own prior state against `new_incidents` from one fresh
    real scan. Every `new_incidents` entry either updates an existing
    OPEN record sharing its `dedup_key` (same `incident_id`, latest
    symptom/severity/evidence, `occurrence_count` +1, `last_seen_at`
    bumped) or becomes a brand-new tracked record. Any OPEN record whose
    own `dedup_key` is in `checked_components` but has no matching entry
    in `new_incidents` this time is marked resolved - genuinely re-checked
    and found clean, not merely unmentioned. A resolved record that
    reoccurs later starts a real NEW incident (a fresh `incident_id`,
    `occurrence_count` reset to 1) - the same problem coming back after
    being closed is honestly a new occurrence, not a silent reopening of
    the old closed one."""
    resolved_at = now if now is not None else _utc_now_iso()

    by_key: dict[tuple[str, str], TrackedIncident] = {}
    closed: list[TrackedIncident] = []
    for tracked in store:
        if tracked.resolved_at is None:
            by_key[tracked.dedup_key] = tracked
        else:
            closed.append(tracked)

    seen_keys: set[tuple[str, str]] = set()
    for incident in new_incidents:
        key = (incident.source_node, incident.component)
        seen_keys.add(key)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = TrackedIncident(
                incident=incident, first_seen_at=incident.detected_at,
                last_seen_at=incident.detected_at, occurrence_count=1, resolved_at=None,
            )
        else:
            # Keep the ORIGINAL incidentId (the whole point of this
            # module) - only the latest observation's own real content
            # (severity/symptom/evidence/detectedAt) is carried forward.
            updated_incident = replace(existing.incident, severity=incident.severity, symptom=incident.symptom, evidence_refs=incident.evidence_refs, detected_at=incident.detected_at)
            by_key[key] = replace(
                existing, incident=updated_incident, last_seen_at=incident.detected_at,
                occurrence_count=existing.occurrence_count + 1,
            )

    newly_closed: list[TrackedIncident] = []
    still_open: list[TrackedIncident] = []
    for key, tracked in by_key.items():
        if key in seen_keys:
            still_open.append(tracked)
        elif key in checked_components:
            newly_closed.append(replace(tracked, resolved_at=resolved_at))
        else:
            # Genuinely not re-checked this run - stays open, untouched.
            still_open.append(tracked)

    return closed + newly_closed + still_open


def load_incident_store(path: Path) -> list[TrackedIncident]:
    """Real, honest degradation: a store that has never been written yet
    is a real, valid empty store, not an error - the same convention
    `edge_agent.py`'s own `collect_snapshot()` already applies to a
    projects root with no manifests yet."""
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IncidentStoreError(f"could not read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IncidentStoreError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise IncidentStoreError(f"{path} does not contain a JSON array")
    try:
        return [TrackedIncident.from_dict(entry) for entry in data]
    except (KeyError, TypeError, ValueError) as exc:
        raise IncidentStoreError(f"{path} contains a malformed tracked-incident record: {exc}") from exc


def save_incident_store(store: list[TrackedIncident], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [tracked.to_dict() for tracked in store]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
