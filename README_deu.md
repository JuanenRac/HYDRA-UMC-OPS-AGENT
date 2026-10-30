<!-- =============================================================================
HYDRA-UMC-OPS-AGENT - Maintenance-incident coordinator
Copyright (C) JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | 🇩🇪 <b>Deutsch</b> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a> | <a href="README_por.md">🇵🇹 Português</a></p>

### 🔎 Schreibgeschützte Beobachtung von Wartungsvorfällen für das gesamte Ökosystem

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Language">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="Core">
  <img src="https://img.shields.io/badge/Tests-350%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.0-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-0F6CBD.svg" alt="Maturity">
</p>

---

> **Stand von Sicherheit (Safety) und Security:** Dieses Ökosystem ist kein zertifiziertes Sicherheitssystem. Es gibt noch keinen Hardware-E-STOP-Pfad, keine von der Firmware durchgesetzten Grenzen oder Verriegelungen und keinen verifizierten Bewegungsbefehl; Firmware-Images werden mit CRC-32 und einer Ed25519-Signatur geprüft, und ein Release-Build verweigert die veröffentlichten Entwicklungsschlüssel (die Werkzeugköpfe und Erweiterungsplatinen hinter dem Relais laufen noch mit URTC-Bootloadern, die statt einer Signatur ein HMAC-SHA256 mit gemeinsamem Schlüssel verwenden); TLS und gegenseitiges TLS sind optional und standardmäßig aus; noch keine eigene Platine wurde bestückt oder getestet. Lesen Sie die [Sicherheitsbasis](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md) und das [Bedrohungsmodell](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md), bevor Sie sich für die Sicherheit einer Person auf eine Aussage hier verlassen.

---

## 📋 Auf einen Blick

| | |
|---|---|
| Version | `0.2.0` |
| Reifegrad | Funktionsfähig |
| Tests | 350 (`python -m pytest -q tests`) |
| Technik | Python 3.11+ / JSON Schema / systemd (edge role, Linux only) / two optional AI provider APIs (provider-agnostic diagnosis) / git (staging clone + git apply for the real canary deploy path) |
| Ziel | Der Raspberry Pi CM5 einer HYDRA-UMC-Zelle |
| Auf echter Hardware | Noch nicht: für diese Version ist kein Lauf auf echter Hardware vermerkt |

**Springe zu:** [Überblick](#-überblick) · [Architektur](#-architektur) · [Funktionen](#-funktionen) · [Schnellstart](#-schnellstart) · [Tests](#-tests) · [Struktur des Repositorys](#-struktur-des-repositorys) · [Verwandte Projekte](#-verwandte-projekte)

## 🚦 Projektstatus

Jede Zeile ist ein Teil dieses Repositorys, und die Ampel sagt, wie weit er heute ist. Sie beruht auf dem, was das Repository zeigen kann (Tests, Builds, Läufe), nicht auf dem, was geplant ist.

🟢 Fertig und überprüft · 🟡 Funktioniert, mit bekannten Grenzen · 🟠 Teilweise fertig oder noch nicht überprüft · 🔴 Nicht gemacht oder funktioniert nicht

| Bereich | Stand | Was das hier bedeutet |
|---|---|---|
| Software | 🟡 | Funktioniert für seinen Hauptzweck; die Ehrlichkeitsprüfung oben nennt, was noch fehlt |
| Tests | 🟢 | 350 automatische Tests, bei jeder Änderung ausgeführt |
| Echte Hardware | 🔴 | Noch nicht: für diese Version ist kein Lauf auf echter Hardware vermerkt |
| Dokumentation | 🟢 | README in acht Sprachen, bei jeder Änderung gegen das Manifest geprüft |

## 🎯 Überblick

HYDRA-UMC-OPS-AGENT ist der Koordinator für Wartungsvorfälle des
HYDRA-UMC/URTC-Ökosystems. Er besitzt genau einen echten Lebenszyklus -
**Beweis → Diagnose → von einer Person genehmigte Änderung →
Canary-Deployment via HYDRA-UMC-UPDATER → Verifizierung** - ohne
Inferenz, Updates oder MCU-Sicherheitslogik neu zu implementieren, die
bereits anderswo im Ökosystem existieren. Dieses Projekt liefert nun
fünf der sechs Stufen dieses Lebenszyklus: **den Beweis**, **die
Diagnose**, **die von einer Person genehmigte Änderung**, **das
Canary-Deployment** und **die Verifizierung**.

Zwei Rollen, ein Paket, noch kein Netzwerktransport zwischen ihnen:

1. **Edge-Rolle** (`edge collect`) - läuft direkt auf der beobachteten
   Maschine (einer echten CM5-Zelle oder der eigenen Workstation eines
   Entwicklers). Scannt jeden Geschwister-Checkout nach dessen eigener
   `hydra-umc.project.json`, prüft optional eine oder mehrere
   systemd-Units und HTTP-Health-Endpunkte, und leitet für jedes
   TATSÄCHLICH gefundene Problem einen echten `MaintenanceIncident` ab -
   ein sauberer Scan erzeugt null Vorfälle, niemals ein synthetisches
   "alles OK". Alle Vorfälle desselben Laufs teilen eine einzige
   Korrelations-ID.
2. **Control-Plane-Rolle** (`control show`) - läuft auf einem
   Entwicklungshost und rendert eine gespeicherte Snapshot-Datei
   schreibgeschützt: Projektinventar, Ergebnisse der Health-Checks, und
   alle Vorfälle sortiert vom schwersten zum leichtesten. Sie verändert
   nie die Datei, die sie liest, und diese Lieferung "löst" auch von
   hier aus keinen Vorfall auf oder bestätigt ihn.
3. **Diagnose** (`control diagnose`) - läuft ebenfalls auf der
   Control-Plane-Rolle. Sendet einen bereits redigierten Vorfall an
   einen KI-Anbieter (beliebig - `anthropic` und OpenAI sind von Haus aus
   dabei, siehe [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)) und erhält eine
   vorgeschlagene Ursachenerklärung als Klartext zurück - ein Vorschlag,
   den eine Person lesen soll, niemals eine Entscheidung.
4. **Von einer Person genehmigte Änderung** (`control propose` /
   `approve` / `reject`) - ein echter, unveränderlicher `ChangeProposal`
   (ein Unified Diff, eine Beschreibung, eine Begründung), der von
   `pending` zu `approved`/`rejected` GENAU EINMAL übergeht, immer einer
   echten, namentlich genannten Person zugeschrieben. Siehe
   [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
5. **Canary-Deployment** (`control deploy-canary`) - verweigert die
   Ausführung gegen alles außer einem `approved`-Vorschlag. Wendet den
   Diff auf einen unabhängigen Staging-Klon an, führt dort den eigenen
   echten Build-Test-Befehl des Zielprojekts aus, und befördert
   (bewahrt den vorherigen Checkout als echtes Backup) nur, wenn das
   gelingt - der reale Checkout wird sonst nie angefasst.
6. **Verifizierung** (`control verify`) - führt genau die reale Prüfung
   erneut aus, die den Vorfall ursprünglich erzeugt hat, unter
   Verwendung der eigenen Funktionen von Lieferung 1, um zu bestätigen,
   dass er wirklich behoben ist.

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
    --approvers approvers.json --policy ops-agent-policy.json --service-unit hydra-umc-server.service \
    --health-url http://127.0.0.1:3000/health
$ hydra-umc-ops-agent control verify snapshot.json --incident-id 7c2c1e4a-... --node-name cm5-cell-3
```

Siehe [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) für den
vollständigen, echten Betreiber-Ablauf oben.

In dieser Lieferung gibt es weder eine Standard-/argumentlose Aufrufform
noch eine GUI - siehe
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) für die vollständige,
echte Befehlsoberfläche.

## 🧩 Rolle in HYDRA-UMC

**HYDRA-UMC-OPS-AGENT** ist der Koordinator für Wartungsvorfälle im Ökosystem. Er besitzt genau einen Lebenszyklus (Belege, Diagnose, von Menschen genehmigte Änderung, Canary-Auslieferung über `HYDRA-UMC-UPDATER`, Verifikation) und implementiert weder Inferenz noch Updates noch die Sicherheitslogik der Steuerungen neu.

## 🏛️ Architektur

<p align="center">
  <img src="images/architecture.svg" alt="HYDRA-UMC-OPS-AGENT architecture" width="100%">
</p>

### ARCHITEKTUR UND DESIGN-ENTSCHEIDUNGEN

- **Ein Vorfall wird abgeleitet, niemals erklärt.** Die `add_*`-Methoden
  von `IncidentBatch` geben `None` zurück, wenn das Untersuchte
  tatsächlich gesund war. Es gibt keinen Codepfad, der aus einer
  sauberen Beobachtung einen Vorfall erfindet, und keinen, der einen
  echten stillschweigend verwirft.
- **Eine Protokollgrenze degradiert ehrlich, sie rät niemals.**
  `check_systemd_unit_health()` wirft in dem Moment einen eigenen
  `SystemdUnavailableError`, in dem `systemctl` nicht im `PATH` ist -
  was auf dieser Entwicklungsmaschine immer der Fall ist, und auf jedem
  Host ohne systemd - statt einen erfundenen "inactive"-Status zu
  melden. `check_http_health()` hält einen echten Netzwerkfehler
  (`status_code is None`) unterscheidbar von einer echten, aber
  ungesunden HTTP-Antwort.
- **Die Redaktion ist hier das sicherheitskritischste Stück Code.**
  `log_redaction.py` ist eine reine, abhängigkeitsfreie
  Textumwandlung, durch eigene Tests abgedeckt, bevor irgendetwas
  anderes sie konsumiert. Ein Schlüsselnamens-Treffer muss den
  Geheimnisnamen als Teilstring eines echten Identifikator-Tokens
  suchen (`DB_PASSWORD`, `api-key`), nicht als `\b`-begrenztes Wort -
  `_` ist in einem regulären Ausdruck ein Wortzeichen, sodass ein
  naives `\bpassword\b` niemals auf `DB_PASSWORD` passt.
  `MaintenanceIncident.to_dict()` führt `redact_secrets()` auf
  `symptom` beim Serialisieren erneut aus, selbst wenn der Aufrufer es
  bereits vorher redigiert hat - Tiefenverteidigung für das Feld, das
  am ehesten eine kopierte Log-Zeile trägt.
- **Der `MaintenanceIncident`/`NodeSnapshot`-Vertrag ist absichtlich
  Feld für Feld auf ein ausdrückliches "CONTRATO MINIMO" festgelegt.**
  Siehe [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md). Eine
  spätere Lieferung, die mit einem echten KI-Anbieter oder
  Ticket-System spricht, sollte niemals zwischen zwei inkompatiblen
  Formen übersetzen müssen.
- **Die Diagnose ist von Natur aus anbieterunabhängig.**
  `diagnose_incident()` hängt nur von einem minimalen `AIProvider`-Protocol
  ab - ein echter, namentlich genannter KI-Anbieter wird nie im Kerncode
  festgelegt. Zwei echte Anbieter (`anthropic`, OpenAI) werden als
  optionale Extras mitgeliefert; ein Aufrufer kann jedes andere Objekt
  übergeben, das denselben Ein-Methoden-Vertrag implementiert.
- **Ein Canary-Deployment fasst den echten Checkout nie an, bevor ein
  echter Build bereits bewiesen hat, dass die Änderung funktioniert.**
  `deploy_canary()` verweigert die Ausführung, solange der `status` des
  gegebenen Vorschlags nicht `approved` ist, staged dann den Diff in
  einem unabhängigen lokalen Klon und befördert (Zwei-Umbenennungs-Swap,
  vorheriger Checkout als echtes Backup aufbewahrt) nur, wenn der eigene
  Build-Test-Befehl dieses Projekts wirklich mit Code `0` endet - dasselbe
  atomar-durch-Verifizierung-Muster, das der eigene `install.py` von
  HYDRA-UMC-UPDATER bereits verwendet.
- **Ein Vorschlag wird genau einmal entschieden.**
  `approve_change()`/`reject_change()` werfen jeweils
  `InvalidTransitionError` bei allem, was nicht `pending` ist - eine
  zweite Entscheidung überschreibt nie stillschweigend die erste, und
  jede Entscheidung wird einem echten, nicht leeren Namen zugeschrieben.
- **Eine Freigabe ist eine Signatur, kein Feld.** `approve_change()` signiert mit dem eigenen Ed25519-Privatschlüssel des Freigebenden eine Erklärung dessen, was genau freigegeben wird: den Vorschlag, den SHA-256 des Diffs, wer freigibt, bis wann, den Commit des Checkouts, für den sie gilt, und ob geschützte Pfade erlaubt sind. `deploy_canary()` akzeptiert sie nur, wenn die Signatur gegen ein Register *öffentlicher* Schlüssel von Freigebenden gültig ist; wer nur die Vorschlagsdatei beschreiben kann, kann also nichts freigeben. Außerdem wird ein Diff abgelehnt, der etwas in der Form eines echten Geheimnisses enthält oder CI-, Build-Test- oder Service-Dateien berührt, ohne es zu sagen; der Build-Test läuft mit minimaler Umgebung; ein Dienst kann um den Austausch herum gestoppt und geprüft werden, mit automatischem Zurückrollen; und jeder Vorschlag, jede Freigabe, jedes Deployment, jedes Zurückrollen und Bereinigen wird an ein hash-verkettetes Audit-Journal angehängt. Siehe [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
- **Es laufen nur die Befehle einer Richtliniendatei.** `control deploy-canary` liest `--policy DATEI` (Standard: `OPS_AGENT_POLICY`, sonst `/etc/hydra-umc/ops-agent-policy.json`) und führt den Build-Test-Befehl nur aus, wenn die Datei genau diesen Befehl für das Projekt aufführt (Wort für Wort verglichen); ein nicht aufgeführtes Projekt, ein nicht aufgeführter Befehl, ein Pfad außerhalb der optionalen `allowed_paths` des Projekts und eine fehlende oder defekte Datei werden abgelehnt, bevor etwas bereitgestellt wird. `deploy/ops-agent-policy.json.example` führt das `build-test.sh` jedes Projekts auf.
- **Die Verifizierung führt DIESELBE echte Prüfung erneut aus, nie eine
  laxere.** `verify_incident_resolved()` ruft direkt die eigenen
  `check_http_health()`/`check_systemd_unit_health()`/
  `check_project_manifest()` von Lieferung 1 auf - es gibt nirgendwo in
  diesem Projekt eine zweite, unabhängig driftende Implementierung der
  Gesundheitsprüfung. Ein Manifest-Vorfall mit einem echten
  `base_commit:` (best-effort bei der Erkennung erfasst) wird zusätzlich
  gegen die geteilte `compare_runs()`-Kontrolle von HYDRA-UMC-SDK
  geprüft - der Commit des Checkouts muss sich wirklich bewegt haben, es
  reicht nicht, dass die Datei auf der Festplatte nur repariert aussieht.
  Siehe [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
- **Lieferung 6 ist blockiert, nicht einfach übersprungen.** Der eigene
  echte Vertrag von HYDRA-UMC-VOICE-UI (`gateway.py`) ist ein
  begrenztes, EINGEHENDES Gateway von Transkript zu Intent, ohne eine
  echte Oberfläche für ausgehende Benachrichtigungen heute - eine hier
  zu erfinden hätte bedeutet, eine Integration vorzutäuschen, die es
  nicht gibt, was der eigene Anti-Fabrikations-Standard dieses Projekts
  nicht erlaubt. Siehe den FAHRPLAN-Abschnitt unten.
- **Nur Standardbibliothek für den Kern.** `edge collect`/`control
  show`/`control propose`/`control approve`/`control reject`/`control
  verify` brauchen überhaupt keine Abhängigkeit - `urllib.request` für
  die HTTP-Prüfung, `subprocess`/`shutil.which` für die von systemd,
  `git` (ein echtes externes Binary, kein Python-Paket) für die
  Canary-Deployment-Stufe und für die `base_commit:`-Erfassung eines
  Manifest-Vorfalls. Nur `control diagnose` (ein `ai-*`-Extra) und die
  `compare_runs()`-Nachprüfung eines Manifest-Vorfalls (das `sdk`-Extra)
  brauchen eine optionale Abhängigkeit, jeweils nur für das, was sie
  tatsächlich benutzt.

## ✨ Funktionen

Ein übernommener Canary hinterlässt seine Änderung zusätzlich als Patch-Datei, mit `git format-patch` nach `<Projekt>.canary-patches/<Deploy-ID>.patch` außerhalb des Checkouts geschrieben und als `patchPath` im Ergebnis und im Audit-Eintrag gemeldet, sodass der lokale Commit geprüft und bewusst verworfen werden kann. Das Schreiben geschieht nach bestem Bemühen und ändert nie das Ergebnis des Deployments.

## 🚀 Schnellstart

Benötigt Python 3.11 oder neuer.

```bash
./build.sh  # Linux, macOS (build.bat on Windows)
./run.sh    # demo: edge collect on a throwaway sample project, then control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
```

## 🧪 Tests

350 automatische Tests laufen mit `python -m pytest -q tests`. Sie brauchen weder Hardware noch etwas außerhalb dieses Rechners.

Die CI führt `HYDRA_UMC_CI=1 python tools/ci_validate.py` aus; das prüft das Manifest, die Dokumente, die acht READMEs und die Bilder.

## 🏗️ Build und Veröffentlichung

```bash
chmod +x build.sh   # einmalig
./build.sh          # erstellt .venv, pip install -e ".[dev]", Compile-Check + Tests
./run.sh                                          # echte Demo: edge collect gegen ein
                                                   # Wegwerf-Beispielprojekt, dann control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # oder .[ai-openai] - nur für control diagnose nötig
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name NAME --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control keygen --name you --key-out you.pem --public-out you.pub
./run.sh control approve proposal.json --approved-by you --key you.pem --live-root PATH
./run.sh control deploy-canary proposal.json --live-root PATH --build-test-command "bash build-test.sh" --approvers approvers.json --policy ops-agent-policy.json
pip install -e ".[signing]"                       # needed to sign and to verify approvals (cryptography)
pip install -e ".[sdk]"                           # nur nötig, um den base_commit eines Manifest-Vorfalls erneut zu prüfen
./run.sh control verify snapshot.json --incident-id <id>
```

Unter Windows: `build.bat`, dann `run.bat` (dieselbe Demo ohne
Argumente) / `run.bat edge collect ...` / einer der obigen
`control ...`-Unterbefehle. `build-test.sh`/`.bat` führt dieselbe
Kompilierungsprüfung (nur Python-Syntax) aus, ohne die Projektversion
oder das CHANGELOG anzufassen, die die eigene CI dieses Projekts auch
ausführt - es führt NICHT selbst die Testsuite aus; die CI führt
`pytest` als eigenen, späteren Schritt aus. Führen Sie
`./build.sh`/`build.bat` (oder direkt `pytest tests/`) für die
vollständige lokale Testsuite aus.

**Fehlerbehebung**

- `edge collect` meldet bei jedem Lauf `systemdAvailable: false`: Dieser
  Host hat wirklich kein `systemctl` im `PATH` (jede
  Nicht-Linux-Entwicklungsmaschine, und manche minimalen
  Linux-Container) - das ist die erwartete ehrliche Degradation, kein
  Bug. Siehe [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).
- `control show` schlägt mit `ERROR: ...` fehl: Die Snapshot-Datei
  existiert nicht, ist kein gültiges JSON, oder ist kein echtes
  Snapshot-Objekt - führen Sie `edge collect` erneut aus und prüfen Sie
  dessen eigenen `--out`-Pfad.
- `control diagnose` schlägt mit `ERROR: the optional '<provider>'
  package is not installed` fehl: führen Sie `pip install -e
  ".[ai-anthropic]"` oder `".[ai-openai]"` aus, passend zu `--provider`.
- `control diagnose` schlägt mit `ERROR: no ... API key available` fehl:
  setzen Sie `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`, bevor Sie es
  ausführen.
- `control deploy-canary` schlägt mit `ERROR: refusing to deploy ...`
  fehl: der Vorschlag ist noch nicht `approved` - führen Sie zuerst
  `control approve` aus.
- `control deploy-canary` schlägt fehl mit `ERROR: ... signed approval` / `not a registered approver` / `expired` / `approved for commit`: Die Freigabe fehlt, wurde mit einem Schlüssel außerhalb des Registers erteilt, ist abgelaufen oder wurde für einen anderen Stand des Checkouts gegeben. Erneut freigeben mit `control approve --key IHRSCHLUESSEL --live-root PFAD`. Ein durch Bearbeiten der Datei oder vor der Signaturpflicht freigegebener Vorschlag wird nie akzeptiert.
- `control deploy-canary` meldet `promoted: false`: lesen Sie
  `buildOutput` im Ergebnis-JSON - der Staging-Build ist wirklich
  fehlgeschlagen, und der echte Checkout wurde nie angefasst. Siehe
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).

## 📂 Struktur des Repositorys

<p align="center">
  <img src="images/repository-structure.svg" alt="Repository structure of HYDRA-UMC-OPS-AGENT" width="100%">
</p>

<details>
<summary>Textversion des Baums</summary>

```text
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/   Quellcode
│   ├── __init__.py            Paketversion
│   ├── _atomic.py             Dauerhafte, atomare Dateischreibvorgänge für Speicher, Vorschläge und Ergebnisse
│   ├── approval_signing.py    Ed25519-Signaturen der Freigaben; Register der Freigebenden
│   ├── audit_journal.py       Hash-verkettetes Audit-Journal, nur anhängend
│   ├── diff_policy.py         Was ein Diff enthalten und berühren darf (Geheimnisformen, geschützte Pfade, Größe)
│   ├── log_redaction.py       Reine Geheimnis-Redaktion (KEY=VALUE, Bearer-Token, PEM-Blöcke)
│   ├── inventory.py           Manifest-Scan + systemd-/HTTP-Health-Checks
│   ├── incident.py            MaintenanceIncident-/IncidentBatch-Vertrag
│   ├── edge_agent.py          fügt die Teile zu einem NodeSnapshot zusammen
│   ├── control_plane.py       Schreibgeschützter Snapshot-Lader + Text-Report-Renderer
│   ├── diagnosis.py           Lieferung 2: anbieterunabhängiger KI-unterstützter Diagnosevorschlag
│   ├── change_proposal.py     Lieferung 3: unveränderlicher, von einer Person genehmigter ChangeProposal-Lebenszyklus
│   ├── canary_deploy.py       Lieferung 4: stage + apply + verify + promote, nur bei Genehmigung
│   ├── verification.py        Lieferung 5: führt die echte Prüfung hinter einem Vorfall erneut aus
│   ├── cli.py                 Unterbefehle edge und control
│   └── incident_store.py      Die dauerhafte, deduplizierte Vorfallsschicht: ein offener Eintrag je (Knoten, Komponente), nur gelöst, wenn die Komponente neu geprüft wurde und sauber ist
├── tests/                     Echte Tests für alle 11 Module, inkl. eines lokalen http.server-Fixtures, eines simulierten KI-Anbieters und eines echten Wegwerf-Git-Repositorys für das Canary-Deployment
├── docs/                      Dokumente des Projekts
├── images/                    Medien und App-Icons
├── tools/                     Projektwerkzeuge und CI-Prüfungen
├── .github/                   CI-Workflow und Issue-Vorlagen
├── build.sh / build.bat       venv + editierbare Installation + Compile-Check + Tests
├── run.sh / run.bat           Echte edge-collect + control-show-Demo (ohne Argumente), oder leitet einen echten CLI-Befehl weiter
├── bump_version.py            ausdrückliche Versionserhöhung
├── bump_manifest_version.py   Synchronisiert die Version von hydra-umc.project.json mit der nativen (--sync)
├── CHANGELOG.md               was sich in jeder Version geändert hat
├── build-test.sh              Build-Prüfung ohne Änderungen
├── hydra-umc.project.json     Manifest: Version, Reifegrad, Familie
├── pyproject.toml             Paketmetadaten
└── test.sh                    führt die Tests aus
```

</details>

## 🗺️ Roadmap und bekannte Grenzen

**Bekannte Grenzen heute**

Die Lieferungen 1-5 (diese Version) liefern **Beweis**, **Diagnose**,
**von einer Person genehmigte Änderung**, **Canary-Deployment** und
**Verifizierung** - den echten Lebenszyklus, der bereits im eigenen
Manifest und CHANGELOG dieses Projekts benannt ist. Was bleibt:

- **Lieferung 6 - Sprach-/Benachrichtigungsintegration - wirklich
  BLOCKIERT, nicht nur aufgeschoben.** Der Plan war, einen kritischen
  Vorfall oder ein abgeschlossenes Canary über HYDRA-UMC-VOICE-UI
  sichtbar zu machen. Die echte Untersuchung des eigenen Codes
  (`gateway.py`) ergab, dass es sich um ein begrenztes, EINGEHENDES
  Gateway von Transkript zu Intent handelt (eine Watch sendet Text,
  erhält eine Antwort), ohne eine echte Oberfläche für ausgehende
  Benachrichtigungen heute. Eine hier zu bauen hätte bedeutet, einen
  Integrationspunkt zu erfinden, den VOICE-UI selbst nicht hat - der
  eigene Anti-Fabrikations-Standard dieses Projekts erlaubt das nicht.
  Erneut aufgreifen, sobald VOICE-UI (oder ein Nachfolger) eine echte
  eigene Fähigkeit zur "eingehenden Assistenten-Ankündigung" entwickelt.
- Ein echter Transport zwischen den Edge- und Control-Plane-Rollen
  (heute ist das Verschieben einer Snapshot-Datei zwischen beiden ein
  manueller Schritt).

## 🌍 Sprachen

Diese README und die Dokumente des Repositorys gibt es in acht Sprachen: Englisch, Spanisch, Deutsch, Französisch, Italienisch, Japanisch, Chinesisch und Portugiesisch (Portugal). Sie entstehen gemeinsam, und die CI prüft, dass die acht Dateien dieselben Abschnitte und dieselben Links haben. Dieses Repository hat weder eine eigene Oberfläche noch einen eigenen Meldungskatalog, es gibt also keine Oberflächentexte zu übersetzen.

## 🔗 Verwandte Projekte

Dieses Projekt ist Teil des HYDRA-UMC-Robotik-Ökosystems desselben Autors (JuanenRac / Electro Hobby 3D). Gut zu wissen, da eine Anfrage eigentlich eines dieser Projekte betreffen könnte statt dieses Repositorys.

**Direkt verwandt**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — erkennt, installiert und aktualisiert jeden Ökosystem-Checkout. Ein Canary-Deployment folgt hier demselben Muster der Atomarität durch Verifikation, ist aber eine eigene Implementierung und kein Aufruf des Updaters, daher können beide voneinander abweichen: Der Updater verweigert das Fast-Forward eines Checkouts mit dem lokalen Commit eines Canary und nennt diesen Commit.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — ein weiterer "Ecosystem Operations"-Verwandter: baut ein neues, vollständig aktuelles CM5-Image, statt ein bereits laufendes zu beobachten.
- **[HYDRA-UMC-DEV-SERVER](https://github.com/JuanenRac/HYDRA-UMC-DEV-SERVER)** — reproduzierbarer Entwicklungshost, der Kandidaten baut und seine dauerhafte Aufgaben-Warteschlange mit dem Vorfall-Lebenszyklus dieses Projekts abstimmt; er genehmigt seine eigenen Aufgaben nie.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — ein echter gRPC-basierter Flotten-Health-Watchdog mit eigenem Retry/Backoff und Identitäts-Mismatch-Erkennung - ein verwandtes, aber eigenständiges Thema (Live-Gesundheit von Flottenknoten via gRPC) gegenüber der eigenen Manifest-/systemd-/HTTP-Beweissammlung und dem Vorfall-Lebenszyklus dieses Projekts.

**Ebenfalls Teil des Ökosystems**

*Kern-Hardware & Plattform*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — der Entwurf des Motherboards des Roboterarms: CM5-Host + Dual-Core-STM32H745, gedacht zur Koordination von bis zu 8 Werkzeugarmen über CAN-OTA/SPI-OTA (Firmware in einer frühen Phase; noch keine bestückte Platine).
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — reproduzierbare Raspberry-Pi-OS-Produktschicht für den CM5: schreibgeschützter Agent, validierte Konfiguration/Profile, WiFi-Ersteinrichtung.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — der gemeinsame JSON-Schema-Vertrag und die Software-Auftragsschranke, gegen die jede Bridge ihre Befehle validiert (keine zertifizierte Sicherheitsfunktion).

*Kern-Backend & Clients*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — das reale Headless-Backend (REST/WebSocket), mit dem jeder Steuerungsclient tatsächlich spricht.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — Web-Steuerungs-Dashboard mit Echtzeit-3D-Visualisierung mehrerer Roboter.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — Desktop-Schwarmleitstand (PySide6) für mehrere Server gleichzeitig.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — native Android-Steuerungs-App mit biometrischem Login und einer gekoppelten Wear-OS-Begleit-App.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — iOS/iPadOS-Steuerungs-App (Flutter) mit Echtzeit-WebSocket-Synchronisierung.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — native Touch-UI für das eingebaute 7"-DSI-Touchscreen, direkt auf dem CM5 eingebettet.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — grafischer Desktop-URDF-Ersteller/-Editor, der fertige Modelle in STUDIOs eigenen Katalog überträgt.
- **[HYDRA-UMC-EDITOR-STL](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-STL)** — Desktop-STL-Modelleditor, der echte Teile im selben Modellkatalog transformiert/ersetzt/entfernt/hinzufügt, den auch HYDRA-UMC-EDITOR-URDF bearbeitet.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — Koordinationsschranke für AGV-/AMR-Flotten über einen VDA-5050-MQTT-Publisher (nur gegen eine emulierte Flotte getestet).
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — High-Level-Koordinator für CNC-Zellen mit GRBL-Status-/Steuerbyte-Zugriff (nur gegen einen Emulator getestet).
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — Koordinationsschranke für laufende/humanoide Droiden, mit einem Boston-Dynamics-Spot-Befehlssender (nur gegen einen Emulator getestet).
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — Koordinator für Laserzellen, liest 3 Schlüssel-/Gehäuse-/Verriegelungs-GPIO-Signale (nur gegen einen simulierten Chip getestet; kann keinen Laser scharfschalten oder auslösen).
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — sicherer High-Level-Koordinator für den Leiterplattenfluss von OpenPnP Pick-and-Place.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — sichere Koordinationsschranke für Moonraker/Klipper-3D-Drucker, mit echten gesicherten Job-Befehlen.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — Koordinator mit einem träge importierten rclpy-ROS-2-Transport (noch nicht gegen eine ROS-2-Installation ausgeführt).
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — Koordinationsschranke für kameraausgestattete UAVs, mit einem MAVLink-Befehlssender (nur gegen einen Emulator getestet).

*URTC-Werkzeugplattform*
- **[URTC](https://github.com/JuanenRac/URTC)** — Firmware für die physische Universal-Robot-Tool-Controller-Platine, 25+ Werkzeugprofile über CAN-Bus.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — Desktop-GUI-Flash-Tool für URTC-Platinen, CAN-OTA plus Full-Chip-SWD/JTAG.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — Desktop-Live-CAN-Bus-Diagnosetool für URTC-Platinen, ein Panel pro Werkzeugprofil.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — browserbasierte Alternative zu URTC-TESTER über die Web-Serial-API, ohne lokale Installation.
- **[URTC-GATEWAY](https://github.com/JuanenRac/URTC-GATEWAY)** — Gateway vor dem CAN-Bus von URTC: Liste erlaubter Kennungen, Ratenbegrenzung und Sitzungsschlüssel; Software auf dem Computer getestet, noch nicht an einem echten Bus.

*Vision-KI-Knoten (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — Integrationsknoten für die Hailo-8-Vision-Pipeline, mit einer echten stufenweisen Hardware-Bereitschaftsprüfung.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — echte Registry für kompilierte Modelle mit Hailo-Architektur-/Prüfsummen-Safe-Load-Verifizierung.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — echter GStreamer-Pipeline- + MediaMTX-Konfigurationsgenerator mit einer echten HailoRT-Integrationsschranke.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — Position-Based-Visual-Servoing-Korrekturgesetz mit Freigabe abhängig vom Zonenstatus; noch keine Posenschätzung per Kamera.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — v0-Logik für Zonenverletzung, Kalibrierungsaktualität und E-STOP-Anforderung, die Objektpositionen aus einer Datei nimmt; kein Detektor speist sie, und noch kein physischer E-STOP ist angeschlossen.

*Kognitiver KI-Knoten (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — Integrationsknoten für die Hailo-10-Cognitive-Pipeline (LLM-/VLA-/Sprach-Orchestrierung).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — echte Aktions-Token-Kodierung/-Dekodierung und Trajektoriengenerierung für ein Vision-Language-Action-Modell.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — echtes Sprach-Frontend (VAD + Intent-Parser) mit einem begrenzten, bestätigungsgesicherten Watch-Relay - einst als Benachrichtigungsoberfläche für Lieferung 6 dieses Projekts vorgesehen, erwies sich als ohne echten Vertrag für ausgehende Benachrichtigungen heute (siehe den FAHRPLAN-Abschnitt).
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — echte regelbasierte Aufgabenzerlegung und semantische Fehlerbehebung über MCU-Fehlercodes.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — echte, nur auf der Standardbibliothek basierende TF-IDF-Dokumentensuche über die eigenen Markdown-Dokumente dieses Ökosystems.
- **[HYDRA-UMC-LOCAL-TECHNICIAN](https://github.com/JuanenRac/HYDRA-UMC-LOCAL-TECHNICIAN)** — lokaler, richtlinien-gesteuerter KI-Wartungstechniker für das Ökosystem selbst - beobachtet, diagnostiziert und schlägt Korrekturen vor; die zwei höchsten Risikostufen sind absichtlich noch nicht implementiert.

*Orchestrierung & Schwarm*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — Integrationsknoten mit einem echten gRPC/Protobuf-Health-Report-Vertrag und einer Missions-Zustandsmaschine.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — echte prioritätsbasierte Job-Queue mit Deduplizierung, über eine echte HTTP-API.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — echter RRT-basierter 3D-Pfadplaner mit echter Hindernis-/Arbeitsraum-Kollisionsvalidierung.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — echte CRDT-LWW-Element-Map-Zustandssynchronisation, eigenschaftsgetestet auf Multi-Zellen-Konvergenz.

*Digitaler Zwilling & Simulation*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — Integrationsknoten für die Digital-Twin-Engine, mit einem echten Versionskompatibilitäts-Sync-Vertrag.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — Hardware-in-the-Loop-Router mit einer Software-Kollisionsverriegelung zwischen Simulation und echter Hardware (ohne echte Hardware getestet).
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — echte Vorwärtskinematik und Gelenkgrenzenvalidierung über eine echte URDF-Teilmenge.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — echter prozeduraler 2D-Szenengenerator mit YOLO/COCO-Annotationsexport.

*Daten & Analytik*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — echter sqlite3-gestützter Zeitreihenspeicher mit einer echten Ingest-/Abfrage-HTTP-API.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — echter FFT- + statistischer Basislinien-Anomaliedetektor mit Drift-Überwachung.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — echte OEE-/Verfügbarkeitsberechnung über den DATALAKE-Verlauf, mit reproduzierbarem CSV-Export.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — echte CAN/WebSocket-Ingestion-Pipeline in DATALAKE, mit Sequenz-Deduplizierung.

*Industrie-Gateway*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — Integrationsknoten, der zu Industrieprotokollen weiterleitet, mit einer echten Befehls-Allowlist-/Backpressure-Schicht.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — echter OPC-UA-Adressraum, verifiziert mit einer echten Binärprotokoll-Client-Session.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — echter MQTT-Broker mit optionaler Pro-Client-Authentifizierung und Topic-ACLs.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — echte MTConnect-`/probe`- und `/current`-XML-Endpunkte mit Degraded-Mode-Ausgabe.

*Ergänzende Tools*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — Smart-Summaries- und Anomaly-Highlighting-Panels über DATALAKE/ANOMALY-DETECTOR, mit einem ehrlichen statistischen Fallback.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — Flotten-CLI mit einem echten, stabilen Exit-Code-Vertrag, ein echter Live-Client der eigenen API von HYDRA-UMC-SERVER.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — WearOS-Begleit-App mit haptischen Alarmmustern und einem Sprach-Relay zum gekoppelten Telefon (noch nicht auf einer physischen Uhr ausgeführt).
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — externer Adapter-Fähigkeitskatalog, per Design nur GET.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — Firmware für ein Platinenmontagegestell mit echter Werkzeug-ID-Dekodierung und Smart-Idle-Vorheizlogik.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — Firmware plus ein echter Python-Vision-Begleiter für einen Thermal-/RGB-Inspektionswerkzeugkopf.

## 📚 Dokumentation

Hier steht mehr:

* **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — jeder Unterbefehl, seine Flags, und der Exit-Code-Vertrag.
* **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — die echte JSON-Form von `MaintenanceIncident`/`NodeSnapshot`.
* **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — der echte Vertrag, die Anbieter, die Zugangsdaten und die Sicherheitsgrenze von Lieferung 2.
* **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — der echte Vertrag, die vollständige stage/apply/verify/promote-Sequenz, und ein echter Betreiber-Ablauf für die Lieferungen 3-5.
* [Sicherheitsgrundlage des Ökosystems](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md)
* [Bedrohungsmodell des Ökosystems](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md)
* [Änderungsprotokoll dieses Repositorys](CHANGELOG.md)
* [Lizenz dieses Repositorys](LICENSE.md)

## 🤝 Mitwirken und Community

* Führe vor einem Pull Request `HYDRA_UMC_CI=1 py -3 tools/ci_validate.py` (oder `HYDRA_UMC_CI=1 python3 tools/ci_validate.py`) aus: Es muss `CI_VALIDATION=PASS` ausgeben. Führe dafür nicht `build.sh` oder `build.bat` aus; Bauen ist keine Prüfung.
* Die acht READMEs entstehen aus einer einzigen Quelle in HYDRA-UMC-DOCS; bearbeite sie nicht von Hand. Ändere die Quelle und schreibe sie mit `tools/make_readmes.py` neu.
* Behaupte in einer README nichts, was nicht gelaufen ist: Schreibe „simuliert“ oder „nicht auf Hardware erprobt“, wo das stimmt.
* Siehe [CONTRIBUTING.md](CONTRIBUTING.md), den [Verhaltenskodex](CODE_OF_CONDUCT.md), [SECURITY.md](SECURITY.md) und [SUPPORT.md](SUPPORT.md).

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LIZENZ

GPL-3.0-or-later - [LICENSE](LICENSE).
