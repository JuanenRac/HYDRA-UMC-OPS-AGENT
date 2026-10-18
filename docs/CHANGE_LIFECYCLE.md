# Change Lifecycle (Deliveries 3-5)

The rest of this project's own real lifecycle, after evidence (Delivery
1) and diagnosis (Delivery 2):

```
evidence -> diagnosis -> human-approved change (this doc, Delivery 3)
-> canary deploy (this doc, Delivery 4) -> verification (this doc, Delivery 5)
```

## Who may do what

The three actions are separated by what each one needs to hold:

| Action | Needs | Never needs |
|---|---|---|
| Read (`edge collect`, `control show`) | read access to the projects root / a snapshot file | any key |
| Propose (`control propose`) | a snapshot and a diff | an approver's private key |
| Approve (`control approve`) | the approver's **private key**, kept only by that person | access to the live checkout beyond reading its commit |
| Execute (`control deploy-canary`) | write access to the checkout and the registry of approvers' **public keys** | any private key |

An approval cannot be produced by whoever can merely write the proposal
file: it is an Ed25519 signature, and the machine that deploys holds only
public keys.

## Delivery 3 - `change_proposal.py`: human-approved change

A `ChangeProposal` is a real, immutable record: a unified-diff string, a
human-readable description and rationale, and a status that starts
`pending` and transitions EXACTLY ONCE, to either `approved` or
`rejected`, always attributed to a real named person. Re-deciding an
already-decided proposal raises `InvalidTransitionError` - a second
decision never silently overwrites the first.

`propose_change()` refuses, before the proposal is ever stored or shown
to anyone as something to approve:

- an empty or malformed diff (anything without a real `--- `/`+++ `/
  `diff --git ` header) - `InvalidDiffError`;
- a diff larger than 256 KiB - `DiffTooLargeError`;
- a diff whose **added** lines hold something with the shape of a real
  secret: a known token format (GitHub, Anthropic, OpenAI, AWS, Slack,
  JWT), a private key, a password inside a URL, or a long literal string
  assigned to a secret-named key - `SecretShapedDiffError`. Ordinary code
  that merely mentions a password (a parameter, a read from the
  environment, a placeholder) is accepted;
- a diff that touches the files that decide how a change is checked or
  run - `.github/`, `tools/`, `scripts/`, `provisioning/`, `build-test.*`,
  `build.sh`/`build.bat`, `bump_*.py`, `install_*.sh`, `*.service`,
  `*.timer`, `Makefile` - unless the proposal says so explicitly
  (`--allow-protected-paths`): a change must not rewrite the check that
  judges it. `ProtectedPathError`.

### Signing an approval

```
hydra-umc-ops-agent control keygen --name ana --key-out ana.pem --public-out ana.pub
```

writes a private key (readable only by its owner; never overwritten) and
prints the entry for the **approver registry**, a JSON file of public
keys that is given to the machine that deploys:

```
{"approvers": {"ana": "<base64 of her 32-byte public key>"}}
```

`control approve` prints the proposal, the SHA-256 of the diff, the
commit it is for and the diff itself, asks for confirmation (or takes
`--yes` when there is no terminal), and signs a statement of exactly what
is approved: the proposal and incident ids, the project, the SHA-256 of
the diff, who approves, when, **until when** (24 hours unless
`--valid-hours` says otherwise), the **commit of the checkout** the
approval is for (`--live-root PATH`, or `--any-commit` to approve for any
state - weaker), and whether protected paths are allowed. Changing any of
it afterwards - the diff, the project, the expiry, a flag - invalidates
the signature.

## Delivery 4 - `canary_deploy.py`: safe, verified deployment

`deploy_canary()` is the one place in this whole project that can
change a real file outside its own process. Before it does anything:

- the proposal must be `approved` (`ChangeNotApprovedError`);
- it must carry a **valid signature** by an approver listed in the
  registry (`--approvers` or the `OPS_AGENT_APPROVERS` variable), over the
  proposal as it is today, not expired, and given for the commit the live
  checkout is on now (`ApprovalInvalidError`). A file edited by hand to say
  "approved" is refused, and so is one approved under the old unsigned
  scheme;
- the checkout's manifest must name the approved project;
- a diff that touches protected paths must have been signed as allowed;
- the live checkout must have no uncommitted edit to a tracked file;
- the audit journal must be writable (see below).

The real sequence, mirroring HYDRA-UMC-UPDATER's own `install.py`
atomic-by-verification pattern:

1. **Stage** - `git clone --local --no-hardlinks` the live checkout into
   a hidden, owner-only directory next to it (`.ops-agent-canary-<id>`;
   `edge collect` never mistakes it for a project). The clone's `origin` is
   the live checkout's real upstream - or, if it has none, no remote at all.
2. **Apply** - `git apply` the proposal's own diff to that staging
   clone. A failure here (`DiffApplyError`) leaves the live checkout
   untouched. The diff is stored and applied byte for byte, and the paths
   it changed are found by comparing `git status` before and after, so a
   rename commits the removal of the old path as well as the new file.
3. **Carry over local data** - untracked and ignored files of the live
   checkout (configuration, certificates, a database) are copied in, except
   build output (`node_modules`, `.venv`, `target`...) at any depth and
   anything the diff itself adds or changes.
4. **Verify** - run the project's own real build-test command
   (`--build-test-command`, e.g. `"bash build-test.sh"`) inside the
   staging clone with a **minimal environment**: the variables a toolchain
   cannot start without, an empty private `HOME`, and only the names listed
   with `--build-env-allow`. The operator's API keys, tokens and agent
   sockets are not visible to it. A failure here is a real, EXPECTED
   possible outcome - reported back as `CanaryDeployResult(promoted=False,
   ...)`, never raised as an exception, and the live checkout is still
   untouched.
5. **Stop and re-check** (with `--service-unit`) - the service is stopped;
   then the live checkout is checked again for tracked edits made during
   the build (a change stops the deploy) and its local data is copied once
   more. Keep databases outside the checkout where you can: copying a file
   a program is writing is only safe while it is stopped.
6. **Promote** - two back-to-back renames swap the staging clone in for the
   live checkout. The previous checkout is kept at `<name>.backup-<id>`,
   never deleted. If the optional SDK is installed, the swap is recorded in a
   durable promotion journal first, so `control recover` can heal a crash
   between the two renames. If the second rename fails the previous checkout
   is put back and the verified candidate is kept for inspection.
7. **Health** (with `--service-unit` and/or `--health-url`) - the service is
   started and the health URL (or `systemctl is-active`) must answer
   healthy within `--health-timeout`. If it does not, the previous checkout
   is put back (the failed one is kept as `<name>.failed-<id>`), the
   service is started again, and the result is `promoted=false`,
   `stageReached="rolled_back"`.

`CanaryDeployResult.stage_reached` always tells you exactly how far a
real run got (`staged` / `diff_applied` / `build_verified` /
`diff_committed` / `promoted` / `rolled_back`), even on a real failure.

### Where it runs

`deploy-canary` and `rollback` act on a checkout of **this** machine, and
`verify` checks **this** machine's localhost and systemd. Run them on the
node that owns the incident (`verify` refuses an incident whose
`sourceNode` is not the `--node-name` it is given). No transport carries
these commands to another node yet.

### Rollback, backups, recovery

- `control rollback --live-root PATH [--backup PATH]` puts the newest (or the
  named) `<name>.backup-<id>` back; the checkout it replaces is kept as
  `<name>.rolledback-<id>`.
- `control prune-backups --live-root PATH --keep N [--dry-run]` removes older
  backups - only when asked.
- `control recover --projects-root PATH` heals an interrupted promotion
  (needs the optional `sdk` extra; `deploy-canary` also does it first).

### Audit journal

Every proposal, approval, rejection, deploy (and refusal), rollback and prune
is appended to an audit journal: one JSON line per event with who and where,
chained by SHA-256 so removing or editing a line breaks every hash after it
(`control audit-verify FILE` says where). Deploys write to a hidden
`.hydra_umc_ops_agent_audit.jsonl` next to the checkout unless
`--audit-journal` / `OPS_AGENT_AUDIT_JOURNAL` names another file; a deploy that
cannot record its start does not happen. The chain shows tampering inside the
file; it cannot show that the last lines were cut off, so keep a copy
elsewhere if that matters.

### Real, honest limits

- This has been verified end-to-end against a real, throwaway local git
  repository (a real `git init`, a real file, a real Python build-test
  script) and with a faked `systemctl` - never against a real service under
  systemd. It has NOT been exercised against a real HYDRA-UMC ecosystem
  project's own checkout; try it on a low-risk project first.
- The commit that promotion leaves in the checkout exists only on this
  machine. HYDRA-UMC-UPDATER updates with a fast-forward-only merge, so once
  upstream moves on it refuses to update that checkout and names the local
  commit. How a hot fix and the normal update path should coexist is open.
- A signature proves who approved what; it does not make the diff correct.

## Delivery 5 - `verification.py`: confirming the fix actually worked

`verify_incident_resolved()` re-runs the EXACT SAME real check that
originally produced a given incident - `check_http_health()` for an
HTTP-health incident, `check_systemd_unit_health()` for a systemd
incident, both straight from Delivery 1's own `inventory.py` - never a
second, independently-drifting implementation of either check.

A health endpoint answering 2xx whose JSON body says it is unwell
(`"status": "degraded"`, `"persistenceHealthy": false`) is not healthy. A
snapshot stores a URL's password redacted, so an HTTP incident with a
credentialed URL is verified with the real URL given as `--health-url` (or
`OPS_AGENT_HEALTH_URL`).

A manifest-scan incident is re-checked with `check_project_manifest()`
(same real per-file logic Delivery 1's own `scan_project_manifests()`
loop applies) AND, whenever the incident carries a real `base_commit:`
evidence entry (best-effort, captured at detection time from the
checkout's own `git rev-parse HEAD` - see `incident.py`'s own
`add_manifest_issue()`), against HYDRA-UMC-SDK's shared
`ScenarioOutcome`/`compare_runs()` "apparent success" control: the
checkout's own commit must have genuinely moved between detection and
re-check, not merely have the file *look* fixed on disk right now (a
real, plausible trap - a hand-edit that was never actually committed).
This needs the optional `sdk` extra installed
(`pip install -e ".[sdk]"`); without it, or without a `base_commit:`
(an incident raised before this, or one whose checkout was never a real
git repo), verification falls back to the original, honest answer: no
automated re-check, re-run `edge collect` against the same
`--projects-root` and check the new snapshot by hand.

## What a real end-to-end operator flow looks like

```
# on the node
hydra-umc-ops-agent edge collect --node-name cm5-cell-3 --projects-root /home/pi/HYDRA-UMC --http-health-url http://127.0.0.1:8090/health --out snapshot.json
hydra-umc-ops-agent control show snapshot.json
ANTHROPIC_API_KEY=... hydra-umc-ops-agent control diagnose snapshot.json --incident-id <id> --out diagnosis.json
# a person writes fix.diff by hand, informed by diagnosis.json
hydra-umc-ops-agent control propose snapshot.json --incident-id <id> --project-name HYDRA-UMC-SERVER --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
# the approver, on their own machine, reads the diff and signs with their key
hydra-umc-ops-agent control approve proposal.json --approved-by ana --key ana.pem --live-root /home/pi/HYDRA-UMC/HYDRA-UMC-SERVER
# on the node
hydra-umc-ops-agent control deploy-canary proposal.json --live-root /home/pi/HYDRA-UMC/HYDRA-UMC-SERVER --build-test-command "bash build-test.sh" --approvers approvers.json --service-unit hydra-umc-server.service --health-url http://127.0.0.1:3000/health --out deploy-result.json
hydra-umc-ops-agent control verify snapshot.json --incident-id <id> --node-name cm5-cell-3
```

Every step above is a separate, explicit, human-triggered command -
nothing in this codebase chains them automatically.
