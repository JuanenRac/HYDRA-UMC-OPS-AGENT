# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/evidence_bundle.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The EvidenceBundle of the shared contract: what this agent hands to a development node when an incident needs a change of code.

The bundle carries the versions of the components the snapshot saw, the manifests that matter, redacted excerpts of the logs, the steps that
reproduce the incident, the tests that failed, the impact, what was already tried and what the validation on the node said. Every text goes
through the redaction of this agent before it is put in, and the checksum is the SHA-256 (hex) of the canonical JSON of the bundle without the
checksum (keys sorted, no ASCII escaping), the same rule the readers apply. The shape is checked here as the contract of the SDK checks it, and
the tests compare both with the SDK when its checkout is at hand.

It only builds and writes a file; nothing is sent anywhere. The command is off until `evidence_bundle.enabled` is true.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ._atomic import atomic_write_text
from .incident import MaintenanceIncident
from .log_redaction import redact_lines, redact_secrets

_REQUIRED = (
    "componentVersions", "relevantManifests", "redactedLogExcerpts", "reproductionSteps", "failedTests",
    "impact", "actionsAttempted", "checksum", "date", "localValidationResult",
)
_TEXT_LISTS = ("relevantManifests", "redactedLogExcerpts", "reproductionSteps", "failedTests", "actionsAttempted")
NOT_VALIDATED = "The change was not validated on the node."


class EvidenceBundleError(ValueError):
    """The bundle cannot be built or is not valid."""


def bundle_checksum(content: dict[str, Any]) -> str:
    """SHA-256 (hex) of the canonical JSON of the bundle without its `checksum` field."""
    canonical = json.dumps({key: value for key, value in content.items() if key != "checksum"}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_bundle(payload: object) -> None:
    """The shape of the contract: every field, texts where texts belong, a reproduction step, a date."""
    if not isinstance(payload, dict):
        raise EvidenceBundleError("the bundle must be an object")
    missing = [name for name in _REQUIRED if name not in payload]
    if missing:
        raise EvidenceBundleError(f"missing field(s): {', '.join(missing)}")
    extra = sorted(set(payload) - set(_REQUIRED))
    if extra:
        raise EvidenceBundleError(f"unknown field(s): {', '.join(extra)}")
    if not isinstance(payload["componentVersions"], dict):
        raise EvidenceBundleError("componentVersions must be an object")
    for name in _TEXT_LISTS:
        value = payload[name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise EvidenceBundleError(f"{name} must be an array of texts")
    if not payload["reproductionSteps"]:
        raise EvidenceBundleError("reproductionSteps must have at least one step")
    for name in ("impact", "checksum", "localValidationResult", "date"):
        if not isinstance(payload[name], str) or not payload[name]:
            raise EvidenceBundleError(f"{name} must be a non-empty text")
    try:
        datetime.fromisoformat(payload["date"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceBundleError("date must be a date-time") from exc


def tail_lines(text: str, max_lines: int) -> list[str]:
    """The last `max_lines` lines of a log, redacted as a whole (a secret that spans lines is still found)."""
    lines = text.splitlines()
    return redact_lines(lines[-max_lines:] if max_lines > 0 else [])


def build_bundle(
    incident: MaintenanceIncident,
    *,
    component_versions: dict[str, str],
    manifests: Sequence[str] = (),
    log_excerpts: Sequence[str] = (),
    reproduction_steps: Sequence[str] = (),
    failed_tests: Sequence[str] = (),
    actions_attempted: Sequence[str] = (),
    local_validation_result: str = NOT_VALIDATED,
    impact: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The sealed bundle of an incident. Every text is redacted here, whatever the caller already did."""
    steps = [redact_secrets(step) for step in reproduction_steps if step.strip()]
    if not steps:
        steps = [
            f"On node {redact_secrets(incident.source_node)}, check the component {redact_secrets(incident.component)}.",
            f"Observed: {redact_secrets(incident.symptom)}",
        ]
    content: dict[str, Any] = {
        "componentVersions": {redact_secrets(str(name)): redact_secrets(str(version)) for name, version in component_versions.items()},
        "relevantManifests": [redact_secrets(text) for text in manifests],
        "redactedLogExcerpts": [redact_secrets(text) for text in log_excerpts],
        "reproductionSteps": steps,
        "failedTests": [redact_secrets(text) for text in failed_tests],
        "impact": redact_secrets(impact or f"{incident.severity} incident on {incident.source_node}: {incident.symptom}"),
        "actionsAttempted": [redact_secrets(text) for text in actions_attempted],
        "checksum": "pending",
        "date": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "localValidationResult": redact_secrets(local_validation_result) or NOT_VALIDATED,
    }
    content["checksum"] = bundle_checksum(content)
    validate_bundle(content)
    return content


def bundle_matches_checksum(payload: dict[str, Any]) -> bool:
    """A valid bundle whose checksum is that of its content."""
    validate_bundle(payload)
    return bundle_checksum(payload) == payload["checksum"]


def component_versions_of(snapshot: dict[str, Any]) -> dict[str, str]:
    """Component name to version from the `projects` of a snapshot (entries that are not objects with text fields are skipped)."""
    versions: dict[str, str] = {}
    projects = snapshot.get("projects")
    if isinstance(projects, list):
        for entry in projects:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str) and isinstance(entry.get("version"), str):
                versions[entry["name"]] = entry["version"]
    return versions


def write_bundle(bundle: dict[str, Any], path: Path) -> None:
    """Validated, then written atomically."""
    validate_bundle(bundle)
    atomic_write_text(path, json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
