# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/incident.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""The real MaintenanceIncident contract this repo's own Delivery 1
defines, plus the Delivery-1 (read-only observation)
derivation logic: turning a real inventory scan's own findings into real,
typed incidents - never a diagnosis, a proposed fix, or an AI call, all of
which are explicitly later deliveries this version does not implement.

Severity here is a plain, honest classification of WHAT WAS OBSERVED, not a
prediction of impact - "critical" means "a service that should be running is
not", "warning" means "something is off but not yet a confirmed outage".
Getting this reclassified with real operational evidence (a false-positive
rate, an actual outage correlation) is exactly the kind of judgment call a
later delivery's own diagnosis step exists for, not this one.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .inventory import HttpHealthResult, ManifestScanIssue, ServiceHealthResult
from .log_redaction import redact_secrets

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

# v0.0.1 only ever produces sanitized evidence (see log_redaction.py) -
# this field exists in the real contract so a LATER delivery that might
# ever handle raw, unredacted evidence has somewhere honest to say so,
# never silently.
REDACTION_LEVEL_SANITIZED = "sanitized"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class MaintenanceIncident:
    """This repo's own real MaintenanceIncident contract, field-for-field
    (incidentId, sourceNode, detectedAt, severity, component, symptom,
    evidenceRefs, redactionLevel, requestedBy, correlationId) - a future
    JSON Schema for this contract should validate exactly these fields,
    this dataclass is its real, current definition."""
    incident_id: str
    source_node: str
    detected_at: str
    severity: str
    component: str
    symptom: str
    evidence_refs: tuple[str, ...]
    redaction_level: str
    requested_by: str
    correlation_id: str

    def to_dict(self) -> dict[str, object]:
        # V07-010 (found in an independent revalidation audit, P1,
        # residual outside REV-013's own three original examples):
        # `component` (often a URL or systemd unit name) and
        # `evidenceRefs` (often a URL or a real command line) were
        # never redacted here - only `symptom` was, since REV-013's own
        # fix - while `redactionLevel` unconditionally still claimed
        # `"sanitized"` for the whole record. A component like
        # `https://user:password@host/health` (a real, plausible
        # http_health_urls configuration) would leak its own embedded
        # credential straight through a field this record's own
        # `redactionLevel` field claimed was already safe.
        return {
            "incidentId": self.incident_id,
            "sourceNode": self.source_node,
            "detectedAt": self.detected_at,
            "severity": self.severity,
            "component": redact_secrets(self.component),
            "symptom": redact_secrets(self.symptom),
            "evidenceRefs": [redact_secrets(ref) for ref in self.evidence_refs],
            "redactionLevel": self.redaction_level,
            "requestedBy": self.requested_by,
            "correlationId": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "MaintenanceIncident":
        return cls(
            incident_id=str(data["incidentId"]),
            source_node=str(data["sourceNode"]),
            detected_at=str(data["detectedAt"]),
            severity=str(data["severity"]),
            component=str(data["component"]),
            symptom=str(data["symptom"]),
            evidence_refs=tuple(str(ref) for ref in data.get("evidenceRefs", [])),
            redaction_level=str(data["redactionLevel"]),
            requested_by=str(data["requestedBy"]),
            correlation_id=str(data["correlationId"]),
        )


@dataclass
class IncidentBatch:
    """A real, named group of incidents from ONE edge-collection run - the
    real meaning behind correlationId: every incident this batch derives
    shares it, so a control-plane viewer can tell "these N observations
    came from the same inventory pass" from "these happened to be reported
    around the same time but are unrelated"."""
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    incidents: list[MaintenanceIncident] = field(default_factory=list)

    def _new_incident(self, source_node: str, severity: str, component: str, symptom: str, evidence_refs: tuple[str, ...]) -> MaintenanceIncident:
        incident = MaintenanceIncident(
            incident_id=str(uuid.uuid4()),
            source_node=source_node,
            detected_at=_utc_now_iso(),
            severity=severity,
            component=component,
            symptom=symptom,
            evidence_refs=evidence_refs,
            redaction_level=REDACTION_LEVEL_SANITIZED,
            requested_by="edge-agent:auto",
            correlation_id=self.correlation_id,
        )
        self.incidents.append(incident)
        return incident

    def add_manifest_issue(self, source_node: str, issue: ManifestScanIssue) -> MaintenanceIncident:
        return self._new_incident(
            source_node=source_node,
            severity=SEVERITY_WARNING,
            component=issue.path,
            symptom=f"manifest scan issue: {issue.reason}",
            evidence_refs=(issue.path,),
        )

    def add_service_health(self, source_node: str, result: ServiceHealthResult) -> MaintenanceIncident | None:
        """Only a real, observed problem becomes an incident - a healthy
        service produces no incident at all (this is an observation log,
        not an audit trail of every check that ever ran clean)."""
        if result.active:
            return None
        return self._new_incident(
            source_node=source_node,
            severity=SEVERITY_CRITICAL,
            component=result.unit_name,
            symptom=f"systemd unit is not active: {result.detail}",
            evidence_refs=(f"systemctl is-active {result.unit_name}",),
        )

    def add_http_health(self, source_node: str, result: HttpHealthResult) -> MaintenanceIncident | None:
        if result.reachable:
            return None
        return self._new_incident(
            source_node=source_node,
            severity=SEVERITY_WARNING,
            component=result.url,
            symptom=f"health endpoint check failed: {result.detail}",
            evidence_refs=(result.url,),
        )
