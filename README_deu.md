<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | 🇩🇪 <b>Deutsch</b> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🔎 Schreibgeschützte Beobachtung von Wartungsvorfällen für das gesamte Ökosystem

<p align="center">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="stdlib-only core">
  <img src="https://img.shields.io/badge/Roles-Edge%20(CM5)%20%7C%20Control--plane-367BF5.svg" alt="Edge- und Control-Plane-Rollen">
</p>

> **Status: v0.0.8, Scaffolding - Lieferungen 1-5 von 6 (Beweis,
> Diagnose, von einer Person genehmigte Änderung, Canary-Deployment,
> Verifizierung).** Jeder Unterbefehl ist echt und Ende-zu-Ende getestet
> - `control diagnose` gegen einen simulierten KI-Anbieter (jeder echte
> Anbieter funktioniert, siehe
> [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)); `control deploy-canary` gegen
> ein echtes, lokales Wegwerf-Git-Repository (siehe
> [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)). Es wird nie
> etwas bereitgestellt, ohne dass zuvor eine ausdrückliche menschliche
> Genehmigung vorliegt. Lieferung 6 (Sprache/Benachrichtigungen) wurde
> untersucht und als wirklich blockiert befunden, nicht nur
> aufgeschoben - siehe den FAHRPLAN-Abschnitt unten. Siehe
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) für die genaue
> Befehlsoberfläche, die es heute gibt.

---

## 1. 🛠️ TECHNISCHER ÜBERBLICK

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
   einen KI-Anbieter (beliebig - Anthropic und OpenAI sind von Haus aus
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
Node: cm5-cell-3   Collected: 2026-09-06T10:15:03Z   Correlation: 7c2c...
Projects scanned: 27
Incidents: 1
  [CRITICAL] hydra-umc-server.service - systemd unit is not active

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
$ hydra-umc-ops-agent control approve proposal.json --approved-by "Juan Enrique"
$ hydra-umc-ops-agent control deploy-canary proposal.json \
    --live-root /home/pi/HYDRA-UMC/HYDRA-UMC-SERVER --build-test-command "bash build-test.sh"
$ hydra-umc-ops-agent control verify snapshot.json --incident-id 7c2c1e4a-...
```

Siehe [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) für den
vollständigen, echten Betreiber-Ablauf oben.

In dieser Lieferung gibt es weder eine Standard-/argumentlose Aufrufform
noch eine GUI - siehe
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) für die vollständige,
echte Befehlsoberfläche.

## 2. 🧱 ARCHITEKTUR UND DESIGN-ENTSCHEIDUNGEN

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
  Feld für Feld auf das eigene "CONTRATO MINIMO" der Audit festgelegt.**
  Siehe [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md). Eine
  spätere Lieferung, die mit einem echten KI-Anbieter oder
  Ticket-System spricht, sollte niemals zwischen zwei inkompatiblen
  Formen übersetzen müssen.
- **Die Diagnose ist von Natur aus anbieterunabhängig.**
  `diagnose_incident()` hängt nur von einem minimalen `AIProvider`-Protocol
  ab - ein echter, namentlich genannter KI-Anbieter wird nie im Kerncode
  festgelegt. Zwei echte Anbieter (Anthropic, OpenAI) werden als
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
- **Die Verifizierung führt DIESELBE echte Prüfung erneut aus, nie eine
  laxere.** `verify_incident_resolved()` ruft direkt die eigenen
  `check_http_health()`/`check_systemd_unit_health()` von Lieferung 1
  auf - es gibt nirgendwo in diesem Projekt eine zweite, unabhängig
  driftende Implementierung der Gesundheitsprüfung.
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
  Canary-Deployment-Stufe. Nur `control diagnose` braucht ein optionales
  Extra, und nur für den tatsächlich verwendeten Anbieter.

## 📂 VERZEICHNISSTRUKTUR

```
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/
│   ├── log_redaction.py    # Reine Geheimnis-Redaktion (KEY=VALUE, Bearer-Token, PEM-Blöcke)
│   ├── inventory.py        # Manifest-Scan + systemd-/HTTP-Health-Checks
│   ├── incident.py         # MaintenanceIncident-/IncidentBatch-Vertrag
│   ├── edge_agent.py       # Orchestriert das Obige zu einem einzigen NodeSnapshot
│   ├── control_plane.py    # Schreibgeschützter Snapshot-Lader + Text-Report-Renderer
│   ├── diagnosis.py        # Lieferung 2: anbieterunabhängiger KI-unterstützter Diagnosevorschlag
│   ├── change_proposal.py  # Lieferung 3: unveränderlicher, von einer Person genehmigter ChangeProposal-Lebenszyklus
│   ├── canary_deploy.py    # Lieferung 4: stage + apply + verify + promote, nur bei Genehmigung
│   ├── verification.py     # Lieferung 5: führt die echte Prüfung hinter einem Vorfall erneut aus
│   └── cli.py               # Einstiegspunkt der edge-/control-Unterbefehle für jede Lieferung oben
├── tests/                  # Echte Tests für alle 10 Module, inkl. eines lokalen http.server-Fixtures, eines simulierten KI-Anbieters und eines echten Wegwerf-Git-Repositorys für das Canary-Deployment
├── docs/
│   ├── CLI_REFERENCE.md     # Jeder Unterbefehl, seine Flags, der Exit-Code-Vertrag
│   ├── INCIDENT_CONTRACT.md # Die echte JSON-Form von MaintenanceIncident/NodeSnapshot
│   ├── DIAGNOSIS.md         # Der Vertrag, die Anbieter und die Sicherheitsgrenze von Lieferung 2
│   └── CHANGE_LIFECYCLE.md  # Der Vertrag und die Sicherheitsgrenze der Lieferungen 3-5
├── images/                 # Medien und App-Icons
├── tools/
│   ├── build_test.py        # Build-/Kompilierungsprüfung ohne Versionierung
│   └── ci_validate.py       # Manifest-/CHANGELOG-/Doku-Validierung, die von der CI verwendet wird
├── build.sh / build.bat     # venv + editierbare Installation + Compile-Check + Tests
├── build-test.sh / .bat     # Nur Build-Validierung, ohne etwas zu verändern
├── run.sh / run.bat         # Echte edge-collect + control-show-Demo (ohne Argumente), oder leitet einen echten CLI-Befehl weiter
├── bump_version.py          # "Kilometerzähler"-Inkrement des Ökosystems (pyproject.toml + __init__.py)
└── bump_manifest_version.py # Synchronisiert die Version von hydra-umc.project.json mit der nativen (--sync)
```

## ⚙️ BUILD UND AUSFÜHRUNG

```bash
chmod +x build.sh   # einmalig
./build.sh          # erstellt .venv, pip install -e ".[dev]", Compile-Check + Tests
./run.sh                                          # echte Demo: edge collect gegen diesen
                                                   # GitHub-Workspace, dann control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # oder .[ai-openai] - nur für control diagnose nötig
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name NAME --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control approve proposal.json --approved-by "Ihr Name"
./run.sh control deploy-canary proposal.json --live-root PFAD --build-test-command "bash build-test.sh"
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
- `control deploy-canary` meldet `promoted: false`: lesen Sie
  `buildOutput` im Ergebnis-JSON - der Staging-Build ist wirklich
  fehlgeschlagen, und der echte Checkout wurde nie angefasst. Siehe
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).

## 🚀 FAHRPLAN

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
- Ein Rollback-Befehl für ein bereits befördertes Canary, das sich
  später zur Laufzeit als falsch herausstellt - das `.backup-<id>`-
  Verzeichnis ist echt und wird aufbewahrt, aber es heute
  wiederherzustellen ist ein manueller Schritt (siehe
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)).

## 🔗 Verwandte Projekte

Dieses Projekt ist Teil des HYDRA-UMC-Robotik-Ökosystems desselben Autors (JuanenRac / Electro Hobby 3D). Gut zu wissen, da eine Anfrage eigentlich eines dieser Projekte betreffen könnte statt dieses Repositorys.

**Direkt verwandt**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — erkennt, installiert und aktualisiert jeden Checkout des Ökosystems; ein Canary-Deployment der Lieferung 4 wendet eine genehmigte Änderung über den eigenen, bereits existierenden atomar-durch-Verifizierung-Update-Pfad dieses Projekts an, statt einer zweiten Implementierung.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — ein weiterer "Ecosystem Operations"-Verwandter: baut ein neues, vollständig aktuelles CM5-Image, statt ein bereits laufendes zu beobachten.
- **[HYDRA-UMC-DEV-SERVER](https://github.com/JuanenRac/HYDRA-UMC-DEV-SERVER)** — reproduzierbarer Entwicklungshost, der Kandidaten baut und seine dauerhafte Aufgaben-Warteschlange mit dem Vorfall-Lebenszyklus dieses Projekts abstimmt; er genehmigt seine eigenen Aufgaben nie.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — ein echter gRPC-basierter Flotten-Health-Watchdog mit eigenem Retry/Backoff und Identitäts-Mismatch-Erkennung - ein verwandtes, aber eigenständiges Thema (Live-Gesundheit von Flottenknoten via gRPC) gegenüber der eigenen Manifest-/systemd-/HTTP-Beweissammlung und dem Vorfall-Lebenszyklus dieses Projekts.

**Ebenfalls Teil des Ökosystems**

*Kern-Hardware & Plattform*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — das physische Motherboard des Roboterarms: CM5-Host + Dual-Core-STM32H745, koordiniert bis zu 8 Werkzeugarme über CAN-OTA/SPI-OTA.
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — reproduzierbare Raspberry-Pi-OS-Produktschicht für den CM5: schreibgeschützter Agent, validierte Konfiguration/Profile, WiFi-Ersteinrichtung.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — der gemeinsame JSON-Schema-Vertrag und die Sicherheitsschranke, gegen die jede Bridge ihre Befehle validiert.

*Kern-Backend & Clients*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — das reale Headless-Backend (REST/WebSocket), mit dem jeder Steuerungsclient tatsächlich spricht.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — Web-Steuerungs-Dashboard mit Echtzeit-3D-Visualisierung mehrerer Roboter.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — Desktop-Schwarmleitstand (PySide6) für mehrere Server gleichzeitig.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — native Android-Steuerungs-App mit biometrischem Login und einer gekoppelten Wear-OS-Begleit-App.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — iOS/iPadOS-Steuerungs-App (Flutter) mit Echtzeit-WebSocket-Synchronisierung.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — native Touch-UI für das eingebaute 7"-DSI-Touchscreen, direkt auf dem CM5 eingebettet.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — grafischer Desktop-URDF-Ersteller/-Editor, der fertige Modelle in STUDIOs eigenen Katalog überträgt.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — Koordinationsschranke für AGV-/AMR-Flotten über einen echten VDA-5050-MQTT-Publisher.
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — High-Level-Koordinator für CNC-Zellen mit echtem GRBL-Status-/Steuerbyte-Zugriff.
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — Koordinationsschranke für laufende/humanoide Droiden, mit einem echten Boston-Dynamics-Spot-Befehlssender.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — Sicherheitskoordinator für Laserzellen, liest 3 echte Schlüssel-/Gehäuse-/Verriegelungs-GPIO-Sicherungen.
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — sicherer High-Level-Koordinator für den Leiterplattenfluss von OpenPnP Pick-and-Place.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — sichere Koordinationsschranke für Moonraker/Klipper-3D-Drucker, mit echten gesicherten Job-Befehlen.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — Sicherheitskoordinator mit einem echten, träge importierten rclpy-ROS-2-Transport.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — Koordinationsschranke für kameraausgestattete UAVs, mit einem echten MAVLink-Befehlssender.

*URTC-Werkzeugplattform*
- **[URTC](https://github.com/JuanenRac/URTC)** — Firmware für die physische Universal-Robot-Tool-Controller-Platine, 25+ Werkzeugprofile über CAN-Bus.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — Desktop-GUI-Flash-Tool für URTC-Platinen, CAN-OTA plus Full-Chip-SWD/JTAG.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — Desktop-Live-CAN-Bus-Diagnosetool für URTC-Platinen, ein Panel pro Werkzeugprofil.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — browserbasierte Alternative zu URTC-TESTER über die Web-Serial-API, ohne lokale Installation.

*Vision-KI-Knoten (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — Integrationsknoten für die Hailo-8-Vision-Pipeline, mit einer echten stufenweisen Hardware-Bereitschaftsprüfung.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — echte Registry für kompilierte Modelle mit Hailo-Architektur-/Prüfsummen-Safe-Load-Verifizierung.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — echter GStreamer-Pipeline- + MediaMTX-Konfigurationsgenerator mit einer echten HailoRT-Integrationsschranke.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — echtes Position-Based-Visual-Servoing-Korrekturgesetz, sicherheitsgesteuert nach vorgelagertem Zonenstatus.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — echte Zonenverletzungsprüfung und E-STOP-Anforderung, mit erzwungener Kalibrierungsaktualität.

*Kognitiver KI-Knoten (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — Integrationsknoten für die Hailo-10-Cognitive-Pipeline (LLM-/VLA-/Sprach-Orchestrierung).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — echte Aktions-Token-Kodierung/-Dekodierung und Trajektoriengenerierung für ein Vision-Language-Action-Modell.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — echtes Sprach-Frontend (VAD + Intent-Parser) mit einem begrenzten, bestätigungsgesicherten Watch-Relay - einst als Benachrichtigungsoberfläche für Lieferung 6 dieses Projekts vorgesehen, erwies sich als ohne echten Vertrag für ausgehende Benachrichtigungen heute (siehe den FAHRPLAN-Abschnitt).
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — echte regelbasierte Aufgabenzerlegung und semantische Fehlerbehebung über MCU-Fehlercodes.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — echte, nur auf der Standardbibliothek basierende TF-IDF-Dokumentensuche über die eigenen Markdown-Dokumente dieses Ökosystems.

*Orchestrierung & Schwarm*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — Integrationsknoten mit einem echten gRPC/Protobuf-Health-Report-Vertrag und einer Missions-Zustandsmaschine.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — echte prioritätsbasierte Job-Queue mit Deduplizierung, über eine echte HTTP-API.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — echter RRT-basierter 3D-Pfadplaner mit echter Hindernis-/Arbeitsraum-Kollisionsvalidierung.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — echte CRDT-LWW-Element-Map-Zustandssynchronisation, eigenschaftsgetestet auf Multi-Zellen-Konvergenz.

*Digitaler Zwilling & Simulation*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — Integrationsknoten für die Digital-Twin-Engine, mit einem echten Versionskompatibilitäts-Sync-Vertrag.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — echte Hardware-in-the-Loop-Sicherheitsverriegelung, die Befehle zwischen Simulation und echter Hardware routet.
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
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — WearOS-Begleit-App mit echten haptischen Alarmen und einem Sprach-Relay zum gekoppelten Telefon.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — Firmware für ein Platinenmontagegestell mit echter Werkzeug-ID-Dekodierung und Smart-Idle-Vorheizlogik.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — Firmware plus ein echter Python-Vision-Begleiter für einen Thermal-/RGB-Inspektionswerkzeugkopf.

---

## 📚 Dokumentation & Community

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — jeder Unterbefehl, seine Flags, und der Exit-Code-Vertrag.
- **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — die echte JSON-Form von `MaintenanceIncident`/`NodeSnapshot`.
- **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — der echte Vertrag, die Anbieter, die Zugangsdaten und die Sicherheitsgrenze von Lieferung 2.
- **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — der echte Vertrag, die vollständige stage/apply/verify/promote-Sequenz, und ein echter Betreiber-Ablauf für die Lieferungen 3-5.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Technologie-Stack und Coding-Richtlinien für einen Pull Request.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — die in dieser Community erwarteten Verhaltensstandards.
- **[SECURITY.md](SECURITY.md)** — wie man eine Schwachstelle meldet, und die echten Sicherheitsschwerpunkte dieses Projekts.
- **[SUPPORT.md](SUPPORT.md)** — wo man Fragen stellt und Fehler meldet.

## 👤 AUTOR
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LIZENZ

GPL-3.0 (Software) / CC BY-SA 4.0 (Dokumentation) - siehe [LICENSE.md](LICENSE.md).
