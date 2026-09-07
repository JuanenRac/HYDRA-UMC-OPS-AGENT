# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/control_plane.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The real control-plane role for Delivery 1: a read-only renderer for a
saved NodeSnapshot (edge_agent.py's own JSON output). No network transport
between edge and control-plane exists yet in this delivery - that is real,
separate future work (a queue/API this project's own manifest is explicit
about not building yet) - this only ever reads a snapshot file already on
disk, exactly matching "control-plane muestra incidencias locales".
"""
from __future__ import annotations

import json
from pathlib import Path


class SnapshotLoadError(RuntimeError):
    """A real, distinct reason a snapshot file could not be loaded/rendered
    - never silently treated as "no incidents", which would hide a
    genuinely broken/missing collection run behind a falsely reassuring
    empty report."""


def load_snapshot(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotLoadError(f"could not read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SnapshotLoadError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SnapshotLoadError(f"{path} does not contain a JSON object")
    return data


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _safe_entries(raw: object) -> tuple[list[dict[str, object]], int]:
    """Returns `(real dict entries, malformed entry count)` for one
    snapshot section. A snapshot is real evidence read from a file that
    could have been swapped, truncated or hand-edited - a section that is
    itself not a list, or a list containing a `null`/string/number instead
    of a real object, must never crash the whole report (`.get()` on
    something that isn't a dict raised `AttributeError` here before); it is
    counted and skipped instead, so the rest of a genuinely mixed batch is
    still rendered."""
    if not isinstance(raw, list):
        return [], 0
    entries = [item for item in raw if isinstance(item, dict)]
    return entries, len(raw) - len(entries)


def _format_skipped(count: int) -> str:
    return f" ({count} malformed entr{'y' if count == 1 else 'ies'} skipped)" if count else ""


def render_snapshot_report(snapshot: dict[str, object]) -> str:
    """A real, human-readable text report - deliberately plain text, not a
    web UI, matching this delivery's own CLI-first scope (see cli.py).
    Incidents are sorted by real severity (critical first) so the one
    thing an operator most needs to see is never buried under a long,
    otherwise-chronological list."""
    lines: list[str] = []
    source_node = snapshot.get("sourceNode", "?")
    collected_at = snapshot.get("collectedAt", "?")
    lines.append(f"Node: {source_node}  (collected {collected_at})")
    lines.append("")

    projects, skipped = _safe_entries(snapshot.get("projects"))
    lines.append(f"Projects found: {len(projects)}{_format_skipped(skipped)}")
    for project in projects:
        lines.append(f"  - {project.get('name')} v{project.get('version')} ({project.get('maturity')})")

    manifest_issues, skipped = _safe_entries(snapshot.get("manifestIssues"))
    if manifest_issues or skipped:
        lines.append("")
        lines.append(f"Manifest issues: {len(manifest_issues)}{_format_skipped(skipped)}")
        for issue in manifest_issues:
            lines.append(f"  - {issue.get('path')}: {issue.get('reason')}")

    # V07-020: systemdAvailable is now a real tri-state - True (actually
    # checked, systemd answered), False (actually checked, systemd
    # itself unavailable), or None/absent (never attempted - no unit
    # was ever configured, genuinely unknown, never rendered as if it
    # were a real "true").
    systemd_available = snapshot.get("systemdAvailable")
    lines.append("")
    if systemd_available is None:
        lines.append("Service health checks: not attempted - no --systemd-unit was configured (unknown, not evidence of health)")
    elif systemd_available is False:
        lines.append(f"Service health checks: skipped - {snapshot.get('systemdUnavailableReason')}")
    else:
        service_health, skipped = _safe_entries(snapshot.get("serviceHealth"))
        lines.append(f"Service health checks: {len(service_health)}{_format_skipped(skipped)}")
        for entry in service_health:
            # V07-011: `entry.get("active")` is a real, publicly-loaded
            # snapshot field, not necessarily this module's own real
            # bool - a truthy-but-wrong-typed value (the textual string
            # "false" included, since any non-empty string is truthy in
            # Python) must never read as "active". Strict identity, same
            # "confirm_arm is not True" style already used for exactly
            # this class of bug elsewhere in the ecosystem.
            status = "active" if entry.get("active") is True else "NOT ACTIVE"
            lines.append(f"  - {entry.get('unitName')}: {status} ({entry.get('detail')})")

    http_health, skipped = _safe_entries(snapshot.get("httpHealth"))
    if http_health or skipped:
        lines.append("")
        lines.append(f"HTTP health checks: {len(http_health)}{_format_skipped(skipped)}")
        for entry in http_health:
            # V07-011: same real gap as serviceHealth's own "active"
            # above - a textual "false" is truthy in Python.
            status = "reachable" if entry.get("reachable") is True else "UNREACHABLE"
            lines.append(f"  - {entry.get('url')}: {status} ({entry.get('detail')})")

    incidents, skipped = _safe_entries(snapshot.get("incidents"))
    lines.append("")
    lines.append(f"Incidents: {len(incidents)}{_format_skipped(skipped)}")
    # V07-011: `inc.get("severity")` is real, publicly-loaded data - an
    # unhashable value (a real `severity: []`/`severity: {}` in the
    # snapshot) used to raise TypeError straight out of dict.get()
    # (unhashable types can't even be looked up), crashing the whole
    # report instead of just sorting that one malformed incident last.
    def _severity_rank(inc: dict[str, object]) -> int:
        severity = inc.get("severity")
        if not isinstance(severity, str):
            return 99
        return _SEVERITY_ORDER.get(severity, 99)

    incidents.sort(key=_severity_rank)
    for incident in incidents:
        lines.append(
            f"  [{str(incident.get('severity')).upper()}] {incident.get('component')}: {incident.get('symptom')}"
            f"  (id={incident.get('incidentId')})"
        )

    return "\n".join(lines)
