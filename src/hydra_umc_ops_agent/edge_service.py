# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/edge_service.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What the edge answers over the authenticated channel (see incident_transport.py).

`snapshot` hands out the current snapshot, `verify` re-runs the check of one incident on THIS machine (which
closes the case where a verification was asked of the wrong host), `health` answers whether the node is
healthy now, and `deploy` / `rollback` run a deploy of an approved proposal and the undoing of it. The last two
are not offered unless the configuration says so, and a deploy is no less guarded for arriving over the
channel: the proposal's Ed25519 approval is verified against this node's own registry of approvers, the
build-test command is the first one this node's own policy lists for the project, and the audit journal
records it.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .approval_signing import ApprovalSigningError, load_approvers
from .canary_deploy import CanaryDeployError, deploy_canary, rollback_deploy
from .change_proposal import ChangeProposal, ChangeProposalError
from .config import ProposalsConfig, TransportConfig
from .deploy_policy import DeployPolicyError, load_policy
from .incident import MaintenanceIncident
from .incident_store import IncidentStoreError
from .incident_transport import Handler, TransportError
from .proposal_intake import PendingError, decide_pending, load_pending, pending_path_for
from .verification import VerificationError, verify_incident_resolved


def find_incident(snapshot: dict[str, Any], incident_id: str) -> MaintenanceIncident | None:
    incidents = snapshot.get("incidents")
    if not isinstance(incidents, list):
        return None
    for raw in incidents:
        if isinstance(raw, dict) and raw.get("incidentId") == incident_id:
            try:
                return MaintenanceIncident.from_dict(raw)
            except (KeyError, TypeError, ValueError):
                return None
    return None


def build_handlers(
    node_name: str,
    snapshot_provider: Callable[[], dict[str, Any]],
    config: TransportConfig,
    *,
    projects_root: Path | None = None,
    health_probe: Callable[[], tuple[bool, str]] | None = None,
    health_url: str | None = None,
    service_unit: str | None = None,
    audit_path: Path | None = None,
    proposals: ProposalsConfig | None = None,
    incident_store_path: Path | None = None,
) -> dict[str, Handler]:
    """The operations this edge offers. `deploy` and `rollback` exist only with `allow_remote_deploy` and a projects root."""

    def snapshot(_: dict[str, Any]) -> dict[str, Any]:
        return snapshot_provider()

    def verify(payload: dict[str, Any]) -> dict[str, Any]:
        incident_id = payload.get("incidentId")
        if not isinstance(incident_id, str) or not incident_id:
            raise TransportError("malformed", "verify needs an incidentId")
        incident = find_incident(snapshot_provider(), incident_id)
        if incident is None:
            raise TransportError("operation-failed", f"no incident {incident_id!r} in the snapshot of this node")
        try:
            result = verify_incident_resolved(incident, local_node_name=node_name, http_health_url=health_url)
        except VerificationError as exc:
            raise TransportError("operation-failed", str(exc)) from exc
        return result.to_dict()

    def health(_: dict[str, Any]) -> dict[str, Any]:
        if health_probe is not None:
            healthy, detail = health_probe()
        else:
            critical = [item for item in snapshot_provider().get("incidents", []) if isinstance(item, dict) and item.get("severity") == "critical"]
            healthy, detail = not critical, f"{len(critical)} critical incident(s) open"
        return {"node": node_name, "healthy": healthy, "detail": detail}

    handlers: dict[str, Handler] = {"snapshot": snapshot, "verify": verify, "health": health}

    if proposals is not None and proposals.enabled and incident_store_path is not None:
        pending_file = pending_path_for(proposals, incident_store_path)

        def list_proposals(_: dict[str, Any]) -> dict[str, Any]:
            try:
                data = load_pending(pending_file)
            except IncidentStoreError as exc:
                raise TransportError("operation-failed", str(exc)) from exc
            return {"pending": data["pending"], "decided": data["decided"]}

        def decide_proposal(payload: dict[str, Any]) -> dict[str, Any]:
            incident_id, decision, by = payload.get("incidentId"), payload.get("decision"), payload.get("by")
            if not isinstance(incident_id, str) or decision not in ("approved", "rejected") or not isinstance(by, str):
                raise TransportError("malformed", "proposal-decide needs incidentId, decision (approved or rejected) and by")
            try:
                return decide_pending(pending_file, incident_store_path, incident_id, decision, by=by)
            except (PendingError, IncidentStoreError) as exc:
                raise TransportError("operation-failed", str(exc)) from exc

        handlers["proposals"] = list_proposals
        handlers["proposal-decide"] = decide_proposal
    if not (config.allow_remote_deploy and projects_root is not None):
        return handlers

    def _loaded_policy() -> Any:
        if not config.policy_file:
            raise TransportError("operation-disabled", "transport.policy_file is not set; a remote deploy runs only what a policy lists")
        try:
            return load_policy(Path(config.policy_file))
        except DeployPolicyError as exc:
            raise TransportError("operation-disabled", str(exc)) from exc

    def deploy(payload: dict[str, Any]) -> dict[str, Any]:
        if not config.approvers_file:
            raise TransportError("operation-disabled", "transport.approvers_file is not set; an approval cannot be verified without it")
        try:
            proposal = ChangeProposal.from_dict(payload.get("proposal", {}))
            approvers = load_approvers(Path(config.approvers_file))
        except (ChangeProposalError, ApprovalSigningError, KeyError, TypeError) as exc:
            raise TransportError("malformed", f"the proposal or the approvers could not be read: {exc.__class__.__name__}") from exc
        policy = _loaded_policy()
        project = policy.projects.get(proposal.project_name)
        if project is None:
            raise TransportError("operation-failed", f"the policy of this node does not list {proposal.project_name!r}")
        assert projects_root is not None
        try:
            result = deploy_canary(
                proposal, live_root=projects_root / proposal.project_name, build_test_command=list(project.build_test_commands[0]),
                approvers=approvers, build_timeout_s=config.build_timeout_seconds, service_unit=service_unit, health_url=health_url,
                audit_path=audit_path, policy=policy,
            )
        except CanaryDeployError as exc:
            raise TransportError("operation-failed", str(exc)) from exc
        return result.to_dict()

    def rollback(payload: dict[str, Any]) -> dict[str, Any]:
        project = payload.get("project")
        if not isinstance(project, str) or not project or "/" in project or "\\" in project or project in (".", ".."):
            raise TransportError("malformed", "rollback needs a project name")
        assert projects_root is not None
        try:
            used = rollback_deploy(projects_root / project)
        except CanaryDeployError as exc:
            raise TransportError("operation-failed", str(exc)) from exc
        return {"project": project, "restoredFrom": str(used)}

    handlers["deploy"] = deploy
    handlers["rollback"] = rollback
    return handlers
