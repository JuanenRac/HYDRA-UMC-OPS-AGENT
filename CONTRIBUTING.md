# Contributing to HYDRA-UMC-OPS-AGENT 🦾

We welcome contributions to the maintenance-incident coordinator of the
HYDRA-UMC platform.

## Technology Stack

- **Language**: Python 3.11+.
- **Dependencies**: stdlib only, deliberately, for this delivery - the
  edge role runs on a CM5 with the lowest reasonable privilege and
  footprint; a dependency is added only once a specific later delivery's
  own code genuinely needs it (e.g. an AI-provider SDK, once that
  delivery actually exists), never speculatively.

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
3. **This delivery only ever observes.** Do not add a mutating action (a
   restart, a config write, a patch, an AI-provider call) to `edge_agent.py`,
   `incident.py`, or `cli.py` without first reading this project's own
   README "Architecture & Design Decisions" section on why that is
   deliberately deferred to a specific later delivery, and updating the
   Roadmap there to match.
4. **`MaintenanceIncident`'s field names mirror the ecosystem-wide
   proposal's own contract exactly** (`incidentId`, `sourceNode`, etc.) -
   don't rename a field for Python-style convenience; `to_dict()`/
   `from_dict()` exist specifically so the Python-internal
   `snake_case` dataclass and the real wire contract's `camelCase` never
   have to be the same names.
