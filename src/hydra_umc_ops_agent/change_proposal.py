# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/change_proposal.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Delivery 3 - Human-approved change: a concrete, reviewable change
proposal that a person must explicitly approve or reject before anything
happens to it. This module never applies a diff to anything - it only
ever creates, approves, or rejects a real, stored proposal record. See
canary_deploy.py (Delivery 4), which refuses to run against anything
that is not in the APPROVED status this module alone can set.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .log_redaction import redact_secrets

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

# A real unified diff always has one of these - `git apply` (canary_deploy.py's
# own consumer) would reject anything else anyway, but rejecting it HERE,
# before it is ever stored or shown to a human as something to approve, is
# a real, earlier and clearer failure than a cryptic git error later.
_DIFF_HEADER_RE = re.compile(r"^(--- |\+\+\+ |diff --git )", re.MULTILINE)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChangeProposalError(RuntimeError):
    """Base for every real, distinct failure this module can report."""


class InvalidDiffError(ChangeProposalError):
    """The supplied diff text does not look like a real unified diff."""


class SecretShapedDiffError(ChangeProposalError):
    """V07-005: a diff that looks like it contains a real secret
    (log_redaction.py's own detectors - a JSON/URL-credential/PEM
    shape) is refused outright at proposal time, instead of being
    silently accepted and then redacted-in-place later - redacting the
    one field that must round-trip byte-for-byte for `git apply` to
    stay a faithful preview of what was actually reviewed is exactly
    the bug this refusal exists to prevent. Remove the real secret from
    the diff (it belongs in a secrets manager/environment variable, not
    committed at all) before proposing this change."""


class ProposalLoadError(ChangeProposalError):
    """A real, distinct reason a saved proposal file could not be loaded
    - mirrors control_plane.py's own SnapshotLoadError shape."""


class InvalidTransitionError(ChangeProposalError):
    """An approve/reject was attempted on a proposal that is not
    currently PENDING - a proposal is decided exactly once, in one
    direction, and this module never lets a second decision silently
    overwrite the first."""


def _validate_diff_text(diff_text: str) -> None:
    if not diff_text.strip():
        raise InvalidDiffError("diff text is empty")
    if not _DIFF_HEADER_RE.search(diff_text):
        raise InvalidDiffError(
            "diff text does not look like a real unified diff (expected a '--- ' / '+++ ' / 'diff --git ' header line)"
        )
    # V07-005: reject a secret-shaped diff HERE, before it is ever
    # stored - see SecretShapedDiffError's own docstring for why this
    # replaces redacting it after the fact.
    if redact_secrets(diff_text) != diff_text:
        raise SecretShapedDiffError(
            "diff text looks like it contains a real secret (a JSON/URL-credential/PEM shape) - "
            "remove it before proposing this change; a diff must round-trip byte-for-byte once approved"
        )


def _content_digest(project_name: str, diff: str) -> str:
    """A real, deterministic SHA-256 over exactly the two fields a
    canary deploy actually acts on - the project it targets and the
    patch it applies. Deliberately excludes description/rationale
    (commentary, never applied) so editing those after approval (e.g.
    fixing a typo in the human-readable rationale) doesn't spuriously
    invalidate a real approval - see approve_change()'s own docstring
    for what this binds and why (V07-003)."""
    return hashlib.sha256(f"{project_name}\n{diff}".encode("utf-8")).hexdigest()


class ApprovalContentMismatchError(ChangeProposalError):
    """V07-003 (P1): an
    approval's own `status == "approved"` used to be the ONLY thing
    deploy_canary() checked - nothing tied that approval to the exact
    project or diff a human actually reviewed. A saved proposal file is
    real, mutable JSON on disk: editing `projectName`/`diff` after
    approval while leaving `status: "approved"` untouched used to let a
    reviewed-and-approved change for one project get silently applied
    to a completely different one. Raised whenever the proposal's
    current project_name/diff no longer match the real digest that was
    computed and stored at the moment of approval - editing the
    approved content invalidates the approval outright."""


@dataclass(frozen=True)
class ChangeProposal:
    """A single proposed change for one incident. Immutable - `approve_change()`/
    `reject_change()` each return a NEW instance rather than mutating this
    one, so a caller holding a reference to the original pending proposal
    never sees it silently change state out from under it."""
    proposal_id: str
    incident_id: str
    correlation_id: str
    created_at: str
    project_name: str
    description: str
    diff: str
    rationale: str
    status: str = STATUS_PENDING
    decided_by: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None
    # V07-003: set only by approve_change(), a real SHA-256 over the
    # exact project_name+diff that were true at the moment of approval
    # - see _content_digest()'s own docstring. None for a proposal that
    # was never approved (pending/rejected).
    approved_content_digest: str | None = None

    def verify_approval_content(self) -> None:
        """Raises ApprovalContentMismatchError unless this proposal's
        CURRENT project_name/diff still match the digest recorded at
        the moment of approval - see ApprovalContentMismatchError's own
        docstring. canary_deploy.py calls this before doing anything
        else, in addition to (never instead of) the existing
        status == approved check."""
        if self.status != STATUS_APPROVED:
            return  # not this check's concern - ChangeNotApprovedError already owns that
        if self.approved_content_digest is None:
            raise ApprovalContentMismatchError(
                f"proposal {self.proposal_id} is marked approved but carries no approval content digest - "
                "refusing to trust an approval that predates this check or was hand-edited"
            )
        current = _content_digest(self.project_name, self.diff)
        if current != self.approved_content_digest:
            raise ApprovalContentMismatchError(
                f"proposal {self.proposal_id}'s project/diff no longer match what was approved "
                f"(approved digest {self.approved_content_digest[:12]}..., current {current[:12]}...) - "
                "the approved content changed after approval; a new approval is required"
            )

    def to_dict(self) -> dict[str, object]:
        # V07-005 (P1): this
        # dict is not just a display view - save_proposal()/load_proposal()
        # round-trip THROUGH it, and canary_deploy.py's own _apply_diff()
        # later runs `git apply` on whatever `.diff` comes back out.
        # Redacting `diff` here used to mean a real, approved proposal's
        # own patch silently changed bytes the moment it was saved -
        # `loaded.diff != proposal.diff` - which could invalidate the
        # patch's own context or, worse, still apply cleanly against
        # DIFFERENT lines than the ones a human actually reviewed and
        # approved. `diff` is the immutable, applicable artifact and must
        # round-trip byte-for-byte - see propose_change()'s own new
        # secret-shaped-diff refusal for how a real secret is kept out of
        # it in the first place, instead of being redacted after the
        # fact. `description`/`rationale`/`decisionReason` are pure
        # human-readable commentary nothing ever applies literally, so
        # redacting THOSE for display remains real, harmless
        # defense-in-depth.
        return {
            "proposalId": self.proposal_id,
            "incidentId": self.incident_id,
            "correlationId": self.correlation_id,
            "createdAt": self.created_at,
            "projectName": self.project_name,
            "description": redact_secrets(self.description),
            "diff": self.diff,
            "rationale": redact_secrets(self.rationale),
            "status": self.status,
            "decidedBy": self.decided_by,
            "decidedAt": self.decided_at,
            "decisionReason": redact_secrets(self.decision_reason) if self.decision_reason else self.decision_reason,
            "approvedContentDigest": self.approved_content_digest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ChangeProposal":
        return cls(
            proposal_id=str(data["proposalId"]),
            incident_id=str(data["incidentId"]),
            correlation_id=str(data["correlationId"]),
            created_at=str(data["createdAt"]),
            project_name=str(data["projectName"]),
            description=str(data["description"]),
            diff=str(data["diff"]),
            rationale=str(data["rationale"]),
            status=str(data.get("status", STATUS_PENDING)),
            decided_by=data.get("decidedBy"),
            decided_at=data.get("decidedAt"),
            decision_reason=data.get("decisionReason"),
            approved_content_digest=data.get("approvedContentDigest"),
        )


def propose_change(
    *,
    incident_id: str,
    correlation_id: str,
    project_name: str,
    description: str,
    diff: str,
    rationale: str,
) -> ChangeProposal:
    """Creates a new, real PENDING proposal. Every field is required and
    non-empty - a proposal a human is about to review is not allowed to
    have a blank rationale or description, and its diff must already
    look like a real unified diff."""
    _validate_diff_text(diff)
    for field_name, value in (
        ("incident_id", incident_id),
        ("correlation_id", correlation_id),
        ("project_name", project_name),
        ("description", description),
        ("rationale", rationale),
    ):
        if not value or not value.strip():
            raise ChangeProposalError(f"{field_name} must not be empty")
    return ChangeProposal(
        proposal_id=str(uuid.uuid4()),
        incident_id=incident_id,
        correlation_id=correlation_id,
        created_at=_utc_now_iso(),
        project_name=project_name,
        description=description,
        diff=diff,
        rationale=rationale,
    )


def approve_change(proposal: ChangeProposal, *, approved_by: str) -> ChangeProposal:
    if proposal.status != STATUS_PENDING:
        raise InvalidTransitionError(
            f"cannot approve proposal {proposal.proposal_id} - status is {proposal.status!r}, not {STATUS_PENDING!r}"
        )
    if not approved_by or not approved_by.strip():
        raise ChangeProposalError("approved_by must not be empty - an approval must be attributable to a real person")
    # V07-003: bind this approval to exactly the project/diff a human
    # reviewed right now - see _content_digest()/ApprovalContentMismatchError's
    # own docstrings.
    digest = _content_digest(proposal.project_name, proposal.diff)
    return replace(
        proposal, status=STATUS_APPROVED, decided_by=approved_by, decided_at=_utc_now_iso(), decision_reason=None,
        approved_content_digest=digest,
    )


def reject_change(proposal: ChangeProposal, *, rejected_by: str, reason: str) -> ChangeProposal:
    if proposal.status != STATUS_PENDING:
        raise InvalidTransitionError(
            f"cannot reject proposal {proposal.proposal_id} - status is {proposal.status!r}, not {STATUS_PENDING!r}"
        )
    if not rejected_by or not rejected_by.strip():
        raise ChangeProposalError("rejected_by must not be empty")
    if not reason or not reason.strip():
        raise ChangeProposalError("reason must not be empty - a rejection must say why")
    return replace(proposal, status=STATUS_REJECTED, decided_by=rejected_by, decided_at=_utc_now_iso(), decision_reason=reason)


def load_proposal(path: Path) -> ChangeProposal:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProposalLoadError(f"could not read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProposalLoadError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProposalLoadError(f"{path} does not contain a JSON object")
    try:
        return ChangeProposal.from_dict(data)
    except KeyError as exc:
        raise ProposalLoadError(f"{path} is missing a required proposal field: {exc}") from exc


def save_proposal(proposal: ChangeProposal, path: Path) -> None:
    path.write_text(json.dumps(proposal.to_dict(), indent=2), encoding="utf-8")
