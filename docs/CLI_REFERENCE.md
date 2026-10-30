# CLI Reference

`hydra-umc-ops-agent` (or `python -m hydra_umc_ops_agent.cli`) has two
subcommand groups, one per role (`edge`, `control`). There is no
default/bare invocation - a command is always required.

## Redaction of what is printed and written

Every JSON result a command prints or writes with `--out` (snapshots,
diagnoses, deploy and verification results) and every entry appended to the
audit journal passes through one function, `redact_json()` in
`log_redaction.py`. It redacts `KEY=VALUE` and JSON secrets, `--token VALUE`
style command-line arguments, `Bearer` and `Basic` credentials, cookie
headers, passwords and tokens in URLs, private keys and the known token
formats (GitHub, Anthropic, OpenAI, AWS, Slack, JWT), and replaces the value
of any key named like a secret. The one thing printed unredacted is the diff
`control show` displays to the approver, because that exact text is what gets
signed.

## `edge collect`

Runs on the edge role (a CM5, or any host being observed). Produces one
`NodeSnapshot` and either prints it (JSON) or writes it to a file.

```
hydra-umc-ops-agent edge collect \
    --node-name cm5-cell-3 \
    --projects-root /home/pi/HYDRA-UMC \
    [--systemd-unit hydra-umc-server.service] \
    [--systemd-unit hydra-umc-vision-streamer.service] \
    [--http-health-url http://127.0.0.1:8090/health] \
    [--incident-store incidents.json] \
    [--out snapshot.json]
```

| Flag | Required | Repeatable | Meaning |
|---|---|---|---|
| `--node-name` | yes | no | This node's own identity string, e.g. `cm5-cell-3`. Stored verbatim as `NodeSnapshot.source_node` and `MaintenanceIncident.source_node`. |
| `--projects-root` | yes | no | Directory whose immediate subdirectories are scanned for a `hydra-umc.project.json`. A subdirectory with no manifest at all is skipped silently; a subdirectory WITH a manifest that fails to parse or is missing a required field becomes a real `ManifestScanIssue` (never dropped). |
| `--systemd-unit` | no | yes | A systemd unit name to check with `systemctl is-active -- <unit>`; a name that is not a plausible unit name (letters, digits and `: _ . @ -`, never starting with `-`) is an error before anything runs. Skipped honestly on a non-systemd host (`SystemdUnavailableError`) rather than reporting a guessed status - this happens on every non-Linux development machine, and on Linux hosts with no `systemctl` on `PATH`. The first unavailable check stops the whole systemd loop for that run, since "no systemd here" is a host-wide fact, not a per-unit one. |
| `--http-health-url` | no | yes | A URL to probe with a plain HTTP GET. A non-2xx response and a connection failure are both reported, but distinguished (`status_code` is set for the former, `None` for the latter). A URL may carry `user:password@`: the credentials are sent as a Basic `Authorization` header, never forwarded if the endpoint redirects, and stored redacted. A redirect is followed only to another `http`/`https` URL, and an endpoint that does not answer in HTTP at all is reported as unreachable. |
| `--incident-store` | no | no | Path to a real, durable JSON file (`incident_store.py`) tracking incidents across separate `edge collect` runs against the same node. Given, the same ongoing problem on the same real component (same `sourceNode`+`component`) keeps its original `incidentId` and gets an `occurrenceCount` bump instead of a brand-new, unrelated incident every run; a component genuinely re-checked this run and found clean gets its own open record marked resolved. Omitted (the default), nothing changes from before - every incident still gets a fresh id on every run. |
| `--out` | no | no | Write the snapshot JSON to this path instead of stdout. |

A health endpoint that answers 2xx but whose JSON body says it is unwell
(`"status": "degraded"`/`"unhealthy"`/`"error"`..., or any `...Healthy: false`
field) is reported as unhealthy. Hidden folders and the `.backup-`,
`.rolledback-` and `.failed-` copies a deploy leaves are not projects and are
not scanned.

Exit code `0` on success. `scan_project_manifests`/`check_systemd_unit_health`/
`check_http_health` failures for an INDIVIDUAL project/unit/URL never abort
the run - they become incidents inside the same snapshot instead. The
command itself fails (exit `1`, one `ERROR:` line on stderr) when the
incident store cannot be read or an output file cannot be written.

## `control show <snapshot_file>`

Runs on the control-plane role (a development host). Renders a snapshot
file produced by `edge collect`, read-only - no field is ever mutated,
no incident is ever "resolved" from here in this delivery.

```
hydra-umc-ops-agent control show snapshot.json
```

Output is a plain-text report: node identity and collection time,
project count, service and HTTP health results, and every incident in the snapshot sorted
by real severity (`critical` first, then `warning`, then `info`). A
snapshot with zero incidents prints `Incidents: 0`.

Exit code `1` (with `ERROR: <reason>` on stderr) if the file does not
exist, is not valid JSON, or is valid JSON that isn't a snapshot object
(`SnapshotLoadError`) - never a raw traceback for a bad file path, since
an operator handing this command an arbitrary/corrupted file is an
expected real case, not a program bug.

## `control diagnose <snapshot_file> --incident-id <id>`

Delivery 2. Runs on the control-plane role. Asks an AI provider to
propose a root-cause explanation for ONE incident already present in a
saved snapshot - a suggestion only, see [DIAGNOSIS.md](DIAGNOSIS.md) for
the full real contract and safety boundary.

```
hydra-umc-ops-agent control diagnose snapshot.json \
    --incident-id 7c2c1e4a-... \
    [--provider anthropic|openai] \
    [--model claude-sonnet-5] \
    [--out diagnosis.json]
```

| Flag | Required | Meaning |
|---|---|---|
| `snapshot_file` (positional) | yes | Path to a snapshot JSON file produced by `edge collect`. |
| `--incident-id` | yes | The `incidentId` (shown by `control show`) to diagnose. |
| `--provider` | no | `anthropic` (default) or `openai` - see [DIAGNOSIS.md](DIAGNOSIS.md) for the credential env var and optional extra each one needs. |
| `--model` | no | Model id. Default: a real, sensible default per provider. |
| `--out` | no | Write the diagnosis JSON to this path instead of stdout. |

Exit code `1` (with `ERROR: <reason>` on stderr, never a raw traceback)
if: the snapshot file can't be loaded, the incident id doesn't exist in
it, the chosen provider's own optional package isn't installed, no
credential is configured, or the real request to the provider fails.

## `control propose <snapshot_file> --incident-id <id> ...`

Delivery 3. Creates a new, real PENDING `ChangeProposal` - never applies
anything. See [CHANGE_LIFECYCLE.md](CHANGE_LIFECYCLE.md) for the full
contract.

```
hydra-umc-ops-agent control propose snapshot.json \
    --incident-id 7c2c1e4a-... \
    --project-name HYDRA-UMC-SERVER \
    --description "Increase retry count to 3" \
    --diff-file fix.diff \
    --rationale "The service gives up too early on a transient network blip" \
    [--allow-protected-paths] \
    [--out proposal.json]
```

`--diff-file` must contain a real unified diff (a `--- `/`+++ `/`diff
--git ` header) no larger than 256 KiB - rejected otherwise, before it is ever
stored. A diff is also refused when a line it adds has the shape of a real
secret (a known token format, a private key, a password in a URL, a long
literal assigned to a secret-named key), or when it touches the files that
decide how a change is checked or run (`.github/`, `tools/`, `scripts/`,
`provisioning/`, `build-test.*`, `build.sh`/`build.bat`, `bump_*.py`,
`install_*.sh`, `*.service`, `*.timer`, `Makefile`) unless
`--allow-protected-paths` says so; the approver signs that decision. `--out`
defaults to `proposal-<id>.json` in the current directory.

## `control keygen --name <name> --key-out <file> [--public-out <file>]`

Creates an approver's Ed25519 key pair (needs the `signing` extra). The
private key is written readable only by its owner and an existing file is
never overwritten; the command prints the entry to add to the **approver
registry**, a JSON file of public keys given to the machine that deploys:

```
{"approvers": {"ana": "<base64 of her 32-byte public key>"}}
```

## `control approve <proposal_file> --approved-by <name> --key <private key> (--live-root <path> | --any-commit)`

Delivery 3. Prints the proposal, the SHA-256 of the diff and the diff
itself, asks for confirmation, and signs the approval. Fails if the
proposal is not currently `pending` (`InvalidTransitionError`).

| Flag | Meaning |
|---|---|
| `--approved-by` | The name under which the approver's public key is registered. |
| `--key` | The approver's private key (PEM, from `control keygen`). It stays with the approver; the machine that deploys never needs it. |
| `--live-root` | The checkout the approval is for: it is valid only while that checkout is on the commit it is on now. |
| `--any-commit` | Approve for any state of the checkout instead (weaker). One of `--live-root` / `--any-commit` is required. |
| `--valid-hours` | How long the approval stays valid (default 24). |
| `--yes` | Do not ask; the diff is still printed. Without it, and without a terminal, nothing is signed. |
| `--out` | Write the updated proposal here (default: overwrite `proposal_file`). |
| `--audit-journal` | Audit journal file (default: `ops-agent-audit.jsonl` next to the proposal, or `OPS_AGENT_AUDIT_JOURNAL`). |

## `control reject <proposal_file> --rejected-by "<name>" --reason "..."`

Delivery 3. Transitions a `pending` proposal to `rejected`, with a real,
non-empty reason. Same rules as `approve` otherwise (no key needed).

## `control deploy-canary <proposal_file> --live-root <path> --build-test-command "..." --approvers <registry> --policy <file>`

The policy file (`--policy`, else `OPS_AGENT_POLICY`, else `/etc/hydra-umc/ops-agent-policy.json`) lists, per project, the build-test commands that may run and, optionally, the paths a diff may touch (`allowed_paths`); whatever is not listed is denied, and a missing or malformed file denies everything. See `deploy/ops-agent-policy.json.example`.

Delivery 4. Refuses to run unless the proposal carries a valid signed
approval (`ChangeNotApprovedError` / `ApprovalInvalidError`). See
[CHANGE_LIFECYCLE.md](CHANGE_LIFECYCLE.md) for the full real
stage/apply/verify/promote sequence and its safety guarantees.

```
hydra-umc-ops-agent control deploy-canary proposal.json \
    --live-root /home/pi/HYDRA-UMC/HYDRA-UMC-SERVER \
    --build-test-command "bash build-test.sh" \
    --policy ops-agent-policy.json \
    --approvers approvers.json \
    [--service-unit hydra-umc-server.service] \
    [--health-url http://127.0.0.1:3000/health] [--health-timeout 30] \
    [--build-env-allow NAME]... \
    [--build-timeout 600] [--audit-journal FILE] [--keep-local-commit] \
    [--out deploy-result.json]
```

| Flag | Meaning |
|---|---|
| `--approvers` | Registry of approvers' public keys (default: `OPS_AGENT_APPROVERS`). Without one nothing can be verified and the command refuses. |
| `--build-env-allow` | An environment variable the build-test command may see (repeatable). It gets a minimal environment otherwise: no API keys, tokens or agent sockets. |
| `--service-unit` | The systemd unit that runs from the checkout: stopped before the swap, started after it. |
| `--health-url` | Health URL (default: `OPS_AGENT_HEALTH_URL`) the promoted checkout must answer healthy within `--health-timeout`; otherwise the previous checkout is put back. With only `--service-unit`, `systemctl is-active` is the check. |
| `--audit-journal` | Audit journal file (default: a hidden `.hydra_umc_ops_agent_audit.jsonl` next to the checkout). |
| `--keep-local-commit` | Leave the change in the checkout as a local commit. By default there is no local commit: the change stays in the working tree, is kept as a patch file next to the checkout and the checkout can still fast-forward to upstream. |

Exit code `0` only if the change was actually promoted and, when asked,
healthy. A build-test failure or a rollback after a failed health check
prints a complete JSON result (`promoted: false`, `stageReached`) and exits
`1`. A proposal that is not approved, an approval that does not verify, a
diff that does not apply, a dirty checkout, a protected-path violation or an
unwritable audit journal is `ERROR: ...` on stderr with exit `1` and no JSON.
Before deploying, an interrupted earlier promotion is recovered when the SDK
extra is installed.

## `control canary-clear --live-root <path>`

Drops a canary that was deployed without a local commit: the files it changed go back to what the checkout commit holds, the files it created are removed, and the next canary may run. Until then another `deploy-canary` against the same checkout is refused, because it would replace the pending change without knowing it.

## `control rollback --live-root <path> [--backup <path>]`

Puts the newest (or the named) `<name>.backup-<id>` back in place of the live
checkout; the checkout it replaces is kept as `<name>.rolledback-<id>`.
Nothing is deleted. Written to the audit journal.

## `control prune-backups --live-root <path> [--keep N] [--dry-run]`

Removes all but the newest `N` backups (default 2) of the checkout; with
`--dry-run` only lists them. Only ever runs when asked.

## `control recover --projects-root <path>`

Heals a promotion interrupted between its two renames, from the durable
promotion journal of the optional SDK extra.

## `control audit-verify <journal_file>`

Checks the hash chain of an audit journal; exit `1` and one `PROBLEM:` line per
break if an entry was removed, edited or reordered.

## `control verify <snapshot_file> --incident-id <id> --node-name <this node>`

Delivery 5. Re-runs the exact real check that originally produced the
given incident, **on this machine** - so `--node-name` (this host's own node
name) is required and must equal the incident's `sourceNode`; an incident from
another node is refused rather than "verified" against the wrong localhost.
`--health-url` (or `OPS_AGENT_HEALTH_URL`) supplies the real URL of an HTTP
incident whose password the snapshot holds redacted. See
[CHANGE_LIFECYCLE.md](CHANGE_LIFECYCLE.md) for which incident kinds this can
and cannot automatically re-check.

Exit code `0` if the incident is now resolved, `1` if it is confirmed
still unresolved, `1` with `ERROR: ...` on stderr if it genuinely cannot
be re-checked automatically (another node; a systemd incident on a host with no
`systemctl` or with a unit name that is not valid; a redacted URL with no
`--health-url`; a manifest-scan incident with no `base_commit:` evidence, or
one re-checked without the optional `sdk` extra installed - see
[CHANGE_LIFECYCLE.md](CHANGE_LIFECYCLE.md)).

## `--version`

Prints the installed `hydra_umc_ops_agent.__version__` and exits `0`.

## What does not exist yet

No transport moves a snapshot from the edge role to the control-plane
role automatically - `edge collect --out` writes a local file, and
getting that file onto the control-plane host (`scp`, a shared volume,
anything) is a manual step today. Delivery 6 (voice/notification via
HYDRA-UMC-VOICE-UI) is investigated and documented as genuinely blocked,
not merely postponed - see the repository root [README.md](../README.md)'s
own ROADMAP section for why.
