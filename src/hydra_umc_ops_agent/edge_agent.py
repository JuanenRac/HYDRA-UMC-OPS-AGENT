# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/edge_agent.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The real edge role for Delivery 1: orchestrates inventory.py's own
collectors into one NodeSnapshot and derives incident.py's own incidents
from what was actually observed - never proposes a fix, never contacts an
AI provider, never mutates anything on this or any other host.

A systemd-unavailable host (this development machine included) is a real,
honestly-reported state (`systemd_available=False`, a real reason string),
not silently skipped or faked as "all units healthy".

V07-020 (found in an independent revalidation audit, P2, a real residual
of REV-015): `systemd_available` used to default to `True` and only ever
flip to `False` on a real, observed failure - if zero `--systemd-unit`
flags were configured at all, it stayed `True` forever, having never
actually asked systemd anything. That's a real, different fact from
"systemd was checked and is genuinely available", but the JSON contract
couldn't tell a consumer the two apart - control_plane.py's own renderer
grew a prose footnote to compensate, but any OTHER consumer reading the
raw JSON never got that nuance. `systemd_available` is now a real
tri-state (`bool | None`): `None` means never attempted (no unit
configured - genuinely unknown, not "true"), `True`/`False` mean
systemd was actually asked and either answered or didn't.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .incident import IncidentBatch, MaintenanceIncident
from .log_redaction import redact_secrets
from .inventory import (
    HttpHealthResult,
    ManifestScanIssue,
    ProjectVersion,
    ServiceHealthResult,
    SystemdUnavailableError,
    check_http_health,
    check_systemd_unit_health,
    scan_project_manifests,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class NodeSnapshot:
    source_node: str
    collected_at: str
    correlation_id: str
    projects: tuple[ProjectVersion, ...]
    manifest_issues: tuple[ManifestScanIssue, ...]
    systemd_available: bool | None
    systemd_unavailable_reason: str | None
    service_health: tuple[ServiceHealthResult, ...]
    http_health: tuple[HttpHealthResult, ...]
    incidents: tuple[MaintenanceIncident, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "sourceNode": self.source_node,
            "collectedAt": self.collected_at,
            "correlationId": self.correlation_id,
            "projects": [
                {"name": p.name, "version": p.version, "maturity": p.maturity, "manifestPath": p.manifest_path}
                for p in self.projects
            ],
            # `reason`/`detail` below are real free text (a manifest parse
            # error, an HTTP response snippet) that can carry a copy-pasted
            # secret just as easily as an incident's own `symptom` can - the
            # same real gap REV-013 found: only `incidents[].symptom` was
            # ever redacted here. Redacted at serialization time regardless
            # of whether the caller already sanitized it upstream, matching
            # `MaintenanceIncident.to_dict()`'s own defense-in-depth.
            "manifestIssues": [{"path": i.path, "reason": redact_secrets(i.reason)} for i in self.manifest_issues],
            "systemdAvailable": self.systemd_available,
            "systemdUnavailableReason": self.systemd_unavailable_reason,
            "serviceHealth": [
                {"unitName": s.unit_name, "active": s.active, "detail": redact_secrets(s.detail)}
                for s in self.service_health
            ],
            "httpHealth": [
                {
                    "url": redact_secrets(h.url),
                    "reachable": h.reachable,
                    "statusCode": h.status_code,
                    "detail": redact_secrets(h.detail),
                }
                for h in self.http_health
            ],
            "incidents": [incident.to_dict() for incident in self.incidents],
        }


def collect_snapshot(
    source_node: str,
    projects_root: Path,
    *,
    systemd_units: list[str] | None = None,
    http_health_urls: list[str] | None = None,
) -> NodeSnapshot:
    """Real, read-only collection - the only network/subprocess calls this
    makes are the ones explicitly asked for (`systemd_units`,
    `http_health_urls`); with both omitted, this only ever reads local
    manifest files."""
    batch = IncidentBatch()

    scan = scan_project_manifests(projects_root)
    for issue in scan.issues:
        batch.add_manifest_issue(source_node, issue)

    # V07-020: starts as None (genuinely unknown/never asked) - only set
    # to a real True/False once systemd is actually queried below.
    systemd_available: bool | None = None
    systemd_unavailable_reason: str | None = None
    service_health: list[ServiceHealthResult] = []
    for unit in systemd_units or []:
        try:
            result = check_systemd_unit_health(unit)
        except SystemdUnavailableError as exc:
            # Real, honest degradation - stop trying further units too
            # (systemctl being absent is a host-wide fact, not a
            # per-unit one), rather than repeating the same failure once
            # per configured unit.
            systemd_available = False
            systemd_unavailable_reason = str(exc)
            break
        systemd_available = True
        service_health.append(result)
        batch.add_service_health(source_node, result)

    http_health: list[HttpHealthResult] = []
    for url in http_health_urls or []:
        result = check_http_health(url)
        http_health.append(result)
        batch.add_http_health(source_node, result)

    return NodeSnapshot(
        source_node=source_node,
        collected_at=_utc_now_iso(),
        correlation_id=batch.correlation_id,
        projects=scan.projects,
        manifest_issues=scan.issues,
        systemd_available=systemd_available,
        systemd_unavailable_reason=systemd_unavailable_reason,
        service_health=tuple(service_health),
        http_health=tuple(http_health),
        incidents=tuple(batch.incidents),
    )
