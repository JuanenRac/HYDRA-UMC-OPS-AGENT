# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/verification.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Delivery 5 - Verification: confirms that the SAME real check which
originally produced an incident now passes, using the exact same
inventory.py functions Delivery 1 already has - never a second,
independently-drifting health-check implementation. An incident is only
ever considered resolved because the real evidence was re-collected and
came back healthy, never because a canary deploy (Delivery 4) merely
reported "promoted"."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .incident import MaintenanceIncident
from .inventory import (
    SystemdUnavailableError,
    check_http_health,
    check_systemd_unit_health,
)

# The exact, fixed symptom prefixes incident.py's own IncidentBatch
# methods use - the real, stable way to tell what KIND of incident this
# is (there is no separate "kind" field in the MaintenanceIncident
# contract itself, by design - see incident.py).
_HTTP_SYMPTOM_PREFIX = "health endpoint check failed:"
_SYSTEMD_SYMPTOM_PREFIX = "systemd unit is not active:"
_MANIFEST_SYMPTOM_PREFIX = "manifest scan issue:"


class VerificationError(RuntimeError):
    """A real reason verification itself could not be performed - never
    silently reported as "still broken" when the real answer is "could
    not be checked at all"."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class VerificationResult:
    incident_id: str
    verified_at: str
    resolved: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "incidentId": self.incident_id,
            "verifiedAt": self.verified_at,
            "resolved": self.resolved,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "VerificationResult":
        # V07-021 (P2): this
        # is a real public loading boundary (whatever produced `data`
        # need not be this module's own to_dict()) - `bool(data["resolved"])`
        # used to coerce ANY non-empty value, including the literal
        # string "false", to True (Python's own `bool("false") is True`
        # - a non-empty string is always truthy). A publicly-loaded
        # 'false' silently became a resolved incident. Every field here
        # is now required to already be its real declared type - no
        # coercion, ever - matching the same "confirm_arm is not True"/
        # "_is_real_number" style already used for exactly this class of
        # bug elsewhere in the ecosystem (HYDRA-UMC-BRIDGE-UAV's own
        # mavlink_transport.py).
        incident_id = data["incidentId"]
        verified_at = data["verifiedAt"]
        resolved = data["resolved"]
        detail = data["detail"]
        if not isinstance(incident_id, str) or not incident_id:
            raise VerificationError(f"incidentId must be a non-empty string, got {incident_id!r}")
        if not isinstance(verified_at, str) or not verified_at:
            raise VerificationError(f"verifiedAt must be a non-empty string, got {verified_at!r}")
        if not isinstance(resolved, bool):
            raise VerificationError(f"resolved must be a real boolean, got {resolved!r} ({type(resolved).__name__})")
        if not isinstance(detail, str):
            raise VerificationError(f"detail must be a string, got {detail!r}")
        return cls(incident_id=incident_id, verified_at=verified_at, resolved=resolved, detail=detail)


def verify_incident_resolved(incident: MaintenanceIncident, *, timeout_s: float = 5.0) -> VerificationResult:
    """Re-runs the real check implied by the incident's own symptom text.
    Only the two Delivery-1 check kinds that can be re-run automatically
    are handled here - a manifest-scan incident has no automated re-check
    (re-running `edge collect` against the same projects-root is the real
    way to confirm one of those is gone, since it is a structural fact
    about a file, not a live service to re-poll)."""
    if incident.symptom.startswith(_HTTP_SYMPTOM_PREFIX):
        result = check_http_health(incident.component, timeout_s=timeout_s)
        return VerificationResult(incident_id=incident.incident_id, verified_at=_utc_now_iso(), resolved=result.reachable, detail=result.detail)

    if incident.symptom.startswith(_SYSTEMD_SYMPTOM_PREFIX):
        try:
            result = check_systemd_unit_health(incident.component, timeout_s=timeout_s)
        except SystemdUnavailableError as exc:
            raise VerificationError(f"cannot verify a systemd-unit incident on this host: {exc}") from exc
        return VerificationResult(incident_id=incident.incident_id, verified_at=_utc_now_iso(), resolved=result.active, detail=result.detail)

    if incident.symptom.startswith(_MANIFEST_SYMPTOM_PREFIX):
        raise VerificationError(
            "a manifest-scan incident has no automated re-check here - re-run `edge collect` "
            "against the same projects-root and confirm this incident no longer appears in the new snapshot"
        )

    raise VerificationError(f"unrecognized incident symptom shape, cannot determine how to verify it: {incident.symptom!r}")
