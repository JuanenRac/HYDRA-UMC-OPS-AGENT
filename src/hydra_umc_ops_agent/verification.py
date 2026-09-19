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
reported "promoted".

A manifest-scan incident is the one real check kind here pinned to
actual versioned source state (a project checkout's own git commit) -
unlike a live HTTP/systemd poll, "did this really get fixed" has an
honest, checkable answer for it: did the checkout's commit actually move,
not just "does the file look fine again right now". That is exactly
HYDRA-UMC-SDK's own `ScenarioOutcome`/`compare_runs()` contract
(`clients/python/src/hydra_umc_sdk/scenario.py`) - the shared "apparent
success" control, reused here rather than a second, competing
implementation. It is genuinely optional (the `sdk` extra, lazily
imported) - a manifest incident raised before this, or one whose checkout
was never a real git repo, has no `base_commit:` evidence and degrades to
the exact same honest VerificationError this module always raised for a
manifest incident. HTTP/systemd checks are deliberately left as they
are: a live service transitioning from unreachable/inactive to
reachable/active is not "apparent success" in this sense - there
is no stable base fingerprint to compare it against (a systemd unit's
own ActiveEnterTimestamp necessarily changes on any real restart, so it
would never actually catch anything an already-covered `active` boolean
doesn't), and forcing that comparison in anyway would be decorative, not
a real additional guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .incident import EVIDENCE_BASE_COMMIT_PREFIX, MaintenanceIncident
from .inventory import (
    ManifestScanIssue,
    SystemdUnavailableError,
    check_http_health,
    check_project_manifest,
    check_systemd_unit_health,
    read_git_commit_hash,
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


class SdkUnavailableError(VerificationError):
    """The optional 'hydra-umc-sdk' package is not installed - same
    degrade-honestly shape as SystemdUnavailableError above, not a bare
    ImportError leaking out of this module."""


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
        # This
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
        return _verify_manifest_incident(incident)

    raise VerificationError(f"unrecognized incident symptom shape, cannot determine how to verify it: {incident.symptom!r}")


def _find_base_commit(evidence_refs: tuple[str, ...]) -> str | None:
    for ref in evidence_refs:
        if ref.startswith(EVIDENCE_BASE_COMMIT_PREFIX):
            return ref[len(EVIDENCE_BASE_COMMIT_PREFIX):]
    return None


def _verify_manifest_incident(incident: MaintenanceIncident) -> VerificationResult:
    """Re-checks THIS exact manifest (incident.component IS its real
    path - see incident.py's own add_manifest_issue()) via
    check_project_manifest(), then - only when a real `base_commit:`
    evidence ref was captured at detection time - runs the shared
    `compare_runs()` check against the checkout's CURRENT commit,
    so a re-check that merely "looks fine" without the checkout's own
    commit ever having moved (a stale/no-op incident, or one silently
    re-created identically by something else) is never reported as
    resolved. No `base_commit:` at all - the honest, unchanged fallback
    this module always had."""
    base_commit = _find_base_commit(incident.evidence_refs)
    if base_commit is None:
        raise VerificationError(
            "a manifest-scan incident has no automated re-check here - re-run `edge collect` "
            "against the same projects-root and confirm this incident no longer appears in the new snapshot"
        )

    manifest_path = Path(incident.component)
    checked = check_project_manifest(manifest_path)

    try:
        import hydra_umc_sdk  # type: ignore[import-not-found]  # noqa: F401
        from hydra_umc_sdk.scenario import compare_runs  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SdkUnavailableError(
            "the optional 'hydra-umc-sdk' package is not installed - run "
            "`pip install -e \".[sdk]\"` to re-verify a manifest incident against its real base commit"
        ) from exc

    observed_commit = read_git_commit_hash(manifest_path.parent)
    if observed_commit is None:
        raise VerificationError(
            f"could not read a real current git commit for {manifest_path.parent} - "
            "cannot compare it against the incident's own recorded base_commit"
        )

    now = _utc_now_iso()
    before = {
        "schema_version": "1.0", "scenario_id": incident.incident_id, "run_id": f"{incident.incident_id}:before",
        "base_fingerprint": base_commit, "phase": "before", "repro_case": incident.component,
        "observed": {"outcome": "reproduced"}, "timestamp_utc": incident.detected_at,
    }
    after = {
        "schema_version": "1.0", "scenario_id": incident.incident_id, "run_id": f"{incident.incident_id}:after",
        "base_fingerprint": observed_commit, "phase": "after", "repro_case": incident.component,
        "observed": {"outcome": "reproduced" if isinstance(checked, ManifestScanIssue) else "not-reproduced"},
        "timestamp_utc": now,
    }
    comparison = compare_runs(before, after)
    return VerificationResult(incident_id=incident.incident_id, verified_at=now, resolved=comparison.is_promotable, detail=comparison.reason)
