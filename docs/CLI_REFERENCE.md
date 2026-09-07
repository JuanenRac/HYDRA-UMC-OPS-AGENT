# CLI Reference

`hydra-umc-ops-agent` (or `python -m hydra_umc_ops_agent.cli`) has two
subcommand groups, one per role (`edge`, `control`). There is no
default/bare invocation - a command is always required.

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
    [--out snapshot.json]
```

| Flag | Required | Repeatable | Meaning |
|---|---|---|---|
| `--node-name` | yes | no | This node's own identity string, e.g. `cm5-cell-3`. Stored verbatim as `NodeSnapshot.source_node` and `MaintenanceIncident.source_node`. |
| `--projects-root` | yes | no | Directory whose immediate subdirectories are scanned for a `hydra-umc.project.json`. A subdirectory with no manifest at all is skipped silently; a subdirectory WITH a manifest that fails to parse or is missing a required field becomes a real `ManifestScanIssue` (never dropped). |
| `--systemd-unit` | no | yes | A systemd unit name to check with `systemctl is-active`. Skipped honestly on a non-systemd host (`SystemdUnavailableError`) rather than reporting a guessed status - this happens on every non-Linux development machine, and on Linux hosts with no `systemctl` on `PATH`. The first unavailable check stops the whole systemd loop for that run, since "no systemd here" is a host-wide fact, not a per-unit one. |
| `--http-health-url` | no | yes | A URL to probe with a plain HTTP GET. A non-2xx response and a connection failure are both reported, but distinguished (`status_code` is set for the former, `None` for the latter). |
| `--out` | no | no | Write the snapshot JSON to this path instead of stdout. |

Exit code `0` on success. `scan_project_manifests`/`check_systemd_unit_health`/
`check_http_health` failures for an INDIVIDUAL project/unit/URL never abort
the run - they become incidents inside the same snapshot instead. The
command itself only fails (non-zero, with a traceback) on a real
programmer/environment error (e.g. `--projects-root` does not exist).

## `control show <snapshot_file>`

Runs on the control-plane role (a development host). Renders a snapshot
file produced by `edge collect`, read-only - no field is ever mutated,
no incident is ever "resolved" from here in this delivery.

```
hydra-umc-ops-agent control show snapshot.json
```

Output is a plain-text report: node identity, collection time,
correlation ID, project count, and every incident in the snapshot sorted
by real severity (`critical` first, then `warning`, then `info`). A
snapshot with zero incidents prints a clean "no incidents" line rather
than an empty section.

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
    [--out proposal.json]
```

`--diff-file` must contain a real unified diff (a `--- `/`+++ `/`diff
--git ` header) - rejected otherwise, before it is ever stored. `--out`
defaults to `proposal-<id>.json` in the current directory.

## `control approve <proposal_file> --approved-by "<name>"`

Delivery 3. Transitions a `pending` proposal to `approved`, attributed
to a real, non-empty name. Fails if the proposal is not currently
`pending` (`InvalidTransitionError`). `--out` defaults to overwriting
`proposal_file` in place.

## `control reject <proposal_file> --rejected-by "<name>" --reason "..."`

Delivery 3. Transitions a `pending` proposal to `rejected`, with a real,
non-empty reason. Same rules as `approve` otherwise.

## `control deploy-canary <proposal_file> --live-root <path> --build-test-command "..."`

Delivery 4. Refuses to run unless the proposal's own `status` is already
`approved` (`ChangeNotApprovedError`). See
[CHANGE_LIFECYCLE.md](CHANGE_LIFECYCLE.md) for the full real
stage/apply/verify/promote sequence and its safety guarantees.

```
hydra-umc-ops-agent control deploy-canary proposal.json \
    --live-root /home/pi/HYDRA-UMC/HYDRA-UMC-SERVER \
    --build-test-command "bash build-test.sh" \
    [--build-timeout 600] \
    [--out deploy-result.json]
```

Exit code `0` only if the change was actually promoted; `1` (still with
a real, complete JSON result, never a bare failure) if the build-test
command failed, the diff didn't apply, or the proposal wasn't approved.

## `control verify <snapshot_file> --incident-id <id>`

Delivery 5. Re-runs the exact real check that originally produced the
given incident. See [CHANGE_LIFECYCLE.md](CHANGE_LIFECYCLE.md) for which
incident kinds this can and cannot automatically re-check.

Exit code `0` if the incident is now resolved, `1` if it is confirmed
still unresolved, `1` with `ERROR: ...` on stderr if it genuinely cannot
be re-checked automatically (e.g. a manifest-scan incident, or a
systemd incident on a host with no `systemctl`).

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
