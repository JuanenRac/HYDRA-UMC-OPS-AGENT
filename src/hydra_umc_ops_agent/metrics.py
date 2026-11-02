# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/metrics.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The state of the incident store (and the counts of the audit journal) as Prometheus / OpenMetrics text.

Read-only: it loads the store and the journal and writes text, nothing else. Labels are only the severity and the
name of an audit event (never a component, a URL or any text from an incident), so nothing sensitive can reach a
scrape. `<namespace>_up` is 0 when the store cannot be read, so a broken store shows as a failing target rather
than as "no incidents".
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .audit_journal import AuditJournalError, read_events
from .config import SEVERITIES, MetricsConfig
from .incident_store import IncidentStoreError, TrackedIncident, load_incident_store


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _seconds(start: str, end: datetime) -> float | None:
    try:
        moment = datetime.fromisoformat(start)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, (end - moment).total_seconds())


def render_metrics(store: list[TrackedIncident], config: MetricsConfig, *, audit_events: list[dict[str, object]] | None = None,
                   now: datetime | None = None, up: bool = True) -> str:
    ns = config.namespace
    moment = now or datetime.now(timezone.utc)
    lines: list[str] = []

    def metric(name: str, kind: str, help_text: str) -> None:
        lines.append(f"# HELP {ns}_{name} {help_text}")
        lines.append(f"# TYPE {ns}_{name} {kind}")

    metric("up", "gauge", "1 when the incident store was read, 0 when it could not be.")
    lines.append(f"{ns}_up {1 if up else 0}")
    if up:
        open_items = [item for item in store if item.resolved_at is None]
        closed = [item for item in store if item.resolved_at is not None]
        metric("incidents_open", "gauge", "Incidents open now, by severity.")
        for severity in SEVERITIES:
            lines.append(f'{ns}_incidents_open{{severity="{severity}"}} {sum(1 for item in open_items if item.incident.severity == severity)}')
        metric("incidents_resolved", "gauge", "Resolved incidents still kept in the store history.")
        lines.append(f"{ns}_incidents_resolved {len(closed)}")
        durations = [value for item in closed if item.resolved_at and (value := _seconds(item.first_seen_at, _parse(item.resolved_at))) is not None]
        metric("incident_mttr_seconds", "gauge", "Mean time from first sight to resolution over the resolved incidents kept (0 when none).")
        lines.append(f"{ns}_incident_mttr_seconds {sum(durations) / len(durations) if durations else 0:.3f}")
        ages = [value for item in open_items if (value := _seconds(item.first_seen_at, moment)) is not None]
        metric("incident_oldest_open_age_seconds", "gauge", "Age of the oldest open incident (0 when none).")
        lines.append(f"{ns}_incident_oldest_open_age_seconds {max(ages) if ages else 0:.3f}")
        metric("incident_occurrences_open", "gauge", "Observations summed over the open incidents.")
        lines.append(f"{ns}_incident_occurrences_open {sum(item.occurrence_count for item in open_items)}")
    if audit_events is not None:
        counts: dict[str, int] = {}
        for entry in audit_events:
            event = entry.get("event")
            if isinstance(event, str) and event.replace("-", "").replace("_", "").isalnum():
                counts[event] = counts.get(event, 0) + 1
        metric("audit_events", "gauge", "Records in the audit journal, by event.")
        for event in sorted(counts):
            lines.append(f'{ns}_audit_events{{event="{_escape(event)}"}} {counts[event]}')
    metric("scrape_timestamp_seconds", "gauge", "Unix time of this rendering.")
    lines.append(f"{ns}_scrape_timestamp_seconds {moment.timestamp():.0f}")
    return "\n".join(lines) + "\n"


def _parse(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def collect_metrics(config: MetricsConfig, store_path: Path, audit_path: Path | None = None) -> str:
    """Reads the store (and the journal, when the configuration asks for it and one is given) and renders the text."""
    if not config.enabled:
        raise IncidentStoreError("the metrics export is switched off in the configuration (metrics.enabled)")
    try:
        store = load_incident_store(store_path)
    except IncidentStoreError:
        return render_metrics([], config, up=False)
    events: list[dict[str, object]] | None = None
    if config.include_audit and audit_path is not None:
        try:
            events = read_events(audit_path)
        except (AuditJournalError, OSError):
            events = None
    return render_metrics(store, config, audit_events=events)
