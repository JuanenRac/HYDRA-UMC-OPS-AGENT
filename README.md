<!-- =============================================================================
HYDRA-UMC-OPS-AGENT - Maintenance-incident coordinator
Copyright (C) JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center">🇺🇸 <b>English</b> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a> | <a href="README_por.md">🇵🇹 Português</a></p>

### 🔎 Read-Only Maintenance-Incident Observability for the Whole Ecosystem

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Language">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="Core">
  <img src="https://img.shields.io/badge/Tests-322%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.1.9-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-0F6CBD.svg" alt="Maturity">
</p>

---

**Honesty check - what actually runs today:** all five shipped deliveries - evidence (`inventory.py`, `edge_agent.py`, `incident.py`), diagnosis (`diagnosis.py`), human-approved change (`change_proposal.py`), canary deploy (`canary_deploy.py`), and verification (`verification.py`), plus the redaction boundary (`log_redaction.py`) and the CLI (`cli.py`) - are real and tested end to end (322 tests plus 42 subtests passing across all 17 test files). The canary-deploy stage is genuinely exercised against a real, throwaway local git repository, not a mock. Diagnosis is only ever tested against a fake `AIProvider` - ``anthropic`Provider`/`OpenAIProvider` are real wrapper implementations of the same protocol, but neither has been exercised against a real, live `anthropic` or OpenAI API call in this test suite (no key available in this environment). The edge and control-plane roles currently talk only through a saved snapshot file - there is no network transport between them yet. Delivery 6 (voice/notification) is genuinely blocked, not merely postponed: HYDRA-UMC-VOICE-UI has no real outbound-notification surface today to integrate with. See `CHANGELOG.md` for exactly what has shipped so far.

---

> **Safety and security status:** this ecosystem is not a certified safety system. There is no hardware E-STOP path, no firmware-enforced limits or interlocks and no verified motion command yet; firmware images are checked with CRC-32 and an Ed25519 signature, and a release build refuses the published development keys (the tool heads and expansion boards behind the relay still run URTC bootloaders, which take a shared-key HMAC-SHA256 instead of a signature); TLS and mutual TLS are optional and off by default; no custom board has been populated or tested yet. Read the [security baseline](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md) and the [threat model](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md) before relying on any statement here for the safety of a person.

---

## 📋 At a glance

| | |
|---|---|
| Version | `0.1.9` |
| Maturity | Functional |
| Tests | 322 (`python -m pytest -q tests`) |
| Stack | Python 3.11+ / JSON Schema / systemd (edge role, Linux only) / two optional AI provider APIs (provider-agnostic diagnosis) / git (staging clone + git apply for the real canary deploy path) |
| Target | The Raspberry Pi CM5 of a HYDRA-UMC cell |
| On real hardware | Not yet: no run on real hardware is recorded for this version |

**Jump to:** [Overview](#-overview) · [Architecture](#-architecture) · [Quick start](#-quick-start) · [Testing](#-testing) · [Repository Structure](#-repository-structure) · [Related Projects](#-related-projects)

## 🚦 Project status

Each line is one part of this repository and the light says how far it is today. It is written from what the repository can show (tests, builds, runs), not from what is planned.

🟢 Done and verified · 🟡 Works, with known limits · 🟠 Partly done or not verified yet · 🔴 Not done or not working

| Area | State | What it means here |
|---|---|---|
| Software | 🟡 | Works for its main purpose; the honesty check above lists what is still missing |
| Tests | 🟢 | 322 automated tests, run on every change |
| Real hardware | 🔴 | Not yet: no run on real hardware is recorded for this version |
| Documentation | 🟢 | README in eight languages, checked against the manifest on every change |

## 🎯 Overview

HYDRA-UMC-OPS-AGENT is the maintenance-incident coordinator for the
HYDRA-UMC/URTC ecosystem. It owns one real lifecycle - **evidence →
diagnosis → human-approved change → canary deploy via
HYDRA-UMC-UPDATER → verification** - without reimplementing inference,
updates, or MCU safety logic that already exists elsewhere in the
ecosystem. This project now ships five of the six stages of that
lifecycle: **evidence**, **diagnosis**, **human-approved change**,
**canary deploy**, and **verification**.

Two roles, one package, no network transport between them yet:

1. **Edge role** (`edge collect`) - runs directly on the machine being
   observed (a real CM5 cell controller, or a developer's own
   workstation). Scans every sibling checkout for its own
   `hydra-umc.project.json`, optionally checks one or more systemd
   units and HTTP health endpoints, and derives a real
   `MaintenanceIncident` for every ACTUAL problem it finds - a clean
   scan produces zero incidents, never a synthetic "all OK" one. Every
   incident from the same run shares one correlation ID.
2. **Control-plane role** (`control show`) - runs on a development
   host and renders a saved snapshot file read-only: project inventory,
   health-check results, and every incident sorted with the most
   severe first. It never mutates the file it reads, and this delivery
   never "resolves" or acknowledges an incident from here either.
3. **Diagnosis** (`control diagnose`) - also runs on the control-plane
   role. Sends one already-redacted incident to an AI provider (any
   provider - `anthropic` and OpenAI ship out of the box, see
   [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)) and gets back a plain-text
   proposed root-cause explanation - a suggestion for a human to read,
   never a decision.
4. **Human-approved change** (`control propose` / `approve` / `reject`)
   - a real, immutable `ChangeProposal` (a unified diff, a description,
   a rationale) that transitions from `pending` to `approved`/`rejected`
   EXACTLY ONCE, always attributed to a real named person. See
   [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
5. **Canary deploy** (`control deploy-canary`) - refuses to run against
   anything but an `approved` proposal. Applies the diff to an
   independent staging clone, runs the target project's own real
   build-test command there, and only promotes (keeping the previous
   checkout as a real backup) if that passes - the live checkout is
   never touched otherwise.
6. **Verification** (`control verify`) - re-runs the exact real check
   that originally produced an incident, using Delivery 1's own
   functions, to confirm it is genuinely resolved.

```
$ hydra-umc-ops-agent edge collect \
    --node-name cm5-cell-3 --projects-root /home/pi/HYDRA-UMC \
    --systemd-unit hydra-umc-server.service \
    --http-health-url http://127.0.0.1:8090/health \
    --out snapshot.json
Wrote snapshot to snapshot.json (1 incident(s)).

$ hydra-umc-ops-agent control show snapshot.json
Node: cm5-cell-3  (collected 2026-01-01T10:15:03+00:00)

Projects found: 27
  - HYDRA-UMC-SERVER v0.1.0 (functional)
  ...

Service health checks: 1
  - hydra-umc-server.service: NOT ACTIVE (failed)

Incidents: 1
  [CRITICAL] hydra-umc-server.service: systemd unit is not active: failed  (id=7c2c1e4a-...)

$ ANTHROPIC_API_KEY=sk-ant-... hydra-umc-ops-agent control diagnose \
    snapshot.json --incident-id 7c2c1e4a-...
{
  "incidentId": "7c2c1e4a-...",
  "explanation": "Likely cause: the service crashed on startup...",
  "disclaimer": "This is an AI-generated suggestion, not a decision. ..."
}

$ hydra-umc-ops-agent control propose snapshot.json --incident-id 7c2c1e4a-... \
    --project-name HYDRA-UMC-SERVER --description "Increase retry count to 3" \
    --diff-file fix.diff --rationale "gives up too early" --out proposal.json
$ hydra-umc-ops-agent control keygen --name ana --key-out ana.pem --public-out ana.pub
$ hydra-umc-ops-agent control approve proposal.json --approved-by ana --key ana.pem \
    --live-root /home/pi/HYDRA-UMC/HYDRA-UMC-SERVER
$ hydra-umc-ops-agent control deploy-canary proposal.json \
    --live-root /home/pi/HYDRA-UMC/HYDRA-UMC-SERVER --build-test-command "bash build-test.sh" \
    --approvers approvers.json --service-unit hydra-umc-server.service \
    --health-url http://127.0.0.1:3000/health
$ hydra-umc-ops-agent control verify snapshot.json --incident-id 7c2c1e4a-... --node-name cm5-cell-3
```

See [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) for the full,
real operator flow above.

There is no default/bare invocation and no GUI in this delivery - see
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) for the full, real
command surface.

## 🧩 Role in HYDRA-UMC

**HYDRA-UMC-OPS-AGENT** is the maintenance-incident coordinator of the ecosystem. It owns one lifecycle (evidence, diagnosis, human-approved change, canary deploy through `HYDRA-UMC-UPDATER`, verification) and reimplements neither inference, updates nor the safety logic of the controllers.

## 🏛️ Architecture

<p align="center">
  <img src="images/architecture.svg" alt="HYDRA-UMC-OPS-AGENT architecture" width="100%">
</p>

### ARCHITECTURE & DESIGN DECISIONS

- **An incident is derived, never declared.** `IncidentBatch.add_*`
  methods return `None` when the thing they examined was actually
  healthy. There is no code path that fabricates an incident from a
  clean observation, and no code path that silently drops a real one.
- **A protocol boundary degrades honestly, it never guesses.**
  `check_systemd_unit_health()` raises a distinct
  `SystemdUnavailableError` the moment `systemctl` isn't on `PATH` -
  which is every time on this development machine, and on any
  non-systemd host - instead of reporting a made-up "inactive" status.
  `check_http_health()` keeps a real network failure (`status_code is
  None`) distinguishable from a real-but-unhealthy HTTP response.
- **Redaction is the single most safety-critical piece of code here.**
  `log_redaction.py` is pure, dependency-free text transformation,
  covered on its own before anything else consumes it. A key-name
  match has to look for the secret name as a substring of a real
  identifier token (`DB_PASSWORD`, `api-key`), not a `\b`-bounded word -
  `_` is a word character in regex, so a naive `\bpassword\b` never
  matches `DB_PASSWORD` at all. `MaintenanceIncident.to_dict()` runs
  `redact_secrets()` on `symptom` again at serialization time, even
  though every caller already redacted it upstream - defense in depth
  for the one field most likely to carry a copy-pasted log line.
- **The `MaintenanceIncident`/`NodeSnapshot` contract is fixed on
  purpose, field-for-field, to an explicit "CONTRATO
  MINIMO".** See [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md).
  A later delivery that talks to a real AI provider or ticketing system
  should never need to translate between two incompatible shapes.
- **Diagnosis is provider-agnostic by design.** `diagnose_incident()`
  depends only on a minimal `AIProvider` Protocol - a real, named AI
  vendor is never hardcoded into the core logic. Two real providers
  (`anthropic`, OpenAI) ship as optional extras; a caller can pass any
  other object implementing the same one-method contract.
- **A canary deploy never touches the live checkout until a real build
  already proved the change works.** `deploy_canary()` refuses to run at
  all unless the given proposal's own `status` is `approved`, then
  stages the diff in an independent local clone and only promotes
  (two-rename swap, previous checkout kept as a real backup) if that
  project's own build-test command actually exits `0` - the same
  atomic-by-verification pattern HYDRA-UMC-UPDATER's own `install.py`
  already uses.
- **A proposal is decided exactly once.** `approve_change()`/`reject_change()`
  each raise `InvalidTransitionError` on anything but a `pending`
  proposal - a second decision never silently overwrites the first, and
  every decision is attributed to a real, non-empty name.
- **An approval is a signature, not a field.** `approve_change()` signs, with the approver's own Ed25519 private key, a statement of exactly what is approved - the proposal, the SHA-256 of the diff, who approves, until when, the commit of the checkout it is for and whether protected paths are allowed. `deploy_canary()` accepts it only if the signature checks out against a registry of approvers' *public* keys, so whoever can merely write the proposal file cannot approve anything. The diff is also refused if it holds something shaped like a real secret or touches CI, build-test or service files without saying so; the build-test runs with a minimal environment; a service can be stopped and health-checked around the swap with an automatic rollback; and every proposal, approval, deploy, rollback and prune is appended to a hash-chained audit journal. See [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
- **Verification re-runs the SAME real check, never a looser one.**
  `verify_incident_resolved()` calls straight back into Delivery 1's own
  `check_http_health()`/`check_systemd_unit_health()`/
  `check_project_manifest()` - there is no second, independently-drifting
  health-check implementation anywhere in this project. A manifest
  incident with a real `base_commit:` (best-effort, captured at
  detection) is additionally checked against HYDRA-UMC-SDK's shared
  `compare_runs()` "apparent success" control - the checkout's
  own commit must have genuinely moved, not just have the file look
  fixed on disk. See [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
- **Delivery 6 is blocked, not skipped.** HYDRA-UMC-VOICE-UI's own real
  contract (`gateway.py`) is a bounded, inbound transcript-to-intent
  gateway with no real outbound-notification surface today - inventing
  one here would have meant fabricating an integration that doesn't
  exist, which this project's own standard does not allow. See the
  ROADMAP section below.
- **stdlib only for the core.** `edge collect`/`control show`/`control
  propose`/`control approve`/`control reject`/`control verify` need no
  dependency at all - `urllib.request` for the HTTP check,
  `subprocess`/`shutil.which` for the systemd check, `git` (a real
  external binary, not a Python package) for the canary-deploy stage and
  for a manifest incident's own `base_commit:` capture. Only `control
  diagnose` (an `ai-*` extra) and a manifest incident's `compare_runs()`
  re-check (the `sdk` extra) need an optional dependency, each only for
  what actually uses it.

## 🚀 Quick start

Requires Python 3.11 or newer.

```bash
./build.sh  # Linux, macOS (build.bat on Windows)
./run.sh    # demo: edge collect on a throwaway sample project, then control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
```

## 🧪 Testing

322 automated tests run with `python -m pytest -q tests`. They need no hardware and nothing outside this machine.

The CI runs `HYDRA_UMC_CI=1 python tools/ci_validate.py`, which checks the manifest, the documents, the eight READMEs and the pictures.

## 🏗️ Build & Release

```bash
chmod +x build.sh   # one-time
./build.sh          # creates .venv, pip install -e ".[dev]", compile-checks + tests
./run.sh                                          # real demo: edge collect against a throwaway
                                                   # sample project, then control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # or .[ai-openai] - only needed for control diagnose
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name NAME --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control keygen --name you --key-out you.pem --public-out you.pub
./run.sh control approve proposal.json --approved-by you --key you.pem --live-root PATH
./run.sh control deploy-canary proposal.json --live-root PATH --build-test-command "bash build-test.sh" --approvers approvers.json
pip install -e ".[signing]"                       # needed to sign and to verify approvals (cryptography)
pip install -e ".[sdk]"                           # only needed to re-verify a manifest incident's own base_commit
./run.sh control verify snapshot.json --incident-id <id>
```

On Windows: `build.bat`, then `run.bat` (same demo when called with no
arguments) / `run.bat edge collect ...` / any of the `control ...`
subcommands above. `build-test.sh`/`.bat` performs the same
non-mutating Python-syntax compile check this project's own CI workflow
performs, without touching the project version or CHANGELOG - it does
NOT run the test suite itself; CI runs `pytest` as its own separate,
later step. Run `./build.sh`/`build.bat` (or `pytest tests/` directly)
for the full local test suite.

**Troubleshooting**

- `edge collect` reports `systemdAvailable: false` for every run: this
  host genuinely has no `systemctl` on `PATH` (every non-Linux
  development machine, and some minimal Linux containers) - this is the
  intended, honest degradation, not a bug. See
  [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).
- `control show` fails with `ERROR: ...`: the snapshot file doesn't
  exist, isn't valid JSON, or isn't a real snapshot object - re-run
  `edge collect` and check its own `--out` path.
- `control diagnose` fails with `ERROR: the optional '<provider>'
  package is not installed`: run `pip install -e ".[ai-anthropic]"` or
  `".[ai-openai]"` first, matching `--provider`.
- `control diagnose` fails with `ERROR: no ... API key available`: set
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` before running it.
- `control deploy-canary` fails with `ERROR: refusing to deploy ...`:
  the proposal is not `approved` yet - run `control approve` first.
- `control deploy-canary` fails with `ERROR: ... signed approval` / `not a registered approver` / `expired` / `approved for commit`: the approval is missing, was made with a key that is not in the registry, has run out, or was given for another state of the checkout. Approve again with `control approve --key YOURKEY --live-root PATH`. A proposal approved by editing the file, or before approvals were signed, is never accepted.
- `control deploy-canary` reports `promoted: false`: read `buildOutput`
  in the result JSON - the staging build genuinely failed, and the live
  checkout was never touched. See
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).

## 📂 Repository Structure

<p align="center">
  <img src="images/repository-structure.svg" alt="Repository structure of HYDRA-UMC-OPS-AGENT" width="100%">
</p>

<details>
<summary>Text version of the tree</summary>

```text
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/   source code
│   ├── __init__.py            Package version
│   ├── _atomic.py             Durable all-or-nothing file writes for stores, proposals and results
│   ├── approval_signing.py    Ed25519 signatures of approvals; the approver registry
│   ├── audit_journal.py       Hash-chained, append-only audit journal
│   ├── diff_policy.py         What a diff may hold and touch (secret shapes, protected paths, size)
│   ├── log_redaction.py       Pure secret redaction (KEY=VALUE, Bearer tokens, PEM blocks)
│   ├── inventory.py           Manifest scan + systemd/HTTP health checks
│   ├── incident.py            MaintenanceIncident / IncidentBatch contract
│   ├── edge_agent.py          puts the pieces into one NodeSnapshot
│   ├── control_plane.py       Read-only snapshot loader + text report renderer
│   ├── diagnosis.py           Delivery 2: provider-agnostic AI-assisted diagnosis suggestion
│   ├── change_proposal.py     Delivery 3: immutable, human-approved ChangeProposal lifecycle
│   ├── canary_deploy.py       Delivery 4: stage + apply + verify + promote, approved-only
│   ├── verification.py        Delivery 5: re-runs the real check behind an incident
│   ├── cli.py                 edge and control subcommands
│   └── incident_store.py      The durable, deduplicated incident layer: one open record per (node, component), resolved only when that component was re-checked and is clean
├── tests/                     Real tests for all 11 modules, incl. a local http.server fixture, a fake AI provider, and a real throwaway git repo for canary deploy
├── docs/                      documents of the project
├── images/                    Media and app icons
├── tools/                     project tools and CI checks
├── .github/                   CI workflow and issue templates
├── build.sh / build.bat       venv + editable install + compile-check + tests
├── run.sh / run.bat           Real edge collect + control show demo (no arguments), or forwards a real CLI command
├── bump_version.py            explicit version bump
├── bump_manifest_version.py   Syncs hydra-umc.project.json's version to the native one (--sync)
├── CHANGELOG.md               what changed in each version
├── build-test.sh              non-mutating build check
├── hydra-umc.project.json     manifest: version, maturity, family
├── pyproject.toml             package metadata
└── test.sh                    runs the tests
```

</details>

## 🗺️ Roadmap & Known limits

**Known limits today**

Deliveries 1-5 (this version) ship **evidence**, **diagnosis**,
**human-approved change**, **canary deploy** and **verification** - the
real lifecycle already named in this project's own manifest and
CHANGELOG. What remains:

- **Delivery 6 - Voice/notification integration - genuinely BLOCKED,
  not merely deferred.** The plan was to surface a critical incident, or
  a completed canary, through HYDRA-UMC-VOICE-UI. Real investigation of
  VOICE-UI's own code (`gateway.py`) found it is a bounded, INBOUND
  transcript-to-intent gateway (a Watch sends text, gets a reply) with
  no real outbound-notification/push surface today. Building one here
  would mean inventing an integration point VOICE-UI itself does not
  have - this project's own no-fabrication standard does not allow
  that. Revisit this once VOICE-UI (or a successor) grows a real
  "inbound assistant announcement" capability of its own.
- A real transport between the edge and control-plane roles (today,
  moving a snapshot file between them is a manual step).

## 🌍 Languages

This README and the documents of the repository exist in eight languages: English, Spanish, German, French, Italian, Japanese, Chinese and Portuguese (Portugal). They are written together and checked in the CI so that the eight files have the same sections and the same links. This repository has no screen or message catalogue of its own, so there are no interface strings to translate.

## 🔗 Related Projects

This project is part of the HYDRA-UMC robotics ecosystem by the same author (JuanenRac / Electro Hobby 3D). Worth knowing about, since a request might actually be about one of these rather than this repository.

**Directly Related**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — detects, installs and updates every ecosystem checkout. A canary deploy here follows the same atomic-by-verification pattern but is its own implementation, not a call into the updater, so the two can disagree: the updater refuses to fast-forward a checkout that carries a canary's local commit, and says which commit.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — another "Ecosystem Operations" sibling: builds a fresh, fully current CM5 image rather than observing an already-running one.
- **[HYDRA-UMC-DEV-SERVER](https://github.com/JuanenRac/HYDRA-UMC-DEV-SERVER)** — reproducible development host that builds candidates and coordinates its durable task queue with this project's own incident lifecycle; it never approves its own tasks.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — a real gRPC-based fleet health watchdog with its own retry/backoff and identity-mismatch detection - a related but distinct concern (live fleet-node health over gRPC) from this project's own manifest/systemd/HTTP evidence collection and incident lifecycle.

**Also Part of the Ecosystem**

*Core Hardware & Platform*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — the robot-arm motherboard design: CM5 host + dual-core STM32H745, meant to orchestrate up to 8 tool arms over CAN-OTA/SPI-OTA (firmware at an early stage; no populated board yet).
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — reproducible Raspberry Pi OS product layer for the CM5: read-only agent, validated config/profiles, WiFi first-contact provisioning.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — the shared JSON-Schema contract and software job-gate boundary every bridge validates its commands against (not a certified safety function).

*Core Backend & Clients*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — the real headless backend (REST/WebSocket) every control client actually talks to.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — web control dashboard with real-time multi-robot 3D visualization.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — desktop (PySide6) swarm command center for multiple servers at once.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — native Android control app with biometric login and a paired Wear OS companion.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — iOS/iPadOS control app (Flutter) with real-time WebSocket sync.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — native touch UI for the onboard 7" DSI touchscreen, embedded on the CM5 itself.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — desktop graphical URDF creator/editor that pushes finished models into STUDIO's own catalog.
- **[HYDRA-UMC-EDITOR-STL](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-STL)** — desktop STL model editor, transforming/replacing/removing/adding real parts in the same model catalog HYDRA-UMC-EDITOR-URDF also edits.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — coordination boundary for AGV/AMR fleets via a VDA 5050 MQTT publisher (tested against an emulated fleet only).
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — high-level CNC-cell coordinator with GRBL status/control-byte access (tested against an emulator only).
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — coordination boundary for legged/humanoid droids, with a Boston Dynamics Spot command sender (tested against an emulator only).
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — laser-cell coordinator reading 3 key/enclosure/interlock GPIO signals (tested against a fake chip only; it cannot arm or fire a laser).
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — safe high-level board-flow coordinator for OpenPnP pick-and-place.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — safe coordination boundary for Moonraker/Klipper 3D printers, with real gated job commands.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — coordinator with a lazily imported rclpy ROS 2 transport (not yet run against a ROS 2 installation).
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — coordination boundary for camera-equipped UAVs, with a MAVLink command sender (tested against an emulator only).

*URTC Tool Platform*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware for the physical Universal Robot Tool Controller PCB, 25+ tool profiles over CAN bus.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — desktop GUI flashing tool for URTC boards, CAN-OTA plus full-chip SWD/JTAG.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — desktop live CAN-bus diagnostic tool for URTC boards, one panel per tool profile.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — browser-based alternative to URTC-TESTER via the Web Serial API, no local install needed.
- **[URTC-GATEWAY](https://github.com/JuanenRac/URTC-GATEWAY)** — gateway in front of the URTC CAN bus: an allowed list of identifiers, a rate limit and a session key; software tested on a computer, not yet on a real bus.

*Vision AI Node (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — integration hub for the Hailo-8 vision pipeline, with a real per-stage hardware-readiness check.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — real compiled-model registry with Hailo-architecture/checksum safe-load verification.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — real GStreamer pipeline + MediaMTX config generator with a real HailoRT integration boundary.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — Position-Based Visual Servoing correction law with authorisation gated on the zone state; no camera pose estimation yet.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — v0 zone-breach, calibration-freshness and E-STOP-request logic that takes object positions from a file; no detector feeds it and no physical E-STOP is wired to it yet.

*Cognitive AI Node (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — integration hub for the Hailo-10 cognitive pipeline (LLM/VLA/voice orchestration).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — real action-token encoding/decoding and trajectory generation for a Vision-Language-Action model.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — real voice front-end (VAD + intent parser) with a bounded, confirmation-gated Watch relay - once considered as a Delivery 6 notification surface for this project, found to have no real outbound-notification contract today (see the ROADMAP section).
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — real rule-based task decomposition and semantic error recovery over MCU error codes.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — real stdlib-only TF-IDF document search over this ecosystem's own Markdown docs.
- **[HYDRA-UMC-LOCAL-TECHNICIAN](https://github.com/JuanenRac/HYDRA-UMC-LOCAL-TECHNICIAN)** — local, policy-gated AI maintenance technician for the ecosystem itself - observes, diagnoses and proposes fixes; the two highest risk levels are deliberately not implemented yet.

*Orchestration & Swarm*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — integration hub with a real gRPC/Protobuf health-report contract and mission state machine.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — real priority-based job queue with deduplication, over a real HTTP API.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — real RRT-based 3D path planner with real obstacle/workspace collision validation.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — real CRDT LWW-Element-Map state sync, property-tested for multi-cell convergence.

*Digital Twin & Simulation*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — integration hub for the digital-twin engine, with a real version-compatibility sync contract.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — hardware-in-the-loop router with a software collision interlock between simulation and real hardware (tested without real hardware).
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — real forward kinematics and joint-limit validation over a real URDF subset.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — real procedural 2D scene generator with YOLO/COCO annotation export.

*Data & Analytics*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — real sqlite3-backed time-series store with a real ingest/query HTTP API.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — real FFT + statistical baseline anomaly detector with drift monitoring.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — real OEE/availability calculation over DATALAKE history, with reproducible CSV export.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — real CAN/WebSocket ingestion pipeline into DATALAKE, with sequence deduplication.

*Industrial Gateway*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — integration hub relaying to industrial protocols, with a real command allowlist/backpressure layer.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — real OPC-UA address space, verified with a real binary-protocol client session.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — real MQTT broker with optional per-client authentication and topic ACLs.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — real MTConnect `/probe` and `/current` XML endpoints with degraded-mode output.

*Complementary Tools*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — Smart Summaries and Anomaly Highlighting panels over DATALAKE/ANOMALY-DETECTOR, with an honest statistical fallback.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — fleet CLI with a real, stable exit-code contract, a genuine live client of HYDRA-UMC-SERVER's own API.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — WearOS companion app with haptic alert patterns and a paired-phone voice relay (not yet run on a physical watch).
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — external adapter capability catalog, GET-only by design.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware for a board-mounting rack with real tool-ID decoding and Smart Idle pre-heating logic.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware plus a real Python vision companion for a thermal/RGB inspection tool head.

## 📚 Documentation

Where to read more:

* **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — every subcommand, its flags, and the exit-code contract.
* **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — the real `MaintenanceIncident`/`NodeSnapshot` JSON shape.
* **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — Delivery 2's own real contract, providers, credentials and safety boundary.
* **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — Deliveries 3-5's own real contract, the full stage/apply/verify/promote sequence, and a real operator flow example.
* [Security baseline of the ecosystem](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md)
* [Threat model of the ecosystem](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md)
* [Changelog of this repository](CHANGELOG.md)
* [License of this repository](LICENSE.md)

## 🤝 Contributing & Community

* Before a pull request run `HYDRA_UMC_CI=1 py -3 tools/ci_validate.py` (or `HYDRA_UMC_CI=1 python3 tools/ci_validate.py`): it must print `CI_VALIDATION=PASS`. Do not run `build.sh` or `build.bat` for this check; building is not a check.
* The eight READMEs are written from one source in HYDRA-UMC-DOCS; do not edit them by hand. Change the source and write them again with `tools/make_readmes.py`.
* Do not state in a README what has not run: say "simulated" or "not tried on hardware" where that is the truth.
* See [CONTRIBUTING.md](CONTRIBUTING.md), the [code of conduct](CODE_OF_CONDUCT.md), [SECURITY.md](SECURITY.md) and [SUPPORT.md](SUPPORT.md).

## 👤 AUTHOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENSE

GPL-3.0-or-later - [LICENSE](LICENSE).
