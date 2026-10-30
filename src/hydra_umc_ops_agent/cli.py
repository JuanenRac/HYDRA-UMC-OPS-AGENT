# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/cli.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Real CLI entry point for every delivery shipped so far:

- Delivery 1: `edge collect` / `control show`.
- Delivery 2: `control diagnose` (an AI-assisted suggestion, never
  applied automatically).
- Delivery 3: `control propose` / `control approve` / `control reject`
  (a human-approved change proposal - nothing is deployed by these).
- Delivery 4: `control deploy-canary` (only ever runs against an
  APPROVED proposal - see canary_deploy.py's own module docstring for
  the full safety sequence).
- Delivery 5: `control verify` (re-runs the real check that originally
  produced an incident).

Approvals are signed (see approval_signing.py): `control keygen` makes an
approver's key pair, `control approve` signs with the private key, and
`control deploy-canary` verifies against a registry of public keys
(`--approvers` or the OPS_AGENT_APPROVERS environment variable). Every
deploy, rollback and prune is written to an append-only audit journal.

No GUI yet - this delivery is explicitly CLI-only, matching
HYDRA-UMC-UPDATER's own CLI-first, GUI-later precedent for a new
project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
from datetime import timedelta
from pathlib import Path

from . import __version__
from ._atomic import atomic_write_text
from .log_redaction import redact_json
from .approval_signing import (
    ApprovalSigningError,
    generate_keypair,
    load_approvers,
    load_private_key,
)
from .audit_journal import AuditJournalError, append_event, verify_chain
from .deploy_policy import DEFAULT_POLICY_FILE, POLICY_ENV, DeployPolicyError, load_policy
from .canary_deploy import (
    CanaryDeployError,
    clear_pending_canary,
    deploy_canary,
    list_backups,
    prune_backups,
    recover_interrupted_promotions,
    rollback_deploy,
)
from .change_proposal import (
    ChangeProposalError,
    approve_change,
    load_proposal,
    propose_change,
    reject_change,
    save_proposal,
)
from .control_plane import SnapshotLoadError, load_snapshot, render_snapshot_report
from .diagnosis import DiagnosisError, diagnose_incident
from .edge_agent import collect_snapshot
from .incident import MaintenanceIncident
from .incident_store import IncidentStoreError
from .inventory import read_git_commit_hash
from .verification import VerificationError, verify_incident_resolved

APPROVERS_ENV = "OPS_AGENT_APPROVERS"
AUDIT_ENV = "OPS_AGENT_AUDIT_JOURNAL"


def _split_command(command: str) -> list[str]:
    """Splits a real shell-like command string into argv tokens without
    mangling a Windows path - plain `shlex.split()` treats backslash as
    an escape character in POSIX mode, which silently corrupts a value
    like `C:\\Users\\...\\python.exe` (real bug, found live via this
    project's own CLI test for `control deploy-canary` on this
    development machine). Disabling `escape` keeps real quoted
    arguments ("tools/build test.py") working while leaving every
    backslash alone."""
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    return list(lexer)


def _dump(value: object) -> str:
    """The one place a structured result becomes text for stdout or a file:
    every string in it, and every value under a secret-named key, is redacted."""
    return json.dumps(redact_json(value), indent=2)


def _write_output(path: str, payload: str) -> bool:
    """Writes `payload` to `path` all-or-nothing; a path that cannot be
    written is one clear line on stderr, not a traceback."""
    try:
        atomic_write_text(Path(path), payload)
    except OSError as exc:
        print(f"ERROR: could not write {path!r}: {exc}", file=sys.stderr)
        return False
    return True


def _audit_file(args: argparse.Namespace, default_dir: Path) -> Path:
    explicit = getattr(args, "audit_journal", None) or os.environ.get(AUDIT_ENV)
    return Path(explicit) if explicit else default_dir / "ops-agent-audit.jsonl"


def _record(args: argparse.Namespace, default_dir: Path, event: str, data: dict[str, object]) -> None:
    """Writes one audit record; a journal that cannot be written is said, not hidden."""
    try:
        append_event(_audit_file(args, default_dir), event, data)
    except (AuditJournalError, OSError, TimeoutError) as exc:
        print(f"WARNING: could not write the audit journal: {exc}", file=sys.stderr)


def _cmd_edge_collect(args: argparse.Namespace) -> int:
    try:
        snapshot = collect_snapshot(
            source_node=args.node_name,
            projects_root=Path(args.projects_root),
            systemd_units=args.systemd_unit or None,
            http_health_urls=args.http_health_url or None,
            incident_store_path=Path(args.incident_store) if args.incident_store else None,
        )
    except (IncidentStoreError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    payload = _dump(snapshot.to_dict())
    if args.out:
        if not _write_output(args.out, payload):
            return 1
        print(f"Wrote snapshot to {args.out} ({len(snapshot.incidents)} incident(s)).")
    else:
        print(payload)
    return 0


def _cmd_control_show(args: argparse.Namespace) -> int:
    try:
        snapshot = load_snapshot(Path(args.snapshot_file))
    except SnapshotLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(render_snapshot_report(snapshot))
    return 0


def _find_incident(snapshot: dict[str, object], incident_id: str) -> MaintenanceIncident | None:
    """The incident with `incident_id`, or None. A snapshot is a file anyone
    can edit: a section that is not a list, an entry that is not an object,
    or a record missing a field is skipped (or, for the matching record,
    treated as not found) instead of ending in a traceback."""
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


def _cmd_control_diagnose(args: argparse.Namespace) -> int:
    try:
        snapshot = load_snapshot(Path(args.snapshot_file))
    except SnapshotLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    incident = _find_incident(snapshot, args.incident_id)
    if incident is None:
        print(f"ERROR: no incident with id {args.incident_id!r} in {args.snapshot_file}", file=sys.stderr)
        return 1

    try:
        result = diagnose_incident(incident, provider_name=args.provider, model=args.model)
    except DiagnosisError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = _dump(result.to_dict())
    if args.out:
        if not _write_output(args.out, payload):
            return 1
        print(f"Wrote diagnosis to {args.out}.")
    else:
        print(payload)
    return 0


def _save_proposal_or_report(proposal, path: Path) -> bool:
    try:
        save_proposal(proposal, path)
    except OSError as exc:
        print(f"ERROR: could not write {str(path)!r}: {exc}", file=sys.stderr)
        return False
    return True


def _cmd_control_propose(args: argparse.Namespace) -> int:
    try:
        snapshot = load_snapshot(Path(args.snapshot_file))
    except SnapshotLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    incident = _find_incident(snapshot, args.incident_id)
    if incident is None:
        print(f"ERROR: no incident with id {args.incident_id!r} in {args.snapshot_file}", file=sys.stderr)
        return 1
    try:
        # Bytes, decoded without newline translation: `read_text` would turn
        # a CRLF diff (a patch against a CRLF file) into LF, and the diff
        # must reach `git apply` byte for byte as reviewed.
        diff_text = Path(args.diff_file).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: could not read {args.diff_file!r}: {exc}", file=sys.stderr)
        return 1
    try:
        proposal = propose_change(
            incident_id=incident.incident_id,
            correlation_id=incident.correlation_id,
            project_name=args.project_name,
            description=args.description,
            diff=diff_text,
            rationale=args.rationale,
            allow_protected_paths=args.allow_protected_paths,
        )
    except ChangeProposalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else Path(f"proposal-{proposal.proposal_id}.json")
    if not _save_proposal_or_report(proposal, out_path):
        return 1
    _record(args, out_path.resolve().parent, "propose", {
        "proposalId": proposal.proposal_id, "incidentId": proposal.incident_id, "projectName": proposal.project_name,
        "diffSha256": hashlib.sha256(proposal.diff.encode("utf-8")).hexdigest(),
        "allowProtectedPaths": proposal.allow_protected_paths,
    })
    print(f"Wrote pending proposal {proposal.proposal_id} to {out_path}.")
    return 0


def _confirm_approval(proposal, base_commit: str | None, assume_yes: bool) -> bool:
    """Shows what is about to be signed and asks. Without `--yes` a person at a
    terminal must answer; with no terminal and no `--yes` nothing is signed."""
    digest = hashlib.sha256(proposal.diff.encode("utf-8")).hexdigest()
    print(f"Proposal   : {proposal.proposal_id}")
    print(f"Project    : {proposal.project_name}")
    print(f"Description: {proposal.description}")
    print(f"Rationale  : {proposal.rationale}")
    print(f"Diff SHA256: {digest}")
    print(f"For commit : {base_commit or '(any commit - weaker)'}")
    print(f"Protected paths allowed: {'YES' if proposal.allow_protected_paths else 'no'}")
    print("---- diff ----")
    print(proposal.diff)
    print("--------------")
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("ERROR: nothing was signed - there is no terminal to ask on; read the diff above and pass --yes", file=sys.stderr)
        return False
    return input("Sign this approval? [y/N] ").strip().lower() in ("y", "yes")


def _cmd_control_approve(args: argparse.Namespace) -> int:
    proposal_path = Path(args.proposal_file)
    try:
        proposal = load_proposal(proposal_path)
        signing_key = load_private_key(Path(args.key))
    except (ChangeProposalError, ApprovalSigningError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    base_commit: str | None = None
    if args.live_root:
        base_commit = read_git_commit_hash(Path(args.live_root))
        if base_commit is None:
            print(f"ERROR: could not read the git commit of {args.live_root!r}", file=sys.stderr)
            return 1
    elif not args.any_commit:
        print("ERROR: say which checkout this approval is for (--live-root PATH), or --any-commit to approve it for any state", file=sys.stderr)
        return 1
    if args.valid_hours <= 0:
        print("ERROR: --valid-hours must be positive", file=sys.stderr)
        return 1
    if not _confirm_approval(proposal, base_commit, args.yes):
        print("Not approved.", file=sys.stderr)
        return 1
    try:
        approved = approve_change(
            proposal, approved_by=args.approved_by, signing_key=signing_key,
            base_commit=base_commit, valid_for=timedelta(hours=args.valid_hours),
        )
    except ChangeProposalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else proposal_path
    if not _save_proposal_or_report(approved, out_path):
        return 1
    _record(args, out_path.resolve().parent, "approve", {
        "proposalId": approved.proposal_id, "approvedBy": approved.decided_by, "expiresAt": approved.approval_expires_at,
        "baseCommit": approved.approved_base_commit, "allowProtectedPaths": approved.allow_protected_paths,
        "diffSha256": hashlib.sha256(approved.diff.encode("utf-8")).hexdigest(),
    })
    print(f"Proposal {approved.proposal_id} approved by {args.approved_by!r} until {approved.approval_expires_at}. Wrote {out_path}.")
    return 0


def _cmd_control_keygen(args: argparse.Namespace) -> int:
    try:
        public = generate_keypair(Path(args.key_out), Path(args.public_out) if args.public_out else None)
    except (ApprovalSigningError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote the private key to {args.key_out} - keep it where only you can read it; it is never needed on the machine that deploys.")
    print("Add this to the approver registry (the file given to deploy-canary with --approvers):")
    print(json.dumps({"approvers": {args.name: public}}, indent=2))
    return 0


def _cmd_control_reject(args: argparse.Namespace) -> int:
    proposal_path = Path(args.proposal_file)
    try:
        proposal = load_proposal(proposal_path)
        rejected = reject_change(proposal, rejected_by=args.rejected_by, reason=args.reason)
    except ChangeProposalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else proposal_path
    if not _save_proposal_or_report(rejected, out_path):
        return 1
    _record(args, out_path.resolve().parent, "reject", {
        "proposalId": rejected.proposal_id, "rejectedBy": rejected.decided_by, "reason": rejected.decision_reason,
    })
    print(f"Proposal {rejected.proposal_id} rejected by {args.rejected_by!r}. Wrote {out_path}.")
    return 0


def _cmd_control_canary_clear(args: argparse.Namespace) -> int:
    try:
        outcome = clear_pending_canary(Path(args.live_root))
    except CanaryDeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(_dump(outcome))
    return 0


def _cmd_control_deploy_canary(args: argparse.Namespace) -> int:
    try:
        proposal = load_proposal(Path(args.proposal_file))
    except ChangeProposalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        command = _split_command(args.build_test_command)
    except ValueError as exc:
        print(f"ERROR: --build-test-command is not a valid command line: {exc}", file=sys.stderr)
        return 1
    if not command:
        print("ERROR: --build-test-command is empty", file=sys.stderr)
        return 1
    registry = args.approvers or os.environ.get(APPROVERS_ENV)
    if not registry:
        print(f"ERROR: no approver registry - pass --approvers FILE or set {APPROVERS_ENV}; without one no approval can be verified", file=sys.stderr)
        return 1
    # The deploy policy says which build-test command may run for which project; without it nothing runs.
    policy_file = args.policy or os.environ.get(POLICY_ENV) or DEFAULT_POLICY_FILE
    try:
        policy = load_policy(Path(policy_file))
    except DeployPolicyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    live_root = Path(args.live_root)
    try:
        approvers = load_approvers(Path(registry))
    except ApprovalSigningError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        for action in recover_interrupted_promotions(live_root.parent):
            print(f"Recovered an interrupted promotion: {action}")
    except Exception as exc:  # noqa: BLE001 - recovery must not stop the deploy it precedes from reporting itself
        print(f"WARNING: could not check for an interrupted promotion: {exc}", file=sys.stderr)
    try:
        result = deploy_canary(
            proposal,
            live_root=live_root,
            build_test_command=command,
            approvers=approvers,
            build_timeout_s=args.build_timeout,
            build_env_allow=args.build_env_allow or (),
            service_unit=args.service_unit,
            health_url=args.health_url or os.environ.get("OPS_AGENT_HEALTH_URL"),
            health_timeout_s=args.health_timeout,
            audit_path=Path(args.audit_journal) if args.audit_journal else None,
            keep_local_commit=args.keep_local_commit,
            policy=policy,
        )
    except CanaryDeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    payload = _dump(result.to_dict())
    if args.out:
        if not _write_output(args.out, payload):
            return 1
        print(f"Wrote canary deploy result to {args.out} (promoted={result.promoted}).")
    else:
        print(payload)
    return 0 if result.promoted else 1


def _cmd_control_verify(args: argparse.Namespace) -> int:
    try:
        snapshot = load_snapshot(Path(args.snapshot_file))
    except SnapshotLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    incident = _find_incident(snapshot, args.incident_id)
    if incident is None:
        print(f"ERROR: no incident with id {args.incident_id!r} in {args.snapshot_file}", file=sys.stderr)
        return 1
    try:
        result = verify_incident_resolved(
            incident,
            local_node_name=args.node_name,
            http_health_url=args.health_url or os.environ.get("OPS_AGENT_HEALTH_URL"),
        )
    except VerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    payload = _dump(result.to_dict())
    if args.out:
        if not _write_output(args.out, payload):
            return 1
        print(f"Wrote verification result to {args.out} (resolved={result.resolved}).")
    else:
        print(payload)
    return 0 if result.resolved else 1


def _cmd_control_rollback(args: argparse.Namespace) -> int:
    live_root = Path(args.live_root)
    try:
        used = rollback_deploy(live_root, Path(args.backup) if args.backup else None)
    except CanaryDeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _record(args, live_root.parent, "rollback", {"liveRoot": str(live_root), "backup": str(used)})
    print(f"Rolled {live_root} back to {used}. The checkout it replaced was kept beside it as {live_root.name}.rolledback-*.")
    return 0


def _cmd_control_prune_backups(args: argparse.Namespace) -> int:
    live_root = Path(args.live_root)
    try:
        existing = list_backups(live_root)
        removed = prune_backups(live_root, keep=args.keep) if not args.dry_run else existing[args.keep:]
    except (CanaryDeployError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    verb = "Would remove" if args.dry_run else "Removed"
    for path in removed:
        print(f"{verb} {path}")
    if not args.dry_run and removed:
        _record(args, live_root.parent, "prune-backups", {"liveRoot": str(live_root), "removed": [str(p) for p in removed]})
    print(f"{len(removed)} of {len(existing)} backup(s) {'would be ' if args.dry_run else ''}removed; kept the newest {args.keep}.")
    return 0


def _cmd_control_recover(args: argparse.Namespace) -> int:
    try:
        actions = recover_interrupted_promotions(Path(args.projects_root))
    except Exception as exc:  # noqa: BLE001 - one clear line, not a traceback
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for action in actions:
        print(action)
    print(f"{len(actions)} interrupted promotion(s) handled.")
    return 0


def _cmd_control_audit_verify(args: argparse.Namespace) -> int:
    problems = verify_chain(Path(args.journal_file))
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    if not problems:
        print("The audit journal is intact.")
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydra-umc-ops-agent",
        description="Maintenance-incident coordinator - evidence, diagnosis, human-approved change, canary deploy, verification (Deliveries 1-5; Delivery 6 is genuinely blocked, see README).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    edge = subparsers.add_parser("edge", help="Edge role (runs on a CM5).")
    edge_sub = edge.add_subparsers(dest="edge_command", required=True)
    collect = edge_sub.add_parser("collect", help="Collect a real, read-only inventory/health snapshot.")
    collect.add_argument("--node-name", required=True, help="This node's own identity, e.g. cm5-cell-3.")
    collect.add_argument("--projects-root", required=True, help="Directory whose immediate subdirectories are scanned for hydra-umc.project.json.")
    collect.add_argument("--systemd-unit", action="append", default=[], help="A systemd unit to check (repeatable). Skipped honestly, not faked, on a non-systemd host.")
    collect.add_argument("--http-health-url", action="append", default=[], help="An HTTP health-check URL to probe (repeatable).")
    collect.add_argument("--out", help="Write the snapshot JSON here instead of stdout.")
    collect.add_argument(
        "--incident-store",
        help="Path to a real, durable JSON file tracking incidents across runs. Given, the same "
        "ongoing problem on the same component keeps its original incidentId across repeated `edge collect` "
        "runs instead of getting a new one every time, and a genuinely re-checked, now-clean component gets "
        "its own open record marked resolved. Omitted (the default), nothing changes from before.",
    )
    collect.set_defaults(func=_cmd_edge_collect)

    control = subparsers.add_parser("control", help="Control-plane role (runs on a development host).")
    control_sub = control.add_subparsers(dest="control_command", required=True)
    show = control_sub.add_parser("show", help="Render a saved snapshot read-only.")
    show.add_argument("snapshot_file", help="Path to a snapshot JSON file produced by `edge collect`.")
    show.set_defaults(func=_cmd_control_show)

    diagnose = control_sub.add_parser(
        "diagnose",
        help="Ask an AI provider to propose a root-cause explanation for one incident (Delivery 2 - a suggestion only, never applied automatically).",
    )
    diagnose.add_argument("snapshot_file", help="Path to a snapshot JSON file produced by `edge collect`.")
    diagnose.add_argument("--incident-id", required=True, help="The incidentId (from `control show`) to diagnose.")
    diagnose.add_argument("--provider", default="anthropic", choices=("anthropic", "openai"), help="AI provider to use (default: anthropic). diagnose_incident() itself accepts any AIProvider object - this flag only selects one of the two built-in ones.")
    diagnose.add_argument("--model", help="Model id (default: a real, sensible default per provider - see docs/DIAGNOSIS.md).")
    diagnose.add_argument("--out", help="Write the diagnosis JSON here instead of stdout.")
    diagnose.set_defaults(func=_cmd_control_diagnose)

    propose = control_sub.add_parser(
        "propose",
        help="Create a pending, human-reviewable change proposal for one incident (Delivery 3 - never applies anything).",
    )
    propose.add_argument("snapshot_file", help="Path to a snapshot JSON file produced by `edge collect`.")
    propose.add_argument("--incident-id", required=True, help="The incidentId this proposal addresses.")
    propose.add_argument("--project-name", required=True, help="The real project this change targets, e.g. HYDRA-UMC-SERVER.")
    propose.add_argument("--description", required=True, help="Human-readable summary of what would change.")
    propose.add_argument("--diff-file", required=True, help="Path to a real unified-diff file with the proposed change.")
    propose.add_argument("--rationale", required=True, help="Why this change is believed to address the incident.")
    propose.add_argument("--out", help="Write the proposal JSON here (default: proposal-<id>.json).")
    propose.add_argument(
        "--allow-protected-paths", action="store_true",
        help="Allow the diff to touch CI workflows, build-test scripts, service units or provisioning scripts - the files that decide how a change is checked or run. The approver signs this decision.",
    )
    propose.add_argument("--audit-journal", help=f"Audit journal file (default: ops-agent-audit.jsonl next to the proposal, or {AUDIT_ENV}).")
    propose.set_defaults(func=_cmd_control_propose)

    approve = control_sub.add_parser("approve", help="Approve a pending proposal (Delivery 3) - the one real gate deploy-canary checks.")
    approve.add_argument("proposal_file", help="Path to a proposal JSON file produced by `control propose`.")
    approve.add_argument("--approved-by", required=True, help="The name under which your public key is registered with the approver registry.")
    approve.add_argument("--key", required=True, help="Your Ed25519 private key (made by `control keygen`); it signs the approval and never leaves your hands.")
    approve.add_argument("--live-root", help="The checkout this approval is for; the approval is valid only while it is on the commit it is on now.")
    approve.add_argument("--any-commit", action="store_true", help="Approve for any commit instead of binding to --live-root (weaker).")
    approve.add_argument("--valid-hours", type=float, default=24.0, help="How long the approval stays valid (default: 24).")
    approve.add_argument("--yes", action="store_true", help="Do not ask for confirmation (the diff is still printed first).")
    approve.add_argument("--out", help="Write the updated proposal here (default: overwrite proposal_file in place).")
    approve.add_argument("--audit-journal", help=f"Audit journal file (default: ops-agent-audit.jsonl next to the proposal, or {AUDIT_ENV}).")
    approve.set_defaults(func=_cmd_control_approve)

    keygen = control_sub.add_parser("keygen", help="Create an approver key pair (the private key signs approvals; the public key goes in the registry).")
    keygen.add_argument("--name", required=True, help="The approver's name as it will appear in the registry and in --approved-by.")
    keygen.add_argument("--key-out", required=True, help="Where to write the private key (must not exist yet).")
    keygen.add_argument("--public-out", help="Also write the public key here.")
    keygen.set_defaults(func=_cmd_control_keygen)

    reject = control_sub.add_parser("reject", help="Reject a pending proposal (Delivery 3).")
    reject.add_argument("proposal_file", help="Path to a proposal JSON file produced by `control propose`.")
    reject.add_argument("--rejected-by", required=True, help="Real name/identity of the person rejecting this.")
    reject.add_argument("--reason", required=True, help="Why this proposal is being rejected.")
    reject.add_argument("--out", help="Write the updated proposal here (default: overwrite proposal_file in place).")
    reject.add_argument("--audit-journal", help=f"Audit journal file (default: ops-agent-audit.jsonl next to the proposal, or {AUDIT_ENV}).")
    reject.set_defaults(func=_cmd_control_reject)

    deploy_canary_parser = control_sub.add_parser(
        "deploy-canary",
        help="Apply an APPROVED proposal's diff to a staged clone, verify its real build, and only then promote it (Delivery 4).",
    )
    deploy_canary_parser.add_argument("proposal_file", help="Path to an APPROVED proposal JSON file.")
    deploy_canary_parser.add_argument("--live-root", required=True, help="Path to the real, live checkout to (maybe) replace.")
    deploy_canary_parser.add_argument("--build-test-command", required=True, help="The project's own real build-test command, e.g. \"bash build-test.sh\".")
    deploy_canary_parser.add_argument("--policy", help=f"Deploy policy file: the build-test commands that may run for each project (default: {POLICY_ENV}, else {DEFAULT_POLICY_FILE}). Without it nothing is deployed.")
    deploy_canary_parser.add_argument("--build-timeout", type=float, default=600.0, help="Seconds to allow the build-test command to run (default: 600).")
    deploy_canary_parser.add_argument("--approvers", help=f"Registry of approvers' public keys (default: {APPROVERS_ENV}).")
    deploy_canary_parser.add_argument("--build-env-allow", action="append", default=[], metavar="NAME", help="An environment variable the build-test command may see (repeatable); it gets none of the operator's others.")
    deploy_canary_parser.add_argument("--service-unit", help="The systemd unit that runs from the checkout: stopped before the swap, started after it.")
    deploy_canary_parser.add_argument("--health-url", help="Health URL the promoted checkout must answer healthy; otherwise the previous one is put back (default: OPS_AGENT_HEALTH_URL).")
    deploy_canary_parser.add_argument("--health-timeout", type=float, default=30.0, help="Seconds to wait for the health check (default: 30).")
    deploy_canary_parser.add_argument("--audit-journal", help="Audit journal file (default: a hidden file next to the checkout).")
    deploy_canary_parser.add_argument("--keep-local-commit", action="store_true", help="Leave the change in the checkout as a local commit (default: no commit; the change is kept as a patch file and the checkout can still fast-forward).")
    deploy_canary_parser.add_argument("--out", help="Write the deploy result JSON here instead of stdout.")
    deploy_canary_parser.set_defaults(func=_cmd_control_deploy_canary)

    canary_clear = control_sub.add_parser("canary-clear", help="Drop a canary that is in the checkout without a local commit (the files go back to the checkout commit).")
    canary_clear.add_argument("--live-root", required=True, help="The live checkout.")
    canary_clear.set_defaults(func=_cmd_control_canary_clear)

    rollback = control_sub.add_parser("rollback", help="Put the previous checkout (a .backup-xxxxxxxx) back in place of the live one; nothing is deleted.")
    rollback.add_argument("--live-root", required=True, help="The live checkout.")
    rollback.add_argument("--backup", help="Which backup to restore (default: the newest).")
    rollback.add_argument("--audit-journal", help="Audit journal file (default: a hidden file next to the checkout).")
    rollback.set_defaults(func=_cmd_control_rollback)

    prune = control_sub.add_parser("prune-backups", help="Remove old .backup-xxxxxxxx folders of a checkout, keeping the newest few.")
    prune.add_argument("--live-root", required=True, help="The live checkout whose backups to prune.")
    prune.add_argument("--keep", type=int, default=2, help="How many of the newest backups to keep (default: 2).")
    prune.add_argument("--dry-run", action="store_true", help="Only list what would be removed.")
    prune.add_argument("--audit-journal", help="Audit journal file (default: a hidden file next to the checkout).")
    prune.set_defaults(func=_cmd_control_prune_backups)

    recover = control_sub.add_parser("recover", help="Heal a promotion that was interrupted between its two renames (needs the sdk extra).")
    recover.add_argument("--projects-root", required=True, help="The directory that holds the checkouts.")
    recover.set_defaults(func=_cmd_control_recover)

    audit_verify = control_sub.add_parser("audit-verify", help="Check the hash chain of an audit journal.")
    audit_verify.add_argument("journal_file", help="The audit journal (JSON lines).")
    audit_verify.set_defaults(func=_cmd_control_audit_verify)

    verify = control_sub.add_parser("verify", help="Re-run the real check that originally produced an incident (Delivery 5).")
    verify.add_argument("snapshot_file", help="Path to a snapshot JSON file produced by `edge collect`.")
    verify.add_argument("--incident-id", required=True, help="The incidentId to re-check.")
    verify.add_argument("--node-name", required=True, help="This host's own node name (the one it collects snapshots under). The check runs on THIS machine, so an incident from another node is refused.")
    verify.add_argument("--health-url", help="The real health URL of an HTTP incident, whose password a snapshot holds redacted (default: OPS_AGENT_HEALTH_URL).")
    verify.add_argument("--out", help="Write the verification result JSON here instead of stdout.")
    verify.set_defaults(func=_cmd_control_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
