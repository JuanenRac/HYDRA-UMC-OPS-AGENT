# Incident & Snapshot Contract

This is the real, current shape of the two JSON objects this project
produces and reads: `MaintenanceIncident` and `NodeSnapshot`. Both are
plain dataclasses (`incident.py`/`edge_agent.py`) with a `to_dict()`
that produces the camelCase field names below, and (for
`MaintenanceIncident`) a matching `from_dict()` for the round trip.

## `MaintenanceIncident`

Field-for-field, this mirrors the ecosystem-wide software-improvements
audit's own "CONTRATO MINIMO" proposal for a maintenance incident -
deliberately, so a later delivery that talks to a real AI provider or a
real ticketing system never has to translate between two incompatible
shapes.

| JSON field | Type | Notes |
|---|---|---|
| `incidentId` | string | A stable identifier for this one incident. |
| `sourceNode` | string | The `--node-name` value of the edge run that found it. |
| `detectedAt` | string | ISO-8601 UTC timestamp. |
| `severity` | string | One of `info` / `warning` / `critical` (see the `SEVERITY_*` constants in `incident.py`). |
| `component` | string | What the incident is about, e.g. a project name, a systemd unit, or an HTTP health-check URL. |
| `symptom` | string | Human-readable description. Always passed through `redact_secrets()` again at `to_dict()` time, even if the caller already redacted it - defense in depth for the single most safety-critical text field in this delivery. |
| `evidenceRefs` | array of string | Free-form references to supporting evidence (e.g. a manifest path). Never raw log content - see `redactionLevel`. |
| `redactionLevel` | string | Currently only `sanitized` (`REDACTION_LEVEL_SANITIZED`) exists - there is no "raw" level in this delivery, on purpose. |
| `requestedBy` | string or null | Who/what asked for this check, when known. |
| `correlationId` | string | Shared by every incident produced by the same `edge collect` run - see `IncidentBatch` below. |

## `IncidentBatch`

Not itself serialized as a top-level object - it is the in-memory
accumulator `edge_agent.collect_snapshot()` uses while it runs, exposing
one shared `correlation_id` (a real UUID4, generated once per run) and
three `add_*` methods, each of which returns `None` (no incident) when
the thing it examined was actually healthy:

- `add_manifest_issue(issue)` - always produces a `warning` incident (a
  present-but-broken manifest is real information worth surfacing, even
  though it's not urgent).
- `add_service_health(unit_name, result)` - a `critical` incident if the
  unit isn't active; `None` if it is.
- `add_http_health(url, result)` - a `warning` incident if the endpoint
  wasn't reachable/healthy; `None` if it was.

## `NodeSnapshot`

The top-level object `edge collect` writes and `control show` reads.

| JSON field | Type | Notes |
|---|---|---|
| `sourceNode` | string | Same value as every incident's own `sourceNode` in this snapshot. |
| `collectedAt` | string | ISO-8601 UTC timestamp for the whole run. |
| `correlationId` | string | Same value as every incident's own `correlationId` in this snapshot. |
| `projects` | array | Every `ProjectVersion` found by `scan_project_manifests()` (name/version/maturity). |
| `manifestIssues` | array | Every `ManifestScanIssue` found (present-but-broken manifests only - a missing manifest is not an issue, see `CLI_REFERENCE.md`). |
| `systemdAvailable` | bool | `false` the moment the first `--systemd-unit` check raises `SystemdUnavailableError`; `true` otherwise (including when no `--systemd-unit` was passed at all). |
| `systemdUnavailableReason` | string or null | Set only when `systemdAvailable` is `false`. |
| `serviceHealth` | array | One `ServiceHealthResult` per `--systemd-unit` actually checked (empty if `systemdAvailable` is `false`, since the whole loop stops at the first failure). |
| `httpHealth` | array | One `HttpHealthResult` per `--http-health-url`. |
| `incidents` | array | Every `MaintenanceIncident` this run produced, in the order they were found (NOT severity-sorted - `control show` sorts at render time, the stored snapshot doesn't reorder its own evidence). |

## What this contract deliberately does not cover yet

There is no field anywhere in either object for a proposed diagnosis, a
proposed patch, an approval decision, or a deployment result - those
belong to later deliveries (see the root [README.md](../README.md)'s
ROADMAP section), and adding a field for them before that code exists
would be a promise this version can't keep.
