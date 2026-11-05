# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/cli_extra.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The commands that depend on the configuration file (see config.py); each one refuses to run, with the name of
the switch, when its feature is off:

* `edge serve` - the authenticated channel (transport), with the metrics route when enabled;
* `edge healing-ingest` - the node watchdog's transitions into the incident store (healing);
* `edge proposals-ingest` - the incident proposals the watchdog publishes to the broker, listened to for a while (proposals);
* `control remote <operation>` - a request over the channel to an edge node (transport);
* `control canary-rollout` - one approved proposal to several nodes, watched, undone on a failure (multinode);
* `control propose-from-diagnosis` - a model drafts a PENDING proposal (llm_propose);
* `control metrics` - the incident store as Prometheus text (metrics).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .audit_journal import append_event
from .change_proposal import ChangeProposalError, load_proposal, save_proposal
from .config import CONFIG_ENV, DEFAULT_CONFIG_FILE, AgentConfig, ConfigError, load_config
from .control_plane import SnapshotLoadError, load_snapshot
from .deploy_policy import DEFAULT_POLICY_FILE, POLICY_ENV, DeployPolicyError, load_policy
from .diagnosis import DiagnosisResult
from .edge_agent import collect_snapshot
from .edge_service import build_handlers, find_incident
from .healing_bridge import ingest
from .incident_store import IncidentStoreError, load_incident_store
from .incident_transport import (
    EdgeService,
    RemoteNode,
    SqliteVerifierState,
    TransportError,
    TransportPolicy,
    load_registry,
    make_server,
)
from .llm_propose import ProposalGenerationError, collect_context, propose_from_diagnosis
from .log_redaction import redact_json
from .messages import translate
from .metrics import collect_metrics
from .multinode_canary import MultiNodeCanaryError, RemoteTarget, run_multinode_canary
from .notify import MqttPublisher, NotifyError, Notifier
from .proposal_intake import (
    MqttSubscriber, PendingError, decide_pending, load_pending, pending_path_for, run_intake,
)


def _config(args: argparse.Namespace) -> AgentConfig | None:
    explicit = getattr(args, "config", None) or os.environ.get(CONFIG_ENV)
    path = Path(explicit) if explicit else Path(DEFAULT_CONFIG_FILE)
    if explicit and not path.is_file():
        print(f"ERROR: the configuration file {explicit!r} does not exist", file=sys.stderr)
        return None
    try:
        return load_config(path)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return None


def scenario_outcome_sink(config: AgentConfig) -> tuple[Any, list[dict[str, Any]]]:
    """(the function that hands a ScenarioOutcome to HYDRA-UMC-SERVER, the list of what came of each one); (None, []) while the section is off."""
    settings = config.scenario_ingest
    sent: list[dict[str, Any]] = []
    if not settings.enabled:
        return None, sent
    from .scenario_ingest import IngestSettings, post_scenario_outcome

    ingest = IngestSettings(
        server_url=settings.server_url or "", token_file=settings.token_file, username=settings.username,
        password_file=settings.password_file, timeout_seconds=settings.timeout_seconds, allow_plain_http=settings.allow_plain_http,
    )

    def sink(outcome: dict[str, Any]) -> None:
        result = post_scenario_outcome(outcome, ingest)
        sent.append({"phase": outcome.get("phase"), "ok": result.ok, "detail": result.detail})

    return sink, sent


def _out(args: argparse.Namespace, value: Any) -> int:
    from . import cli

    payload = cli._dump(value)
    if getattr(args, "out", None):
        if not cli._write_output(args.out, payload):
            return 1
        print(f"Wrote {args.out}.")
    else:
        print(payload)
    return 0


def make_notifier(config: AgentConfig) -> Notifier | None:
    """A notifier for the configuration, or None when notifications are off. Credentials come from the environment variables it names."""
    settings = config.notify
    if not settings.enabled:
        return None
    publisher = MqttPublisher(
        settings.broker_host, settings.broker_port, tls=settings.tls, timeout_s=settings.timeout_seconds,
        username=os.environ.get(settings.username_env) if settings.username_env else None,
        password=os.environ.get(settings.password_env) if settings.password_env else None,
    )
    return Notifier(settings, publisher)


def collect_with_notification(args: argparse.Namespace, config: AgentConfig) -> int:
    """`edge collect` when notifications are on: the same collection, then an event for each incident that opened or closed."""
    from . import cli

    notifier = make_notifier(config)
    store_path = Path(args.incident_store) if args.incident_store else None
    before = load_incident_store(store_path) if store_path else []
    snapshot = collect_snapshot(
        source_node=args.node_name, projects_root=Path(args.projects_root), systemd_units=args.systemd_unit or None,
        http_health_urls=args.http_health_url or None, incident_store_path=store_path, host_checks=config.host_checks,
    )
    if notifier is not None and store_path is not None:
        notifier.flush_outbox()
        notifier.notify_changes(before, load_incident_store(store_path))
    payload = cli._dump(snapshot.to_dict())
    if args.out:
        if not cli._write_output(args.out, payload):
            return 1
        print(f"Wrote snapshot to {args.out} ({len(snapshot.incidents)} incident(s)).")
    else:
        print(payload)
    return 0


# ---------------------------------------------------------------------------
def _cmd_edge_serve(args: argparse.Namespace) -> int:
    config = _config(args)
    if config is None:
        return 1
    transport = config.transport
    try:
        if not transport.registry_file or not transport.state_file:
            raise TransportError("operation-disabled", "transport.registry_file and transport.state_file must be set")
        registry = load_registry(Path(transport.registry_file))
        projects_root = Path(args.projects_root) if args.projects_root else None
        if args.snapshot_file:
            def provider() -> dict[str, Any]:
                return load_snapshot(Path(args.snapshot_file))
        elif projects_root is not None:
            def provider() -> dict[str, Any]:
                fresh = collect_snapshot(args.node_name, projects_root, systemd_units=args.systemd_unit or None,
                                         http_health_urls=args.http_health_url or None,
                                         incident_store_path=Path(args.incident_store) if args.incident_store else None,
                                         host_checks=config.host_checks)
                redacted: dict[str, Any] = redact_json(fresh.to_dict())  # type: ignore[assignment]
                return redacted
        else:
            raise TransportError("operation-disabled", "give --snapshot-file or --projects-root so there is something to serve")
        handlers = build_handlers(args.node_name, provider, transport, projects_root=projects_root,
                                  health_url=args.health_url or os.environ.get("OPS_AGENT_HEALTH_URL"), service_unit=args.service_unit,
                                  audit_path=Path(args.audit_journal) if args.audit_journal else None,
                                  proposals=config.proposals, incident_store_path=Path(args.incident_store) if args.incident_store else None)
        service = EdgeService(args.node_name, registry, TransportPolicy.from_config(transport), SqliteVerifierState(Path(transport.state_file)), handlers)
        metrics_fn = None
        token = None
        if config.metrics.enabled and args.incident_store:
            token = os.environ.get(config.metrics.token_env) if config.metrics.token_env else None
            if transport.bind not in ("127.0.0.1", "::1", "localhost") and not token:
                raise TransportError("operation-disabled", "the metrics route outside the loopback needs metrics.token_env to name a set variable")
            store_path = Path(args.incident_store)
            audit_path = Path(args.audit_journal) if args.audit_journal else None
            def metrics_fn() -> str:  # noqa: E306
                return collect_metrics(config.metrics, store_path, audit_path)
        server = make_server(service, transport, metrics=metrics_fn, metrics_token=token)
    except (TransportError, SnapshotLoadError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Serving node {args.node_name!r} on {transport.bind}:{transport.port} (deploy over the channel: {'ON' if 'deploy' in handlers else 'off'}).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _cmd_edge_healing_ingest(args: argparse.Namespace) -> int:
    config = _config(args)
    if config is None:
        return 1
    try:
        result = ingest(config.healing, Path(args.incident_store), notifier=make_notifier(config))
    except (IncidentStoreError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Read {result.transitions} transition(s): {result.opened_or_updated} opened or updated, {result.resolved} resolved.")
    return 0


def _cmd_edge_proposals_ingest(args: argparse.Namespace) -> int:
    config = _config(args)
    if config is None:
        return 1
    settings = config.proposals
    subscriber = MqttSubscriber(
        settings.broker_host, settings.broker_port, tls=settings.tls, timeout_s=settings.timeout_seconds,
        username=os.environ.get(settings.username_env) if settings.username_env else None,
        password=os.environ.get(settings.password_env) if settings.password_env else None,
    )
    try:
        result = run_intake(settings, Path(args.incident_store), subscriber, notifier=make_notifier(config),
                            pending_path=Path(args.pending_store) if args.pending_store else None)
    except (IncidentStoreError, NotifyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    refused = ", ".join(f"{reason}={count}" for reason, count in sorted(result.refused.items())) or "none"
    print(f"Received {result.received} message(s): {result.accepted} accepted ({result.pending} waiting for a person, "
          f"{result.pending_full} dropped because the pending list is full), retained ignored {result.ignored_retained}, "
          f"rate limited {result.rate_limited}, refused: {refused}.")
    return 0


def _pending_file(args: argparse.Namespace, config: AgentConfig) -> Path:
    return Path(args.pending_store) if args.pending_store else pending_path_for(config.proposals, Path(args.incident_store))


def _cmd_edge_proposals_list(args: argparse.Namespace) -> int:
    config = _config(args)
    if config is None:
        return 1
    if not config.proposals.enabled:
        print("ERROR: the incident proposals are switched off in the configuration (proposals.enabled)", file=sys.stderr)
        return 1
    try:
        data = load_pending(_pending_file(args, config))
    except IncidentStoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"pending": data["pending"], "decided": data["decided"]}, indent=2))
    return 0


def _cmd_edge_proposals_decide(args: argparse.Namespace) -> int:
    config = _config(args)
    if config is None:
        return 1
    if not config.proposals.enabled:
        print("ERROR: the incident proposals are switched off in the configuration (proposals.enabled)", file=sys.stderr)
        return 1
    try:
        record = decide_pending(_pending_file(args, config), Path(args.incident_store), args.incident_id,
                                "approved" if args.decision == "approve" else "rejected", by=args.by, notifier=make_notifier(config))
    except (PendingError, IncidentStoreError, NotifyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record))
    return 0


def _remote(args: argparse.Namespace, config: AgentConfig) -> RemoteNode:
    if not config.transport.enabled:
        raise TransportError("operation-disabled", "the transport is switched off in the configuration (transport.enabled)")
    if not config.transport.registry_file:
        raise TransportError("operation-disabled", "transport.registry_file is not set")
    return RemoteNode(args.node, args.url, args.local_node, load_registry(Path(config.transport.registry_file)),
                      policy=TransportPolicy.from_config(config.transport), timeout_s=config.transport.request_timeout_seconds)


def _cmd_control_remote(args: argparse.Namespace) -> int:
    config = _config(args)
    if config is None:
        return 1
    payload: dict[str, Any] = {}
    try:
        remote = _remote(args, config)
        if args.operation == "verify":
            payload["incidentId"] = args.incident_id
        elif args.operation == "rollback":
            payload["project"] = args.project
        elif args.operation == "deploy":
            payload["proposal"] = load_proposal(Path(args.proposal_file)).to_dict()
        elif args.operation == "proposal-decide":
            if not (args.incident_id and args.decision and args.by):
                print("ERROR: proposal-decide needs --incident-id, --decision and --by", file=sys.stderr)
                return 1
            payload.update({"incidentId": args.incident_id, "decision": args.decision, "by": args.by})
        if args.operation in ("verify", "rollback", "deploy") and not (args.incident_id or args.project or args.proposal_file):
            print(f"ERROR: {args.operation} needs its argument", file=sys.stderr)
            return 1
        result = remote.request(args.operation, payload)
    except (TransportError, ChangeProposalError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return _out(args, result)


def _cmd_control_canary_rollout(args: argparse.Namespace) -> int:
    config = _config(args)
    if config is None:
        return 1
    try:
        proposal = load_proposal(Path(args.proposal_file))
        if not config.transport.enabled or not config.transport.registry_file:
            raise TransportError("operation-disabled", "the rollout reaches nodes over the channel: transport.enabled and transport.registry_file are needed")
        registry = load_registry(Path(config.transport.registry_file))
        targets = []
        for spec in args.target:
            name, separator, url = spec.partition("=")
            if not separator or not name or not url:
                raise TransportError("malformed", f"--target must be NAME=URL, not {spec!r}")
            targets.append(RemoteTarget(RemoteNode(name, url, args.local_node, registry, policy=TransportPolicy.from_config(config.transport),
                                                   timeout_s=config.transport.request_timeout_seconds)))
        notifier = make_notifier(config)

        def on_event(event: str, data: dict[str, Any]) -> None:
            if notifier is not None and event == "rolled-back":
                notifier.send({"schema_version": "1.0", "event_id": data["proposalId"], "type": "ops.canary.rolled_back",
                               "source": config.notify.source, "node": "fleet", "language": config.notify.language,
                               "timestamp_utc": "", "sequence": 0,
                               "message": translate("canary.rolled_back", config.notify.language, node=data["projectName"], detail=data["reason"])})

        result = run_multinode_canary(proposal, targets, config.multinode,
                                      audit_path=Path(args.audit_journal) if args.audit_journal else None, on_event=on_event)
    except (TransportError, MultiNodeCanaryError, ChangeProposalError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    code = _out(args, result.to_dict())
    return code if code else (0 if result.promoted else 1)


def _cmd_control_propose_from_diagnosis(args: argparse.Namespace) -> int:
    from . import cli

    config = _config(args)
    if config is None:
        return 1
    try:
        snapshot = load_snapshot(Path(args.snapshot_file))
        incident = find_incident(snapshot, args.incident_id)
        if incident is None:
            print(f"ERROR: no incident with id {args.incident_id!r} in {args.snapshot_file}", file=sys.stderr)
            return 1
        diagnosis = DiagnosisResult.from_dict(json.loads(Path(args.diagnosis_file).read_text(encoding="utf-8"))) if args.diagnosis_file else None
        policy_file = args.policy or os.environ.get(POLICY_ENV) or DEFAULT_POLICY_FILE
        policy = load_policy(Path(policy_file))
        live_root = Path(args.live_root)
        context = collect_context(live_root, args.file, policy, args.project_name)
        draft = propose_from_diagnosis(incident, diagnosis, config.llm_propose, project_name=args.project_name, context=context,
                                       live_root=live_root, policy=policy, language=args.language or config.notify.language)
        out_path = Path(args.out) if args.out else Path(f"proposal-{draft.proposal.proposal_id}.json")
        save_proposal(draft.proposal, out_path)
    except (ProposalGenerationError, SnapshotLoadError, DeployPolicyError, ChangeProposalError, ValueError, KeyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        append_event(cli._audit_file(args, out_path.resolve().parent), "propose-generated",
                     {"proposalId": draft.proposal.proposal_id, "incidentId": incident.incident_id, "projectName": args.project_name,
                      "generatedBy": draft.proposal.generated_by, "files": draft.files})
    except Exception as exc:  # noqa: BLE001 - said, not hidden
        print(f"WARNING: could not write the audit journal: {exc}", file=sys.stderr)
    print(f"Wrote PENDING proposal {draft.proposal.proposal_id} to {out_path}. {translate('proposal.generated', args.language or config.notify.language, project=args.project_name)}")
    return 0


def _cmd_control_metrics(args: argparse.Namespace) -> int:
    from . import cli

    config = _config(args)
    if config is None:
        return 1
    try:
        text = collect_metrics(config.metrics, Path(args.incident_store), Path(args.audit_journal) if args.audit_journal else None)
    except IncidentStoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.out:
        return 0 if cli._write_output(args.out, text) else 1
    sys.stdout.write(text)
    return 0


def register(edge_sub: Any, control_sub: Any) -> None:
    serve = edge_sub.add_parser("serve", help="Serve this node over the authenticated channel (needs transport.enabled in the configuration).")
    serve.add_argument("--node-name", required=True, help="This node's identity; it must be in the node registry.")
    serve.add_argument("--snapshot-file", help="Serve the snapshot in this file (read again on every request).")
    serve.add_argument("--projects-root", help="Collect a fresh snapshot of this directory on every request; also where a remote deploy finds its checkouts.")
    serve.add_argument("--systemd-unit", action="append", default=[], help="A systemd unit to check when collecting (repeatable).")
    serve.add_argument("--http-health-url", action="append", default=[], help="An HTTP health URL to probe when collecting (repeatable).")
    serve.add_argument("--incident-store", help="Incident store used when collecting, and read by the metrics route.")
    serve.add_argument("--health-url", help="Health URL a deploy must answer and the `health` operation reports (default: OPS_AGENT_HEALTH_URL).")
    serve.add_argument("--service-unit", help="The systemd unit a remote deploy stops and starts.")
    serve.add_argument("--audit-journal", help="Audit journal file.")
    serve.set_defaults(func=_cmd_edge_serve)

    ingest_parser = edge_sub.add_parser("healing-ingest", help="Turn the new transitions of the node watchdog's journal into incidents (needs healing.enabled).")
    ingest_parser.add_argument("--incident-store", required=True, help="The durable incident store (the one `edge collect --incident-store` uses).")
    ingest_parser.set_defaults(func=_cmd_edge_healing_ingest)

    proposals_parser = edge_sub.add_parser("proposals-ingest", help="Listen to the broker for the incident proposals of the node watchdog and open them as incidents to review (needs proposals.enabled).")
    proposals_parser.add_argument("--incident-store", required=True, help="The durable incident store (the one `edge healing-ingest` uses).")
    proposals_parser.add_argument("--pending-store", help="Where the proposals wait for a person (default: proposals.pending_store, or next to the incident store).")
    proposals_parser.set_defaults(func=_cmd_edge_proposals_ingest)

    listing = edge_sub.add_parser("proposals-list", help="Show the proposals that wait for a person and the decisions taken (needs proposals.enabled).")
    listing.add_argument("--incident-store", required=True)
    listing.add_argument("--pending-store")
    listing.set_defaults(func=_cmd_edge_proposals_list)

    deciding = edge_sub.add_parser("proposals-decide", help="Approve (opens the incident) or reject a pending proposal (needs proposals.enabled).")
    deciding.add_argument("decision", choices=("approve", "reject"))
    deciding.add_argument("incident_id")
    deciding.add_argument("--by", required=True, help="Who decides (a label of letters, digits and . _ : -).")
    deciding.add_argument("--incident-store", required=True)
    deciding.add_argument("--pending-store")
    deciding.set_defaults(func=_cmd_edge_proposals_decide)

    remote = control_sub.add_parser("remote", help="Ask an edge node over the authenticated channel (needs transport.enabled).")
    remote.add_argument("operation", choices=("snapshot", "verify", "health", "deploy", "rollback", "proposals", "proposal-decide"))
    remote.add_argument("--url", required=True, help="Base URL of the edge, e.g. http://192.168.0.180:18310.")
    remote.add_argument("--node", required=True, help="The edge node's identity in the registry.")
    remote.add_argument("--local-node", required=True, help="This host's identity in the registry.")
    remote.add_argument("--incident-id", help="For verify and proposal-decide.")
    remote.add_argument("--decision", choices=("approved", "rejected"), help="For proposal-decide.")
    remote.add_argument("--by", help="For proposal-decide: who decides.")
    remote.add_argument("--project", help="For rollback.")
    remote.add_argument("--proposal-file", help="For deploy: an APPROVED proposal; the edge verifies the approval itself.")
    remote.add_argument("--out", help="Write the result JSON here instead of stdout.")
    remote.set_defaults(func=_cmd_control_remote)

    rollout = control_sub.add_parser("canary-rollout", help="Roll one approved proposal out to several nodes: a few first, watched, undone on a failure (needs multinode.enabled).")
    rollout.add_argument("proposal_file", help="An APPROVED proposal.")
    rollout.add_argument("--target", action="append", required=True, metavar="NAME=URL", help="An edge node (repeatable); the first ones are the canary.")
    rollout.add_argument("--local-node", required=True, help="This host's identity in the registry.")
    rollout.add_argument("--audit-journal", help="Audit journal file.")
    rollout.add_argument("--out", help="Write the rollout result JSON here instead of stdout.")
    rollout.set_defaults(func=_cmd_control_canary_rollout)

    draft = control_sub.add_parser("propose-from-diagnosis", help="A local model drafts a PENDING proposal for an incident; a person must still approve it (needs llm_propose.enabled).")
    draft.add_argument("snapshot_file", help="Snapshot JSON produced by `edge collect`.")
    draft.add_argument("--incident-id", required=True)
    draft.add_argument("--project-name", required=True, help="The project the change is for; the deploy policy must list it.")
    draft.add_argument("--live-root", required=True, help="The checkout; the draft must apply cleanly to it.")
    draft.add_argument("--file", action="append", required=True, help="A file of the checkout the model may see and change (repeatable).")
    draft.add_argument("--diagnosis-file", help="A diagnosis JSON (from `control diagnose`) to base the draft on.")
    draft.add_argument("--policy", help=f"Deploy policy file (default: {POLICY_ENV}, else {DEFAULT_POLICY_FILE}).")
    draft.add_argument("--language", choices=("en", "es", "de", "fr", "it", "ja", "zh", "pt"), help="Language of the marker and the notice (default: notify.language).")
    draft.add_argument("--audit-journal", help="Audit journal file.")
    draft.add_argument("--out", help="Write the proposal here (default: proposal-<id>.json).")
    draft.set_defaults(func=_cmd_control_propose_from_diagnosis)

    metrics = control_sub.add_parser("metrics", help="Print the incident store as Prometheus text (needs metrics.enabled).")
    metrics.add_argument("--incident-store", required=True)
    metrics.add_argument("--audit-journal", help="Also count the records of this audit journal.")
    metrics.add_argument("--out", help="Write the text here instead of stdout.")
    metrics.set_defaults(func=_cmd_control_metrics)
