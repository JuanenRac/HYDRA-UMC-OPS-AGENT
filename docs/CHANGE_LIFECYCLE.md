# Change Lifecycle (Deliveries 3-5)

The rest of this project's own real lifecycle, after evidence (Delivery
1) and diagnosis (Delivery 2):

```
evidence -> diagnosis -> human-approved change (this doc, Delivery 3)
-> canary deploy (this doc, Delivery 4) -> verification (this doc, Delivery 5)
```

## Delivery 3 - `change_proposal.py`: human-approved change

A `ChangeProposal` is a real, immutable record: a unified-diff string, a
human-readable description and rationale, and a status that starts
`pending` and transitions EXACTLY ONCE, to either `approved` or
`rejected`, always attributed to a real named person
(`approve_change(..., approved_by=...)` / `reject_change(...,
rejected_by=..., reason=...)`). Re-deciding an already-decided proposal
raises `InvalidTransitionError` - a second decision never silently
overwrites the first.

`propose_change()` rejects an empty or malformed diff (anything that
doesn't have a real `--- `/`+++ `/`diff --git ` header) before the
proposal is ever stored or shown to anyone as something to approve -
see `InvalidDiffError`.

This module never applies anything. It only ever creates, approves, or
rejects a record on disk (`save_proposal()`/`load_proposal()`).

## Delivery 4 - `canary_deploy.py`: safe, verified deployment

`deploy_canary()` is the one place in this whole project that can
change a real file outside its own process, and it is built around one
non-negotiable gate:

> **It refuses to run at all unless the given proposal's `status` is
> already `approved`.** `ChangeNotApprovedError`, checked first, every
> time, before anything else.

The real sequence, mirroring HYDRA-UMC-UPDATER's own `install.py`
atomic-by-verification pattern exactly:

1. **Stage** - `git clone --local --no-hardlinks` the live checkout into
   an independent directory. The live checkout is not touched yet.
2. **Apply** - `git apply` the proposal's own diff to that staging
   clone. A failure here (`DiffApplyError`) leaves the live checkout
   untouched.
3. **Verify** - run the project's own real build-test command
   (`--build-test-command`, e.g. `"bash build-test.sh"`) inside the
   staging clone. A failure here is a real, EXPECTED possible outcome
   (that is the whole point of staging first) - reported back as
   `CanaryDeployResult(promoted=False, ...)`, never raised as an
   exception, and the live checkout is still untouched.
4. **Promote** - only if step 3 passed: two back-to-back renames swap
   the staging clone in for the live checkout. The previous checkout is
   kept at a real `<name>.backup-<id>` path, never deleted.

`CanaryDeployResult.stage_reached` always tells you exactly how far a
real run got (`staged` / `diff_applied` / `build_verified` /
`promoted`), even on a real failure.

### Real, honest limits

- This has been verified end-to-end against a real, throwaway local git
  repository (`tests/test_canary_deploy.py` - a real `git init`, a real
  file, a real Python build-test script) - never a mocked `subprocess`
  or a mocked `git`. It has NOT been exercised against a real HYDRA-UMC
  ecosystem project's own real checkout in this development session -
  an operator should try it against a real, low-risk project first.
- There is no rollback command if a PROMOTED canary later turns out to
  be wrong at runtime (as opposed to at build-test time) - the `.backup-<id>`
  directory is real and kept specifically so an operator can restore it
  by hand, but this delivery does not yet automate that restoration.

## Delivery 5 - `verification.py`: confirming the fix actually worked

`verify_incident_resolved()` re-runs the EXACT SAME real check that
originally produced a given incident - `check_http_health()` for an
HTTP-health incident, `check_systemd_unit_health()` for a systemd
incident, both straight from Delivery 1's own `inventory.py` - never a
second, independently-drifting implementation of either check.

A manifest-scan incident has no automated re-check here on purpose: it
is a structural fact about a file, not a live service to re-poll. The
real way to confirm one is gone is to re-run `edge collect` against the
same `--projects-root` and check the new snapshot.

## What a real end-to-end operator flow looks like

```
hydra-umc-ops-agent edge collect --node-name cm5-cell-3 --projects-root /home/pi/HYDRA-UMC --http-health-url http://127.0.0.1:8090/health --out snapshot.json
hydra-umc-ops-agent control show snapshot.json
ANTHROPIC_API_KEY=... hydra-umc-ops-agent control diagnose snapshot.json --incident-id <id> --out diagnosis.json
# a person writes fix.diff by hand, informed by diagnosis.json
hydra-umc-ops-agent control propose snapshot.json --incident-id <id> --project-name HYDRA-UMC-SERVER --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
# a person reviews proposal.json's own diff/description/rationale
hydra-umc-ops-agent control approve proposal.json --approved-by "Juan Enrique"
hydra-umc-ops-agent control deploy-canary proposal.json --live-root /home/pi/HYDRA-UMC/HYDRA-UMC-SERVER --build-test-command "bash build-test.sh" --out deploy-result.json
hydra-umc-ops-agent control verify snapshot.json --incident-id <id>
```

Every step above is a separate, explicit, human-triggered command -
nothing in this codebase chains them automatically.
