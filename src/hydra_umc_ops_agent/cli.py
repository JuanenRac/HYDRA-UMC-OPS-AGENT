# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/cli.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
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

No GUI yet - this delivery is explicitly CLI-only, matching
HYDRA-UMC-UPDATER's own CLI-first, GUI-later precedent for a new
project.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from . import __version__
from .canary_deploy import CanaryDeployError, deploy_canary
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
from .verification import VerificationError, verify_incident_resolved


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


def _cmd_edge_collect(args: argparse.Namespace) -> int:
    snapshot = collect_snapshot(
        source_node=args.node_name,
        projects_root=Path(args.projects_root),
        systemd_units=args.systemd_unit or None,
        http_health_urls=args.http_health_url or None,
    )
    payload = json.dumps(snapshot.to_dict(), indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
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
    for raw in snapshot.get("incidents", []):
        if raw.get("incidentId") == incident_id:
            return MaintenanceIncident.from_dict(raw)
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

    payload = json.dumps(result.to_dict(), indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"Wrote diagnosis to {args.out}.")
    else:
        print(payload)
    return 0


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
        diff_text = Path(args.diff_file).read_text(encoding="utf-8")
    except OSError as exc:
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
        )
    except ChangeProposalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else Path(f"proposal-{proposal.proposal_id}.json")
    save_proposal(proposal, out_path)
    print(f"Wrote pending proposal {proposal.proposal_id} to {out_path}.")
    return 0


def _cmd_control_approve(args: argparse.Namespace) -> int:
    proposal_path = Path(args.proposal_file)
    try:
        proposal = load_proposal(proposal_path)
        approved = approve_change(proposal, approved_by=args.approved_by)
    except ChangeProposalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else proposal_path
    save_proposal(approved, out_path)
    print(f"Proposal {approved.proposal_id} approved by {args.approved_by!r}. Wrote {out_path}.")
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
    save_proposal(rejected, out_path)
    print(f"Proposal {rejected.proposal_id} rejected by {args.rejected_by!r}. Wrote {out_path}.")
    return 0


def _cmd_control_deploy_canary(args: argparse.Namespace) -> int:
    try:
        proposal = load_proposal(Path(args.proposal_file))
    except ChangeProposalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        result = deploy_canary(
            proposal,
            live_root=Path(args.live_root),
            build_test_command=_split_command(args.build_test_command),
            build_timeout_s=args.build_timeout,
        )
    except CanaryDeployError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(result.to_dict(), indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
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
        result = verify_incident_resolved(incident)
    except VerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(result.to_dict(), indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"Wrote verification result to {args.out} (resolved={result.resolved}).")
    else:
        print(payload)
    return 0 if result.resolved else 1


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
    propose.set_defaults(func=_cmd_control_propose)

    approve = control_sub.add_parser("approve", help="Approve a pending proposal (Delivery 3) - the one real gate deploy-canary checks.")
    approve.add_argument("proposal_file", help="Path to a proposal JSON file produced by `control propose`.")
    approve.add_argument("--approved-by", required=True, help="Real name/identity of the person approving this - never blank.")
    approve.add_argument("--out", help="Write the updated proposal here (default: overwrite proposal_file in place).")
    approve.set_defaults(func=_cmd_control_approve)

    reject = control_sub.add_parser("reject", help="Reject a pending proposal (Delivery 3).")
    reject.add_argument("proposal_file", help="Path to a proposal JSON file produced by `control propose`.")
    reject.add_argument("--rejected-by", required=True, help="Real name/identity of the person rejecting this.")
    reject.add_argument("--reason", required=True, help="Why this proposal is being rejected.")
    reject.add_argument("--out", help="Write the updated proposal here (default: overwrite proposal_file in place).")
    reject.set_defaults(func=_cmd_control_reject)

    deploy_canary_parser = control_sub.add_parser(
        "deploy-canary",
        help="Apply an APPROVED proposal's diff to a staged clone, verify its real build, and only then promote it (Delivery 4).",
    )
    deploy_canary_parser.add_argument("proposal_file", help="Path to an APPROVED proposal JSON file.")
    deploy_canary_parser.add_argument("--live-root", required=True, help="Path to the real, live checkout to (maybe) replace.")
    deploy_canary_parser.add_argument("--build-test-command", required=True, help="The project's own real build-test command, e.g. \"bash build-test.sh\".")
    deploy_canary_parser.add_argument("--build-timeout", type=float, default=600.0, help="Seconds to allow the build-test command to run (default: 600).")
    deploy_canary_parser.add_argument("--out", help="Write the deploy result JSON here instead of stdout.")
    deploy_canary_parser.set_defaults(func=_cmd_control_deploy_canary)

    verify = control_sub.add_parser("verify", help="Re-run the real check that originally produced an incident (Delivery 5).")
    verify.add_argument("snapshot_file", help="Path to a snapshot JSON file produced by `edge collect`.")
    verify.add_argument("--incident-id", required=True, help="The incidentId to re-check.")
    verify.add_argument("--out", help="Write the verification result JSON here instead of stdout.")
    verify.set_defaults(func=_cmd_control_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
