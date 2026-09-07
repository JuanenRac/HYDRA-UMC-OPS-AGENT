# Security Policy 🔒 (HYDRA-UMC-OPS-AGENT)

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.x.x   | ✅ Yes    |

## Reporting a Vulnerability

**CRITICAL: Do not report vulnerabilities through public GitHub issues.**

This project is designed, from its very first delivery, around a
non-negotiable limit: it must never leak a secret, and it must never
mutate anything without an explicit human approval step that does not
exist yet in this version. If you discover a vulnerability affecting:

- **What `log_redaction.py` fails to redact** - a real secret shape
  (a password, token, API key, private key, credential, or SSH key) that
  reaches a saved snapshot or a rendered report unredacted. This is the
  single most safety-critical piece of code in this delivery: everything
  else this project will ever do (an AI-provider call, a control-plane
  view, a future patch proposal) depends on evidence having already been
  sanitized before it leaves the edge role.
- **What `scan_project_manifests()` trusts** - a way to make it read a
  file outside the intended workspace root, or to make a malformed
  manifest crash collection instead of being reported as a real,
  contained `ManifestScanIssue`.
- **What `check_systemd_unit_health()`/`check_http_health()` execute or
  contact** - a way to make either function run something other than the
  exact `systemctl is-active <unit>` invocation or the exact HTTP GET it
  was given (e.g. a command- or URL-injection through an operator-supplied
  unit name or health-check URL).
- **What `diagnosis.py` sends to, or reads from, the AI provider** - a
  real secret shape that reaches `_build_prompt()`'s own second,
  independent redaction pass unredacted; a way to make an API key
  (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`) leak into a log, an exception
  message, or a saved file; or a way to make this module treat the
  provider's own response text as anything other than inert display
  text (it is never executed, evaluated, or used to construct a
  command).
- **What `change_proposal.py` lets become an APPROVED proposal without a
  real human decision** - a way to reach `STATUS_APPROVED` without going
  through `approve_change()` with a real, non-empty `approved_by`, or a
  way to re-approve/re-reject a proposal that already left `pending`
  (the one-decision-only guarantee `InvalidTransitionError` exists to
  enforce).
- **What `canary_deploy.py` does before an approved diff is verified** -
  the single most safety-critical check in this whole delivery: any way
  to make `deploy_canary()` promote a staging clone (replace the real,
  live checkout) WITHOUT the target project's own real build-test
  command having actually exited `0` first, or any way to make it run
  against a proposal whose `status` is not `approved`
  (`ChangeNotApprovedError` is the one gate this exists to prove).
  Also: a way to make `_apply_diff()`'s own `git apply` or the build-test
  command escape the staging clone's own directory (e.g. via a
  maliciously crafted diff path, `../` traversal, or shell metacharacters
  in `--build-test-command`).
- **What `verification.py` re-checks** - a way to make
  `verify_incident_resolved()` report `resolved: true` for an incident
  that is still genuinely broken (it must only ever re-run the exact
  real check `inventory.py` already has - the same real HTTP/systemd
  functions Delivery 1 uses, never a second, looser implementation of
  either).

**Not yet applicable** - Delivery 6 (voice/notification via
HYDRA-UMC-VOICE-UI) does not exist, and after real investigation is now
known to be genuinely blocked rather than merely postponed - see this
project's own manifest `notes` field and README ROADMAP section for why.
There is no code path anywhere in this repository that talks to
VOICE-UI, so there is nothing there to have a vulnerability in.

Please report responsibly:

1. **Email**: Send a detailed report to `electrohobby3d@gmail.com`.
2. **Impact**: Describe the attack surface affected and a realistic
   scenario (this delivery has no network-facing service of its own - the
   edge role only runs when explicitly invoked, so most realistic
   scenarios involve what evidence an operator-configured health check or
   systemd unit name could exfiltrate or execute, not a remote attacker
   directly reaching this tool).
3. **Response**: Initial acknowledgment within 48 hours.

We follow a coordinated disclosure policy.
