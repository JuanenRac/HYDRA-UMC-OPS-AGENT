# Changelog: HYDRA-UMC-OPS-AGENT 🛠️

All notable changes to this project will be documented in this file. The
version number follows this ecosystem's "odometer" scheme: PATCH +1 on
every real build, rolling into MINOR past 9 (`0.0.9` -> `0.1.0`); MAJOR is
bumped manually only. See `bump_version.py`.

## Unreleased

(nothing yet)

## [0.0.8] - F08: a real, single diagnose-to-closure chain test + a real bug it found

Every F08 stage already had its own isolated real CLI round-trip test,
but no single test threaded ONE real incident through diagnose ->
propose -> approve -> deploy-canary -> re-verified closure in order -
the private plan's own explicit F08 gap. New
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

## [0.0.7] - V07-004: a real regression test for a self-heal that had none

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

## [0.0.5] - V07-002/003/004/005/010/011/020/021: 7 real regressions found in a second review pass

A second review pass (Codex) reproduced 7 real, distinct gaps
in this project's own maintenance-incident lifecycle, before it has ever
been used against a real installation:

- **V07-002 (P1):** `canary_deploy.py`'s own docstring claimed it used
  "the same atomic-by-verification pattern HYDRA-UMC-UPDATER's own
  install.py already uses" - it never actually did. No real-local-data
  carryover, no upstream-remote reset, no tracked-dirty rejection -
  reproducing every real gap UPDATER's own REV-001/REV-002/V07-001
  fixes already closed there. Fixed by giving `canary_deploy.py` its
  own real `_tracked_dirty_paths()`/`_carry_over_local_data()`/
  upstream-remote-reset logic, mirroring UPDATER's own functions.
- **V07-004 (P1, shared with UPDATER):** a crash in the narrow gap
  between the two promotion renames used to leave no active checkout
  at all. Bounded, honest mitigation: a best-effort self-heal restores
  the backup if the second rename fails - a full transactional journal
  is real, separate future work this does not attempt.
- **V07-003 (P1):** `deploy_canary()` only ever checked
  `status == "approved"` - nothing tied an approval to the exact
  project or diff a human actually reviewed. A saved proposal file is
  real, mutable JSON: editing `projectName`/`diff` after approval while
  leaving `status: "approved"` untouched used to let a reviewed change
  for one project silently apply to a different one. `approve_change()`
  now stamps a real SHA-256 digest over the approved project+diff;
  `deploy_canary()` verifies it and also cross-checks the approved
  project against `live_root`'s own real manifest.
- **V07-005 (P1):** `ChangeProposal.to_dict()` used to redact `diff` -
  but `save_proposal()`/`load_proposal()` round-trip THROUGH it, and
  `canary_deploy.py`'s own `_apply_diff()` later runs `git apply` on
  whatever comes back out. A real, approved proposal's own patch
  silently changed bytes the moment it was saved. `diff` is now the
  immutable, byte-exact artifact; a secret-shaped diff is refused
  outright at proposal time instead (new `SecretShapedDiffError`).
- **V07-010 (P1, residual outside REV-013's own three original
  examples):** a secret nested one level deeper as a JSON object/array
  (`"password": {"value": "FAKE"}`, `"api_key": ["FAKE"]`), a truncated
  PEM block with no END marker, and `MaintenanceIncident.component`/
  `evidenceRefs` (often a URL with embedded credentials) all used to
  pass through unredacted while `redactionLevel` still claimed
  `"sanitized"`. All three now handled for real.
- **V07-011 (P2, partial closure of REV-014):** an incident with
  `severity: []`/`{}` (unhashable) still crashed the report's own sort;
  a textual `"false"` for `active`/`reachable` still rendered as if it
  were really active/reachable (`bool("false") is True` in Python).
- **V07-020 (P2, residual of REV-015):** `systemdAvailable` used to
  default to `True` and never actually flip when zero units were
  configured - indistinguishable from "checked and healthy". Now a
  real tri-state (`bool | None`): `None` means genuinely never
  attempted.
- **V07-021 (P2):** `VerificationResult.from_dict()`'s
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
