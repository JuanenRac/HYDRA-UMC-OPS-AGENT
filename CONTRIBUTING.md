# Contributing to HYDRA-UMC-OPS-AGENT 🦾

We welcome contributions to the maintenance-incident coordinator of the
HYDRA-UMC platform.

## Technology Stack

- **Language**: Python 3.11+.
- **Dependencies**: stdlib only for the core - the edge role runs on a CM5
  with the lowest reasonable privilege and footprint. Each dependency is an
  optional extra that only the code which needs it imports: `cryptography`
  (`signing`, to sign and verify approvals), an AI-provider SDK
  (`ai-anthropic` / `ai-openai`), and HYDRA-UMC-SDK (`sdk`, for the
  manifest re-check and the promotion journal). Never add one speculatively.

## Guidelines

1. **`log_redaction.py` is the one module every real evidence path must
   go through before it leaves the edge role.** Do not add a second,
   parallel place that formats evidence for a snapshot, a log line, or a
   future network/AI-provider call without also redacting it here first.
   A new secret shape belongs in `_SECRET_KEY_NAMES`/a new dedicated
   pattern in this same module, not a one-off regex somewhere else.
2. **A collector reports a real, honest failure - it never guesses.**
   `check_systemd_unit_health()` raising `SystemdUnavailableError` and
   `scan_project_manifests()` returning a `ManifestScanIssue` are the
   established pattern: a distinct, typed reason a caller can act on,
   never a silently-returned default value standing in for "couldn't
   check". Follow the same shape for a new collector.
3. **The edge role only ever observes.** Do not add a mutating action (a
   restart, a config write, a patch, an AI-provider call) to `edge_agent.py`,
   `incident.py`, or the `edge` commands. Changes happen only through the
   signed-approval path (`change_proposal.py` -> `canary_deploy.py`), which is
   the one place that may touch a checkout; keep every mutation behind it and
   leave a record in the audit journal.
4. **`MaintenanceIncident`'s field names mirror an explicit
   contract exactly** (`incidentId`, `sourceNode`, etc.) -
   don't rename a field for Python-style convenience; `to_dict()`/
   `from_dict()` exist specifically so the Python-internal
   `snake_case` dataclass and the real wire contract's `camelCase` never
   have to be the same names.
