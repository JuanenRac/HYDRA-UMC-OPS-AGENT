# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- **README in the universal layout:** the README and its seven translations follow the layout that the four families share (22 sections in a fixed order), with an architecture picture and a repository-structure picture drawn from `docs/architecture.json` and `docs/structure.json`; the CI validator checks both pictures and the file tree.

- **The layout of the README is checked in the CI:** the validator runs `tools/universal_readme_check.py` and lists, as a warning, what differs from the universal layout of the README.
- `docs/DIAGNOSIS.md` shows how to check, with the provider's own model list, that the default model id exists, and which variables replace it.

## [0.1.9] - Pinned to SDK 0.3.6

- The secret redaction is the shared copy kept by the SDK (`tools/canonical/redaction.py`), identical to the one of the local technician, and it passes the same shared cases (`tests/redaction_vectors.json`): headers, cookies, URL credentials, known token shapes, command-line flags, nested JSON and private-key blocks.
- Building no longer changes the version; raising it is the explicit `bump` command (`python tools/hydra_project_tool.py bump`). The build scripts only report the version they built, and CI fails if a build script runs a bump.
- The build and run scripts use the Python of the `.venv` directly instead of an activate script, and create the venv with the `py` launcher when there is one; CI fails if a script activates a venv.
- **Pinned to SDK 0.3.6** (dependency and contract checkout in CI).
- The banner follows the animated style of the ecosystem banners, with the name, the kind and the technologies of the project.
- Added `tools/hydra_project_tool.py`: the same `validate`, `test`, `version`, `status` and `bump` commands in every repository. The checks run with `HYDRA_UMC_CI=1` and fail if the version changes; only `bump` changes it.
- The SDK is now fetched at a release tag instead of the main branch, so a change of the SDK cannot break this repository by itself.

## [0.1.8]

- Build version synchronized with `hydra-umc.project.json` and the repository-native version source.
- The licence is written as GPL-3.0-or-later in every header and in the package metadata.

## [0.1.7] - Redaction covers command-line arguments, cookies and Basic credentials, at one point

- **Redaction:** a secret passed as a separate command-line argument (`--token VALUE`, `-password VALUE`) is now redacted, as are `Cookie` / `Set-Cookie` headers, a bare `Basic <base64>` credential (the word "Basic" in prose is left alone) and a token used as the whole user part of a URL. The existing bare-token formats stay as they were.
- **One redaction point:** every JSON result the commands print or write and every audit journal entry goes through `redact_json()`, which also replaces the value of any key named like a secret, so a new field cannot forget to redact itself.
- **Redaction was quadratic:** the patterns that start with an identifier-like run rescanned the rest of the run from every position, so a megabyte of letters in a log or snapshot took days to redact. They now start only at the beginning of a run and the URL patterns bound each part (a password over 1024 characters inside a URL is the one thing left unredacted); a megabyte now takes under a second.
- 319 tests: each new shape and its false-positive guards, the output and file boundaries, the audit journal and the cost of redacting a huge input.

## [0.1.6] - Approvals are signatures; the deploy checks, restarts, rolls back and records itself

- **Signed approvals:** an approval used to be three fields of a JSON file (`status: approved`, a name and an unkeyed SHA-256 anyone could recompute), so whoever could write the proposal could approve it and get its diff and build script run. `control approve` now signs, with the approver's own Ed25519 private key, a statement of the proposal, the SHA-256 of the diff, who approves, until when (24 hours by default), the commit of the checkout it is for and whether protected paths are allowed. `deploy-canary` verifies it against a registry of approvers' *public* keys (`--approvers`) and refuses an unsigned or hand-edited approval, a signature by another key, a changed diff, an expired approval and a different commit. New `control keygen`; `approve` shows the diff and asks (or takes `--yes`). Needs the `signing` extra (`cryptography`).
- **The build runs with a minimal environment:** the build-test used to inherit the operator's whole environment (API keys, tokens, agent sockets). It now gets only what a toolchain needs, an empty private `HOME`, and the names given with `--build-env-allow`. A diff that touches CI workflows, build-test scripts, service units, provisioning scripts or the project's bump scripts is refused unless the proposal says so and the approver signs it, and a diff over 256 KiB is refused.
- **Health, service and rollback:** `--service-unit` stops the service before the swap and starts it after; `--health-url` (or `systemctl is-active`) must answer healthy or the previous checkout is put back (the failed one is kept as `.failed-<id>`) and the result is `rolled_back`. New `control rollback`, `control prune-backups` and `control recover`. The swap is recorded in the SDK's durable promotion journal when the `sdk` extra is installed. Before the swap the checkout is checked again for edits made during the build and its local data is copied once more.
- **Audit journal:** every proposal, approval, rejection, deploy (and refusal), rollback and prune is appended to a hash-chained journal; `control audit-verify` finds a removed or edited entry. A deploy that cannot write its start record does not happen.
- **Verification on the right host:** `control verify` takes `--node-name` and refuses an incident raised on another node (it used to check this machine's localhost and systemd and could "resolve" an outage of a different one). A URL stored with a redacted password is no longer checked as `[REDACTED]` (it crashed on some Python versions, and sent that text as the password otherwise): give the real one with `--health-url`. An empty `base_commit:` is no evidence, and a comparison the SDK rejects is a verification error, not a traceback.
- **Unit names:** a systemd unit that starts with `-` (`--version`, `--host=...`) was taken by `systemctl` for an option and could close an incident falsely. Names are validated and `--` is passed.
- **Diff secret check:** the detector refused ordinary code (`def login(user, password=None)`, `tokens = 5`, `PWD=/home`), blocking exactly the fixes that matter most. It now looks only at lines the diff adds and only at things shaped like a real secret: known token formats, private keys, passwords in URLs, long literals assigned to a secret-named key.
- **Redaction:** bare tokens (GitHub, Anthropic, OpenAI, AWS, Slack, JWT) and `Authorization: Basic ...` headers are redacted in logs and snapshots.
- **Staging and scanning:** the staging clone is hidden and private (`.ops-agent-canary-<id>`), so `edge collect` no longer lists it as a second copy of the project; the scan skips hidden folders and `.rolledback-`/`.failed-` copies. A checkout without an upstream gets no remote instead of one pointing at the backup. Local data is carried over skipping build output at any depth, and a file the diff adds wins over a local file of the same name instead of failing `git apply`.
- **Incident store:** a store that is not UTF-8 is an error line; load, reconcile and save run under a lock so two simultaneous `edge collect` runs cannot erase each other's counters; an ongoing incident takes the correlation id of the latest pass (as the contract says); two observations of one component in a pass count once; `requestedBy: null` stays null and wrongly typed fields are refused.
- **Health bodies:** a 2xx health answer whose JSON says `"status": "degraded"` or `...Healthy: false` is reported unhealthy.
- **Diagnosis:** the incident is fenced as untrusted evidence in the prompt, each field is cut at 600 characters, provider requests have a timeout and bounded retries, and the model can be set with `OPS_AGENT_ANTHROPIC_MODEL` / `OPS_AGENT_OPENAI_MODEL` (the default id has never been confirmed against the live API).
- **Scripts and CI:** the build compiles every module instead of seven; the CI step has its own name, installs the SDK extra so the SDK tests run, and runs `ruff`; the SDK extra is pinned to a commit; the demo no longer scans the folder above the project (it uses a throwaway sample project, or `OPS_AGENT_DEMO_ROOT`).
- **Documentation:** the README in eight languages, the CLI reference, the change lifecycle, the incident contract, the security policy and the maturity criteria describe what the code does today (the real `control show` output, the signed approval, where each command must run, the real limits).
- 305 tests (about a hundred new ones): signed approvals and each way to defeat them, the diff policy, the environment, service and rollback paths with a faked `systemctl`, the audit chain, verification on the wrong node, unit names, bare-token redaction and the store under concurrency.

## [0.1.5] - Credentialed health URLs, renames, bounded builds, atomic stores

- A health URL with credentials (`http://user:password@host/health`) now works: urllib took `user:password@host` for the host name, so such a URL was reported unreachable forever and opened a false incident on every pass. The credentials are sent as a Basic `Authorization` header (never forwarded on a redirect), the incident store matches the redacted form so the same endpoint stays one incident across runs and closes when it recovers.
- An endpoint that does not speak HTTP, or a manifest that is not valid UTF-8, no longer crashes `edge collect`: the first is reported as unreachable and the second as a manifest issue; a manifest over 1 MB is an issue too. A redirect from a health URL is followed only to `http`/`https`.
- A diff that renames a file can now be promoted: the changed paths are found by comparing `git status` before and after the apply, so the removal of the old path is part of the commit (the numstat listing named only the new path and left the promoted checkout dirty, which blocked the next deploy), and file names with non-ASCII characters no longer break the commit.
- The diff is kept byte for byte: the CLI reads the diff file without newline translation and the patch is written as bytes, so a patch against a CRLF file reaches `git apply` unchanged.
- The build-test command runs in its own process group and the whole tree is killed on a timeout (a grandchild holding the output open used to keep the run waiting), its output is bounded to the last 256 KiB and decoded tolerantly, every git call has a timeout, and an empty command is refused up front.
- When promotion fails the verified candidate is kept, as the error message says it is (cleanup used to delete it); symlinks among the carried-over local data stay symlinks instead of being copied through; a failing `git status --ignored` is an error instead of silently skipping the carry-over.
- The incident store, change proposals and every `--out` file are written atomically (temporary file, flushed, renamed), resolved incidents are capped at the newest 500, and the CLI reports a corrupt store, an unwritable output, a malformed snapshot record, an unbalanced quote in the build command and a non-UTF-8 file as one `ERROR:` line instead of a traceback.
- Added 33 tests for all of the above (202 in total, with a real throwaway git repository and real sockets); documented the behaviour; added the Portuguese README and the `_atomic.py` module to the directory tree of every README.

## [0.1.4] - Removed internal tracking-code labels leaked into source comments

A broad, systemic docs-review pass had already cleaned CHANGELOG/README/
docs of these; a follow-up audit found the exact same private tracking
labels also leaked into this module's own source code comments and
docstrings (canary_deploy.py, change_proposal.py, cli.py,
control_plane.py, edge_agent.py, incident.py, incident_store.py,
inventory.py, log_redaction.py, verification.py). Removed everywhere -
no behavior changed, 169 tests still passing.

## [0.1.3] - A manifest incident's own real "apparent success" control

`verify_incident_resolved()` used to have no automated re-check at all
for a manifest-scan incident - "a structural fact about a file, not a
live service to re-poll" was true, but left a real, honest gap: a
manifest incident could not be verified without a human re-running
`edge collect` by hand.

New: `inventory.py`'s own `check_project_manifest()` (the per-file logic
`scan_project_manifests()`'s loop already applied, now a real, separate,
independently-callable function - no behavior change to the existing
scan) re-checks the one manifest a manifest incident is about, directly.
`incident.py`'s own `add_manifest_issue()` best-effort captures the
checkout's real `git rev-parse HEAD` as a `base_commit:` evidence ref
(never a new `MaintenanceIncident` field - that contract stays exactly
as documented). When both are available, `verification.py` runs
HYDRA-UMC-SDK's shared `ScenarioOutcome`/`compare_runs()`
control (the optional `sdk` extra) against the checkout's current
commit: a manifest that merely *looks* fixed on disk without the
checkout's own commit having actually moved (a real, plausible trap - a
hand-edit that was never committed) is reported unresolved, not a false
"fixed". No `base_commit:`, or the `sdk` extra not installed - the exact
same honest `VerificationError` this always raised for a manifest
incident, unchanged.

## [0.1.2] - real persistent, deduplicated incidents across separate edge-collection runs

`incident.py`'s own `IncidentBatch._new_incident()` generated a fresh
`uuid4()` every single call - a service that stayed down across ten
consecutive `edge collect` runs used to become ten separate, unrelated
`MaintenanceIncident`s instead of one real, ongoing problem a
control-plane viewer could track and eventually see resolved.

New `incident_store.py`: `reconcile_incidents()` deduplicates by
`(sourceNode, component)` - an ongoing problem on the same real
component keeps its original `incidentId` (only its
symptom/severity/evidence/detectedAt update to the latest observation)
and gets `occurrenceCount` bumped, instead of spawning a new incident
every pass. Resolution is scoped, never blanket: a component is only
ever auto-resolved when it was genuinely re-checked this run and came
back clean (`checked_components`), never just because a caller happened
to omit that check this time. A problem that reoccurs after being
resolved honestly starts a real NEW incident (fresh id), never a silent
reopening of the closed one - the closed record itself is preserved as
real history, never dropped.

Wired as a new, optional `edge_agent.collect_snapshot(incident_store_path=...)`
parameter (and the CLI's new `edge collect --incident-store <path>`) -
omitted, nothing changes from before; given, the store file is
loaded/reconciled/saved automatically as part of the same call, and the
snapshot's own `incidents` carry the durable ids.

A real bug in `reconcile_incidents()` itself was caught by its own new
regression tests before this shipped: the first version replaced an
existing open record's ENTIRE `incident` (including the fresh id from
the new observation) instead of keeping the original id and only
updating the observed fields - defeating the whole point. Fixed before
merge, the exact regression test that caught it kept in the suite.

21 new tests (155 passed, 6 subtests).

## [0.1.1] - Real CI/production bug fixed: the staging clone never had its own git identity

`_commit_applied_diff()` (added above) runs a real `git commit`
against the staging clone, but a plain `git clone` never copies
commit-author identity - that step silently depended on a global
`user.name`/`user.email` already being configured on whatever host
runs this. True on a maintainer's own workstation, false by default on
a fresh GitHub Actions runner (this repo's own CI failed on exactly
this, every run, since that commit step landed) - and arguably wrong even on a
real deploy host, where an automated canary commit should never be
silently authored as whichever human happens to be logged in there.
`_create_staging_clone()` now sets a fixed, local-only synthetic
identity (`HYDRA-UMC OPS-AGENT <ops-agent@hydra-umc.local>`) on the
staging clone right after cloning it, so this step's correctness never
depends on the host's ambient git config again.

## [0.1.0] - a successful canary locked itself out, and a broken git status read as "clean"

- `_apply_diff()` only ran `git apply` against the
  staging clone, leaving it with a real, uncommitted working-tree
  change. Promoting that clone as the new live checkout made it dirty
  from the moment it went live, and the very next canary deploy's own
  `TrackedDirtyError` safety gate would then correctly - but
  wrongly, from the operator's point of view - refuse to run at all: a
  genuinely successful canary locking itself out of ever deploying
  again. Fixed: the staging clone now commits exactly the paths the
  diff itself touched (via `git apply --numstat`, never `git add -A`/
  `git add -u`, either of which risks sweeping `_carry_over_local_data()`'s
  own untracked local data into the commit too) as one real, identifiable
  deployment commit before promotion. Two different, consecutive,
  approved canaries against the same live checkout now both succeed.
- **Shared with HYDRA-UMC-UPDATER's own sibling helper:**
  `_tracked_dirty_paths()` treated a `git status` that failed to even
  run (not a git repository, git missing from PATH, a permissions/IO
  error) exactly like "ran fine, found nothing dirty" - the one real
  uncommitted edit this check exists to catch became invisible the
  moment the check itself broke, and `deploy_canary()` would proceed as
  if the live checkout were genuinely clean. Now fails closed: a
  `git status` failure raises `DirtyCheckError` instead of returning an
  empty dirty-paths list.
- 3 new regression tests + 1 new regression test.

## [0.0.9] - Honesty check section in every README

Added a "Honesty check" paragraph right after the status blockquote in
`README.md` and all 6 translated READMEs, naming all five shipped
deliveries' real modules and the real test count (136 tests plus 6
subtests passing across all 11 test files). States plainly that
diagnosis is only ever tested against a fake `AIProvider` - neither
`AnthropicProvider` nor `OpenAIProvider` has been exercised against a
real, live API call in this test suite - and that the edge/control-plane
roles currently talk only through a saved snapshot file, with no network
transport between them yet. Also refreshed the stale v0.0.8 status line
to the current v0.0.9 in every README. Documents the real, current
state of what's implemented vs. planned; no behavior changed.

## [0.0.8] - A real, single diagnose-to-closure chain test + a real bug it found

Every stage already had its own isolated real CLI round-trip test,
but no single test threaded ONE real incident through diagnose ->
propose -> approve -> deploy-canary -> re-verified closure in order.
New
`tests/test_full_incident_lifecycle.py`: a real manifest-scan incident
(a project missing its required `version` field), diagnosed (LLM call
mocked, everything else real), proposed with a real diff, approved,
canary-deployed against a real git repo, then re-collected to prove
the incident is genuinely resolved - plus a rollback-shaped
counterpart proving a fix that doesn't actually work is never promoted
and the original incident survives, reopened.

Writing that real chain surfaced a real bug: `inventory.py`'s
`scan_project_manifests()` had no concept of `canary_deploy.py`'s (and
HYDRA-UMC-UPDATER's own, identical convention) real `<name>.backup-
<uuid>` retired-checkout directories - a re-scan after a real promotion
picked the retired backup back up as if it were a live project, so an
already-fixed incident would reappear forever, every scan, from its own
backup. Fixed: `.backup-` directories are now skipped.

Verified: full pytest suite (136/136, 8 new), `tools/ci_validate.py`
PASS (incl. a 7-language README version-string fix this surfaced).

## [0.0.7] - a real regression test for a self-heal that had none

`canary_deploy.py`'s own best-effort self-heal for a failed second
promotion rename (added alongside HYDRA-UMC-UPDATER's own sibling fix)
had no real regression test proving it actually works - only this
module's own code comment claimed the behavior. New
`test_promotion_self_heals_when_the_second_rename_fails`
(`tests/test_canary_deploy.py`) injects a real `Path.rename` failure on
exactly the second promotion rename and confirms the previous checkout
is restored, matching the equivalent new test HYDRA-UMC-UPDATER's own
`tests/test_install.py` just added for its own identical gap. No
production code changed here - the self-heal itself was already real;
only its own test coverage was missing. 133/133 tests pass.

## [0.0.6] - Docs-only: closes 2 real staleness gaps + a real packaging demo

No functional code changed. `pyproject.toml`'s own `description` and the
CLI's own top-level `--help` text still said "Never proposes/applies a
patch or deploys anything" / "Delivery 1 (read-only observability)" -
stale since Deliveries 3-5 (change proposal, canary deploy,
verification) actually shipped in `v0.0.3`/`v0.0.4`. Both corrected to
describe the real, current 5-delivery scope.

Also: built a real wheel and installed it into a venv outside this
project's own checkout, then ran `edge collect`/`control show` from
there against this workspace's own 58 real repository manifests end to
end - confirms the packaging itself (not just an editable install or
`pytest` inside the checkout) works, closing that part of this
project's own README/ROADMAP honesty note about install/deploy
guarantees.

## [0.0.5] - 7 real regressions found in a second review pass

A second review pass (Codex) reproduced 7 real, distinct gaps
in this project's own maintenance-incident lifecycle, before it has ever
been used against a real installation:

- `canary_deploy.py`'s own docstring claimed it used
  "the same atomic-by-verification pattern HYDRA-UMC-UPDATER's own
  install.py already uses" - it never actually did. No real-local-data
  carryover, no upstream-remote reset, no tracked-dirty rejection -
  reproducing every real gap UPDATER's own earlier
  fixes already closed there. Fixed by giving `canary_deploy.py` its
  own real `_tracked_dirty_paths()`/`_carry_over_local_data()`/
  upstream-remote-reset logic, mirroring UPDATER's own functions.
- **Shared with UPDATER:** a crash in the narrow gap
  between the two promotion renames used to leave no active checkout
  at all. Bounded, honest mitigation: a best-effort self-heal restores
  the backup if the second rename fails - a full transactional journal
  is real, separate future work this does not attempt.
- `deploy_canary()` only ever checked
  `status == "approved"` - nothing tied an approval to the exact
  project or diff a human actually reviewed. A saved proposal file is
  real, mutable JSON: editing `projectName`/`diff` after approval while
  leaving `status: "approved"` untouched used to let a reviewed change
  for one project silently apply to a different one. `approve_change()`
  now stamps a real SHA-256 digest over the approved project+diff;
  `deploy_canary()` verifies it and also cross-checks the approved
  project against `live_root`'s own real manifest.
- `ChangeProposal.to_dict()` used to redact `diff` -
  but `save_proposal()`/`load_proposal()` round-trip THROUGH it, and
  `canary_deploy.py`'s own `_apply_diff()` later runs `git apply` on
  whatever comes back out. A real, approved proposal's own patch
  silently changed bytes the moment it was saved. `diff` is now the
  immutable, byte-exact artifact; a secret-shaped diff is refused
  outright at proposal time instead (new `SecretShapedDiffError`).
- A secret nested one level deeper as a JSON object/array
  (`"password": {"value": "FAKE"}`, `"api_key": ["FAKE"]`), a truncated
  PEM block with no END marker, and `MaintenanceIncident.component`/
  `evidenceRefs` (often a URL with embedded credentials) all used to
  pass through unredacted while `redactionLevel` still claimed
  `"sanitized"`. All three now handled for real.
- An incident with
  `severity: []`/`{}` (unhashable) still crashed the report's own sort;
  a textual `"false"` for `active`/`reachable` still rendered as if it
  were really active/reachable (`bool("false") is True` in Python).
- `systemdAvailable` used to
  default to `True` and never actually flip when zero units were
  configured - indistinguishable from "checked and healthy". Now a
  real tri-state (`bool | None`): `None` means genuinely never
  attempted.
- `VerificationResult.from_dict()`'s
  `bool(data["resolved"])` coerced the literal string `"false"` to
  `True` - a publicly-loaded 'false' silently became a resolved
  incident. Every field is now required to already be its real
  declared type.

`PYTHONPATH=src python -m pytest tests -q`: 132 passed (was 107).
`tools/ci_validate.py` PASS.

## [0.0.4] - Real regressions found in a second review pass

A second review pass reproduced 5 real
issues against this project's own v0.0.2/v0.0.3 code (each with a real
fixture/probe, no hardware/network involved). All 5 are fixed here,
each with a new regression test:

- **`log_redaction.py` missed 3 real secret shapes.** A JSON string-key
  pair (`{"password": "..."}`), a URL's own embedded userinfo
  credential (`https://user:secret@host/`), and a PEM private-key block
  whose BEGIN/END markers land in two different entries of a bounded
  log-line list (`redact_lines()` used to redact each entry in
  isolation, so a cross-line PEM block never matched as one shape).
  Fixed with two new patterns and a `redact_lines()` rewrite that joins
  before redacting, splits after.
- **`NodeSnapshot.to_dict()` only ever redacted `incidents[].symptom`.**
  `manifestIssues[].reason`, `serviceHealth[].detail` and
  `httpHealth[].url`/`.detail` are equally real free text that can
  carry a copy-pasted secret - now redacted too.
- **`control_plane.py`'s report renderer crashed on a structurally
  malformed but JSON-valid snapshot** (`"projects": [null]` and
  similar) with a bare `AttributeError` deep in a loop. A malformed
  entry in any section is now skipped and counted instead, so the rest
  of a genuinely mixed batch still renders.
- **`check_http_health()` crashed with `TypeError` on a non-HTTP(S)
  URL** (a real `data:`/`file:` scheme opens successfully via
  `urlopen()`, then `response.getcode()` returns `None`, and
  `200 <= None < 300` raises). Only `http`/`https` schemes are ever
  opened now; anything else is a real, honest "unsupported scheme"
  result, never a crash.
- **README (all 7 languages) overclaimed what `build-test.sh` checks.**
  It said "runs the same checks as build.sh... the command this
  project's own CI actually runs" - true for the compile step, false
  for the test suite: `build-test.sh` only ever compiles (Python
  syntax), it never runs `pytest`; CI runs `pytest` as its own,
  separate, later step. Wording corrected in all 7 languages.
- 10 new regression tests (107 total), each reproducing its
  exact scenario before the fix and passing after it.

## [0.0.3] - Deliveries 3-5: human-approved change, canary deploy, verification

Adds the rest of the real maintenance-incident lifecycle after diagnosis
- proposal, approval, safe deployment and verification - plus a real
fix making Delivery 2 provider-agnostic instead of Anthropic-only.

- **`diagnosis.py` is now genuinely provider-agnostic.** `diagnose_incident()`
  depends only on a minimal `AIProvider` Protocol (`complete(system_prompt,
  user_prompt, model, max_tokens) -> str`) instead of Anthropic's own
  request/response shape directly. Two real, concrete providers ship out
  of the box - `AnthropicProvider` and `OpenAIProvider`, each an
  optional dependency (`[ai-anthropic]` / `[ai-openai]`, replacing the
  old single `[ai]` extra), each with its own real credential env var
  (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) and lazily-imported SDK. A
  caller with a third vendor or a local model can pass any object
  implementing `AIProvider` directly - this module never needs to know
  it exists. `DiagnosisResult` gained a real `provider` field.
- **`change_proposal.py` (Delivery 3)** - `propose_change()`/`approve_change()`/
  `reject_change()` manage one immutable `ChangeProposal` record per
  incident: a real unified-diff string, a human-readable description
  and rationale, and a `pending` -> `approved`/`rejected` transition
  that can only ever happen once, attributed to a real named person.
  Rejects an empty/malformed diff before it is ever stored or shown to
  anyone as something to approve.
- **`canary_deploy.py` (Delivery 4)** - `deploy_canary()` refuses to run
  against anything but an `approved` proposal (`ChangeNotApprovedError`),
  then applies the proposal's diff to an independent local staging
  clone (`git clone --local --no-hardlinks`, never the live checkout),
  runs the target project's own real build-test command there, and only
  promotes (two-rename swap, previous checkout kept at a real
  `.backup-<id>`, never deleted) if that build passes - the same
  atomic-by-verification pattern HYDRA-UMC-UPDATER's own `install.py`
  already uses. A failed `git apply` or a failed build both leave the
  live checkout completely untouched, reported honestly either way.
- **`verification.py` (Delivery 5)** - `verify_incident_resolved()`
  re-runs the exact real check (`check_http_health`/`check_systemd_unit_health`)
  that originally produced a given incident, using Delivery 1's own
  functions - never a second, independently-drifting health-check
  implementation. A manifest-scan incident has no automated re-check
  (real, honest limit - re-running `edge collect` is the real way to
  confirm one of those is gone).
- **`cli.py`** - new `control propose` / `control approve` / `control
  reject` / `control deploy-canary` / `control verify` subcommands.
  `control diagnose` gained a `--provider {anthropic,openai}` flag.
- Real bug found and fixed during this delivery's own CLI test: plain
  `shlex.split()` on `--build-test-command` treats backslash as an
  escape character in POSIX mode, silently corrupting a Windows path
  like `C:\Users\...\python.exe` into `C:UsersPython.exe`. Fixed with a
  custom `_split_command()` (a `shlex.shlex` instance with `escape`
  disabled) that keeps real quoted arguments working without mangling
  backslashes - a real, live-caught defect, not a hypothetical one.
- 45 new tests (25 for change_proposal/canary_deploy/verification
  against a real throwaway git repository - never a mocked
  `subprocess` - plus CLI round-trips and 3 for the shlex fix) - 97
  tests total, all passing.

## [0.0.2] - Delivery 2: AI-assisted diagnosis (suggestion only)

Adds the second stage of the maintenance-incident lifecycle -
**diagnosis** - still strictly read-only: this stage only ever proposes
an explanation for a human to read, it never decides, applies, or
deploys anything.

- **`diagnosis.py`** - `diagnose_incident()` sends one already-redacted
  `MaintenanceIncident` to an AI provider (Anthropic's Messages API, via
  the official `anthropic` package - a new optional `[ai]` dependency,
  lazily imported so the Delivery-1 core stays dependency-free) and
  returns a `DiagnosisResult` (root-cause explanation + a disclaimer
  that it is a suggestion, not a decision). Every incident field is
  redacted again immediately before it leaves the process, independent
  of whether an upstream caller already did so - defense in depth for
  the one new real secret-exfiltration surface this delivery
  introduces. The API key is read ONLY from `ANTHROPIC_API_KEY` - never
  a CLI flag (shell history) or a repository file. A distinct, typed
  exception exists for every real way this can fail:
  `AnthropicUnavailableError` (the optional package isn't installed),
  `MissingApiKeyError` (no key configured), `AnthropicRequestError` (a
  real network/API failure), `AnthropicResponseError` (a
  real-but-unexpected response shape).
- **`cli.py`** - new `hydra-umc-ops-agent control diagnose <snapshot>
  --incident-id <id>` subcommand, printing or saving the diagnosis JSON.
- 13 new tests (10 for `diagnosis.py` against a fake provider transport,
  3 real CLI round-trips) - 62 tests total, all passing. No real network
  call or the real `anthropic` package is needed to run this suite.

## [0.0.1] - Delivery 1: read-only observability

First real scaffolding version - Delivery 1 of the 6-delivery plan
("Observabilidad read-only") from an explicit recommended-new-project
proposal. This version can only ever
**observe and record** - it never invokes an AI provider, never proposes or
applies a patch, and never deploys or mutates anything on any host.

- **`inventory.py`** - real, read-only collectors: `scan_project_manifests()`
  reads every real `hydra-umc.project.json` under a workspace root (skipping
  a subdirectory with no manifest silently, but reporting a *present*
  malformed/incomplete one as a real, named `ManifestScanIssue`, never
  dropped); `check_systemd_unit_health()` runs a real `systemctl is-active`
  for the edge role, raising a distinct `SystemdUnavailableError` (never a
  guessed status) on a host without `systemctl` at all - this development
  machine included; `check_http_health()` is a real stdlib-only HTTP GET,
  distinguishing a genuine network failure from a real-but-unhealthy
  non-2xx response.
- **`log_redaction.py`** - real, pure secret redaction for the project's own
  non-negotiable security limit ("no envía secretos, tokens, claves SSH,
  archivos .env ni logs sin saneamiento"): `KEY=VALUE`/`KEY: VALUE` secret
  fields (password/token/api_key/private_key/credential/ssh_key and real
  variants like `DB_PASSWORD`), `Authorization: Bearer <token>` headers, and
  full PEM private-key blocks are each replaced with a fixed `[REDACTED]`
  marker - only the secret value, never the surrounding line content.
- **`incident.py`** - the real `MaintenanceIncident` contract from the
  proposal's own "CONTRATO MINIMO" section (incidentId/sourceNode/
  detectedAt/severity/component/symptom/evidenceRefs/redactionLevel/
  requestedBy/correlationId), plus `IncidentBatch`, which derives a real
  incident only from an actually-observed problem (a malformed manifest, an
  inactive systemd unit, an unreachable HTTP health check) - a clean
  observation produces no incident at all. Every incident's own symptom
  text is redacted again at serialization time as a real defense-in-depth
  measure.
- **`edge_agent.py`** - orchestrates the above into one `NodeSnapshot` per
  collection run, with every incident from that run sharing the same real
  `correlationId`.
- **`control_plane.py`** - a real, read-only text renderer for a saved
  snapshot file, sorting incidents by real severity (critical first).
- **`cli.py`** - `hydra-umc-ops-agent edge collect` (writes a real snapshot
  JSON) and `hydra-umc-ops-agent control show <file>` (renders one) - no
  network transport between the two roles exists yet in this delivery; that
  is real, separate future work.
- 49 real tests across all five modules, including genuine end-to-end CLI
  round-trips (`edge collect` writing a file, `control show` reading it
  back) and a real local `http.server` fixture for the HTTP health checks -
  no mocking framework, no fixture blindly assumed to match reality.
