# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/multinode_canary.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A canary across several nodes: a few first, watched, and only then the rest - or all of it undone.

The change is one already APPROVED proposal (a person's Ed25519 signature inside it; every node verifies it
against its own registry of approvers before it touches anything, so this module cannot widen what was
approved). The rollout:

1. the first `canary_nodes` nodes get the change; if any of them does not promote it, the ones that did are put
   back and the rollout stops;
2. every node that has the change is probed each `poll_seconds` for `observe_seconds` (at least once); a node that
   fails `max_failed_probes` probes - or cannot be asked - counts as unhealthy and the rollout is undone on every
   node that took the change, canary included;
3. the remaining nodes follow in waves of `wave_size` (0: all at once), each wave observed the same way;
4. only when the last wave is healthy is the rollout promoted.

A rollback restores the checkout a deploy set aside, only on nodes where this rollout saw the deploy succeed. A
node whose answer was lost in the middle of a deploy is reported as `unknown` and is NOT rolled back blindly (the
newest backup could belong to an earlier deploy); it is left for a person to look at. A rollback that fails is
reported, never hidden.

The nodes are reached through `NodeTarget`: `RemoteTarget` over the authenticated channel, `LocalTarget` for this
host, or a fake in a test. Nothing here runs unless the configuration turns it on (`multinode.enabled`).
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .audit_journal import AuditJournalError, append_event
from .change_proposal import STATUS_APPROVED, ChangeProposal
from .config import MultiNodeConfig
from .incident_transport import RemoteNode, TransportError


class MultiNodeCanaryError(RuntimeError):
    """The rollout was refused before anything was changed."""


class NodeTarget(Protocol):
    name: str

    def deploy(self, proposal: ChangeProposal) -> bool:
        """True when the node promoted the change; False when it refused or failed cleanly. Raises when the outcome is unknown."""
        ...

    def probe(self) -> tuple[bool, str]: ...

    def rollback(self, project: str) -> str: ...


class RemoteTarget:
    """A node reached over the authenticated channel."""

    def __init__(self, remote: RemoteNode) -> None:
        self.remote = remote
        self.name = remote.name

    def deploy(self, proposal: ChangeProposal) -> bool:
        try:
            result = self.remote.request("deploy", {"proposal": proposal.to_dict()})
        except TransportError as exc:
            if exc.code == "unreachable" or exc.code.startswith("reply-"):
                raise  # the answer was lost or cannot be trusted: the state of the node is unknown
            return False  # the edge answered with a refusal (its checks, its policy, an operation it does not offer): nothing changed
        return bool(result.get("promoted"))

    def probe(self) -> tuple[bool, str]:
        try:
            result = self.remote.request("health")
        except TransportError as exc:
            return False, f"{exc.code}: {exc.reason}"
        return bool(result.get("healthy")), str(result.get("detail", ""))

    def rollback(self, project: str) -> str:
        return str(self.remote.request("rollback", {"project": project}).get("restoredFrom", ""))


@dataclass
class NodeOutcome:
    name: str
    state: str = "pending"  # pending | deployed | refused | unknown | rolled-back | rollback-failed
    detail: str = ""


@dataclass
class RolloutResult:
    proposal_id: str
    project: str
    outcome: str  # promoted | rolled-back | aborted | rollback-incomplete
    started_at: str
    finished_at: str
    reason: str
    nodes: list[NodeOutcome] = field(default_factory=list)

    @property
    def promoted(self) -> bool:
        return self.outcome == "promoted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposalId": self.proposal_id, "projectName": self.project, "outcome": self.outcome,
            "startedAt": self.started_at, "finishedAt": self.finished_at, "reason": self.reason,
            "nodes": [{"name": node.name, "state": node.state, "detail": node.detail} for node in self.nodes],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_multinode_canary(
    proposal: ChangeProposal,
    targets: Sequence[NodeTarget],
    config: MultiNodeConfig,
    *,
    audit_path: Path | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> RolloutResult:
    if not config.enabled:
        raise MultiNodeCanaryError("the multi-node canary is switched off in the configuration (multinode.enabled)")
    if proposal.status != STATUS_APPROVED or not proposal.approval_signature:
        raise MultiNodeCanaryError("only a proposal with a person's signed approval can be rolled out")
    names = [target.name for target in targets]
    if not targets or len(set(names)) != len(names):
        raise MultiNodeCanaryError("give at least one node, each named once")
    if len(targets) > config.max_nodes:
        raise MultiNodeCanaryError(f"{len(targets)} nodes is more than multinode.max_nodes ({config.max_nodes})")

    result = RolloutResult(proposal.proposal_id, proposal.project_name, "aborted", _now(), "", "", [NodeOutcome(name) for name in names])
    by_name = {outcome.name: outcome for outcome in result.nodes}
    deployed: list[NodeTarget] = []

    def record(event: str, **data: Any) -> None:
        payload = {"proposalId": proposal.proposal_id, "projectName": proposal.project_name, **data}
        if audit_path is not None:
            try:
                append_event(audit_path, f"multinode-{event}", payload)
            except (AuditJournalError, OSError, TimeoutError):
                pass  # the journal failing must not leave a rollout half-managed
        if on_event is not None:
            on_event(event, payload)

    def finish(outcome: str, reason: str) -> RolloutResult:
        result.outcome, result.reason, result.finished_at = outcome, reason, _now()
        record("finished", outcome=outcome, reason=reason, nodes=[node.state for node in result.nodes])
        return result

    def undo(reason: str) -> RolloutResult:
        failed = False
        for target in reversed(deployed):
            node = by_name[target.name]
            try:
                node.detail = target.rollback(proposal.project_name) or node.detail
                node.state = "rolled-back"
            except Exception as exc:  # noqa: BLE001 - every node gets its rollback attempt
                node.state, node.detail, failed = "rollback-failed", f"{exc.__class__.__name__}: {str(exc)[:200]}", True
        failed = failed or any(node.state == "unknown" for node in result.nodes)  # a person must look at it
        record("rolled-back", reason=reason, failed=failed)
        return finish("rollback-incomplete" if failed else "rolled-back", reason)

    def observe(group: Sequence[NodeTarget]) -> str | None:
        """None when every node of the group stayed healthy; otherwise why not."""
        failures = {target.name: 0 for target in group}
        deadline = monotonic() + config.observe_seconds
        while True:
            for target in group:
                try:
                    healthy, detail = target.probe()
                except Exception as exc:  # noqa: BLE001 - a probe that cannot run is a failed probe
                    healthy, detail = False, f"{exc.__class__.__name__}"
                if not healthy:
                    failures[target.name] += 1
                    by_name[target.name].detail = detail[:200]
                    if failures[target.name] >= config.max_failed_probes:
                        return f"{target.name} failed {failures[target.name]} probe(s): {detail[:200]}"
            if monotonic() >= deadline:
                return None
            sleep(config.poll_seconds)

    def roll_out(group: Sequence[NodeTarget]) -> str | None:
        for target in group:
            node = by_name[target.name]
            try:
                promoted = target.deploy(proposal)
            except Exception as exc:  # noqa: BLE001 - the answer was lost: unknown, never rolled back blindly
                node.state, node.detail = "unknown", f"{exc.__class__.__name__}: {str(exc)[:200]}"
                return f"{target.name} did not answer the deploy; its state is unknown"
            if not promoted:
                node.state = "refused"
                return f"{target.name} did not promote the change"
            node.state = "deployed"
            deployed.append(target)
            record("deployed", node=target.name)
        return None

    first = list(targets[: config.canary_nodes])
    rest = list(targets[config.canary_nodes:])
    waves = [first]
    step = config.wave_size or len(rest) or 1
    waves += [rest[index:index + step] for index in range(0, len(rest), step)]

    for number, group in enumerate(waves):
        problem = roll_out(group)
        if problem is None:
            problem = observe(deployed)
        if problem is not None:
            record("wave-failed", wave=number, reason=problem)
            if deployed:
                return undo(problem)
            return finish("aborted", problem)
        record("wave-healthy", wave=number, nodes=[target.name for target in group])
    return finish("promoted", f"{len(deployed)} node(s) took the change and stayed healthy")
