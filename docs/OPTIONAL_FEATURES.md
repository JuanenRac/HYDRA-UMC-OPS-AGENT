# Optional features

Everything on this page is **off** until the configuration file turns it on. The configuration is a JSON file
(`--config FILE`, else `OPS_AGENT_CONFIG`, else `/etc/hydra-umc/ops-agent.json`); without one every switch is off
and every limit has its conservative default. A file that exists but is malformed stops the command, because half
a configuration must not switch half a feature on. `deploy/ops-agent.json.example` lists every key.

The configuration holds **no secret**. It names the files (the node registry, the approvers, the policy) and the
environment variables (broker credentials, the metrics token, a model key) that do; those live outside any
repository.

| Section | Switch | What it enables |
|---|---|---|
| `transport` | `enabled` | the authenticated channel between an edge and a control host |
| `healing` | `enabled` | incidents from the node watchdog's transitions |
| `proposals` | `enabled` | incident proposals of the node watchdog, heard from the broker; they wait for a person to approve them (`auto_open` opens them directly) |
| `notify` | `enabled` | incident events published to the MQTT broker |
| `multinode` | `enabled` | a canary across several nodes |
| `llm_propose` | `enabled` | a local model drafts a pending proposal |
| `metrics` | `enabled` | Prometheus text of the incident store |
| `scenario_ingest` | `enabled` | the before/after `ScenarioOutcome` of `control verify` handed to HYDRA-UMC-SERVER |

## Authenticated channel (`transport`)

`edge serve` listens (on the loopback unless `allow_non_loopback` is set) and answers `snapshot`, `verify` and
`health`; with `allow_remote_deploy` it also answers `deploy` and `rollback`. `control remote <operation>` asks.

* Every message is signed with the shared secret of the node that sends it (HMAC-SHA256 over a canonical JSON
  body) and carries a nonce, a timestamp and a contract version, in the wire format of the development server's
  incident transport. The receiver refuses, each with a named code, an unregistered node (`unknown-identity`), a node
  speaking as another (`impersonation`), a message for someone else (`wrong-recipient`), an incompatible version
  (`incompatible-version`), a wrong signature (`bad-signature`), a timestamp outside `replay_window_seconds`
  (`stale`), a repeated nonce (`replay`) and more than `max_messages_per_minute` (`overloaded`). Replies are signed
  and checked the same way, so a forged answer is refused by the control host.
* The nonce and rate state is a SQLite file (`state_file`), so a replay is caught across restarts and processes.
* The secrets are in the node registry (`registry_file`): `{"nodes": {"<node>": "<secret of 16 characters or more>"}}`.
  It is never part of a repository.
* The channel is signed, not encrypted. Wrap it in TLS with `tls_cert_file` and `tls_key_file`, or tunnel it.
* `verify` runs on the node that owns the incident, which removes the case of a check run against the wrong machine.
* A `deploy` over the channel is not less guarded: the proposal still carries a person's Ed25519 approval, which the
  edge verifies against its own approvers file; the build-test command is the first one its own policy file lists
  for the project; the diff is limited by the policy's `allowed_paths`.

## Node watchdog bridge (`healing`)

`edge healing-ingest --incident-store FILE` reads the watchdog's journal from where it stopped (a position kept in
`state_file`; a rotated journal is read from its start) and, for each transition into one of `trigger_statuses`
(default `UNREACHABLE`, `INVALID`), opens an incident on the node or updates the open one in the same store that
`edge collect` uses. A transition into one of `resolve_statuses` (default `HEALTHY`) closes it. Both the structured
line (`{"event": "transition", "node", "from", "to", "detail"}`) and the text of the watchdog's own log line are
understood.

## Incident proposals from the broker (`proposals`)

`edge proposals-ingest --incident-store FILE` connects to the broker (plain MQTT 3.1.1, TLS optional, credentials from
the environment variables `username_env` and `password_env`), subscribes to `topic_filter` (default
`hydra/health/+/incident-proposal`, where the node watchdog publishes ONE proposal after a node stayed in a failing
state) and listens for `listen_seconds` or `max_messages`. A proposal is untrusted: an oversized payload, a message
that is not a JSON object, another `schema_version`, a missing or ill-typed field, a label outside the contract and
a retained message are refused or ignored with a named reason; the node in the payload must be the node in the topic,
`allowed_nodes` (comma separated) narrows who may propose, at most `max_per_minute` messages are looked at, and the
severity never goes above `severity_cap`. An accepted proposal WAITS FOR A PERSON: it is kept in the pending file (`pending_store`, by default next to the incident
store with the ending `.pending-proposals.json`, at most `max_pending` entries) and nothing reaches the incident store.
`edge proposals-list` shows what waits and what was decided, `edge proposals-decide approve|reject INCIDENT_ID --by NAME`
(or the `proposals` and `proposal-decide` operations of the authenticated channel, which a control side or Studio can call)
takes the decision and records who took it. Approving opens (or updates) the incident of that node in the
store `healing-ingest` uses, with the same component, so a transition to `HEALTHY` read by the bridge closes it;
rejecting only records the decision. With `"auto_open": true` (off by default) an accepted proposal is opened directly.
Either way it is marked `requestedBy = node-healing:proposal` and nothing is deployed or changed by it. A broker that cannot be
reached ends the command with an error and the store is left as it was.

## Notifications (`notify`)

Incident events are `EventEnvelope` documents (`schema_version`, `event_id`, `type` = `ops.incident.opened` or
`ops.incident.resolved`, `source`, `timestamp_utc`, `sequence`, `correlation_id`) with the incident fields
(redacted again) and a sentence in `language` (en, es, de, fr, it, ja, zh, pt). They go to
`<topic_prefix>/<node>` through a plain MQTT 3.1.1 client (QoS 0 or 1, TLS optional). Credentials come from the
environment variables `username_env` and `password_env`. When the broker is down the event is queued in
`outbox_file` and sent by the next collection. Resolutions always go out; the others are filtered by `min_severity`.
`edge collect` and `edge healing-ingest` publish when this is on.

## Canary across nodes (`multinode`)

`control canary-rollout PROPOSAL --target NAME=URL ... --local-node ME` takes one **approved** proposal.

1. The first `canary_nodes` nodes get the change. If one does not promote it, those that did are put back.
2. Every node that has the change is probed each `poll_seconds` for `observe_seconds` (at least once). A node that
   fails `max_failed_probes` probes, or cannot be reached, is unhealthy.
3. The rest follow in waves of `wave_size` (0: all at once), each wave observed the same way.
4. Any failure undoes the change on **every** node that took it, canary included. A rollback that fails is reported.
   A node whose answer was lost in the middle of a deploy is reported as `unknown` and is not rolled back blindly.

Limits: `max_nodes` caps the fleet in one rollout. Each step is written to the audit journal.

## Proposal drafted by a model (`llm_propose`)

`control propose-from-diagnosis SNAPSHOT --incident-id ID --project-name P --live-root DIR --file PATH ...` asks a
**local** model (an OpenAI-compatible chat endpoint on the loopback; another host needs `allow_non_loopback`) for a
unified diff.

* The model sees only the files named with `--file` (secrets redacted, cut to a size limit), the incident and the
  diagnosis, the last two as untrusted evidence.
* It is accepted only within `max_diff_bytes`, `max_files` and `max_changed_lines`; only files it was shown;
  outside the protected paths (CI, build scripts, service units); within the deploy policy's `allowed_paths`; free of
  anything shaped like a secret; and it must apply cleanly (`git apply --check`).
* The result is a **pending** proposal, never an applied change. It is marked `generated_by` (part of what the
  approver signs), its description starts with a marker in the language asked for, and `control approve` refuses
  `--yes` for it: a person is asked at a terminal.

## Metrics (`metrics`)

`control metrics --incident-store FILE [--audit-journal FILE]` prints Prometheus text: open incidents by
severity, resolved incidents kept, mean time to resolution, age of the oldest open incident, observations of the open
ones and the count of each audit event. Labels are only the severity and the event name. `hydra_ops_agent_up` is 0
when the store cannot be read. `edge serve` also serves it at `GET /metrics` with a bearer token from the variable
named by `token_env` (required off the loopback).

## What the machine says about itself (`host_checks`)

Off by default. With `host_checks.enabled`, `edge collect` also reads, without changing anything: the free space of each folder in
`disk_paths`, the temperature of the thermal zone, the throttling flags of `vcgencmd get_throttled` (Raspberry Pi) and, when
`backup_dir` is set, the backups in that folder. The readings go into the snapshot as `hostHealth`, and an incident is opened for a disk
below `disk_warn_free_percent` (critical below `disk_critical_free_percent`), a temperature above `temperature_warn_celsius`
(critical above `temperature_critical_celsius`), a throttling flag that is active now, fewer than `backup_min_count` backups
matching `backup_pattern`, or a newest backup older than `backup_max_age_days` (0 switches the age check off). A reading the machine
cannot give (no thermal zone, no `vcgencmd`) is reported as unavailable and never becomes an incident. When a reading is fine again,
the open incident of that component is resolved. Every threshold is in the configuration file.

## What is not done yet

* None of this has run on a real fleet; it is tested against simulated nodes, broker and model server.
* The watchdog does not yet write a structured `transition` event; the bridge reads its text line too.
* The transport and the development server's keep separate copies of one wire format until the SDK holds the
  contract.
* A model draft is not yet run in a sandbox that reproduces the before/after result.

## Scenario outcomes for the server (`scenario_ingest`)

`control verify` of a manifest incident compares a `before` and an `after` run (`ScenarioOutcome` 1.0). With this section on, both are also sent to
`POST /api/ingest/scenario-outcome` of HYDRA-UMC-SERVER, which keeps them in a signed, hash-chained record. The server has this feed off (it answers
404) until its switch `HYDRA_UMC_INGEST_SCENARIO` is `1`, and it takes the outcome from an operator or administrator account.

* `server_url` and the credential are in the configuration; the credential itself is in a file: `token_file` (a token the server issued) or `username`
  with the password in `password_file` (the agent logs in first). Nothing secret is written in the configuration, a log or a result.
* The credential only goes over HTTPS or to this machine (`allow_plain_http` allows a bench); a redirect is never followed.
* A server that is off, refuses the credential or cannot be reached is reported on the error stream and never changes the verdict or the exit status.
* **A check of a live service is handed over too.** An incident of an HTTP endpoint or of a systemd unit is verified by running the same check again; with this section on, the
  `before` (the incident as it was detected: its symptom and its time, `reproduced`) and the `after` (the check just run: `not-reproduced` if the service is healthy, `reproduced` if
  not) are sent as well, as a record of what was measured. A live service has no source state, so `base_fingerprint` is `live-<http|systemd>:<node>:<component>` (the same in both runs)
  and the outcome says `"fingerprint_kind": "live-service"`; the pair is **never** compared with `compare_runs()` (it could not tell a repair from a restart), and the verdict stays
  the result of the live check alone. The address and the text are redacted like the rest of the incident. A check that could not run measured nothing and sends nothing.
