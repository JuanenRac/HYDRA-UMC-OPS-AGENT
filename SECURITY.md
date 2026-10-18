# Security Policy 🔒 (HYDRA-UMC-OPS-AGENT)

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.x.x   | ✅ Yes    |

## Reporting a Vulnerability

**CRITICAL: Do not report vulnerabilities through public GitHub issues.**

This project is designed, from its very first delivery, around a
non-negotiable limit: it must never leak a secret, and it must never
mutate anything without an explicit, signed human approval. If you discover
a vulnerability affecting:

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
- **What `change_proposal.py` and `approval_signing.py` let count as an
  approval** - a way to make `deploy_canary()` accept a proposal whose
  approval was not signed with the private key of an approver registered in
  the registry it is given, or whose diff, project, expiry, commit or
  protected-paths flag changed after signing, or that has expired, or that
  was signed for another commit than the checkout is on; a way to re-approve
  or re-reject a proposal that already left `pending`. The threat model: whoever
  can write the proposal file, the snapshot or the machine that deploys must
  not be able to approve; the machine that deploys holds only public keys,
  and an approver's private key must stay with that person.
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
  in `--build-test-command`); a way to make the build-test command see
  the operator's environment variables (it gets a minimal environment); a
  way to get a diff that rewrites CI, build-test, service or provisioning
  files through without it being signed as allowed.
- **What `audit_journal.py` records** - a way to remove or alter an entry of
  the audit journal without `control audit-verify` noticing, or to deploy
  without a start record. (A journal rewritten from scratch, or with its last
  lines cut off, cannot be detected from inside the file; keep a copy elsewhere
  if that matters.)
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
