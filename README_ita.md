<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | 🇮🇹 <b>Italiano</b> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🔎 Osservabilità di sola lettura degli incidenti di manutenzione per l'intero ecosistema

<p align="center">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="stdlib-only core">
  <img src="https://img.shields.io/badge/Roles-Edge%20(CM5)%20%7C%20Control--plane-367BF5.svg" alt="Ruoli edge e control-plane">
</p>

> **Stato: v0.0.8, scaffolding - Consegne 1-5 di 6 (evidenza, diagnosi,
> cambiamento approvato da una persona, distribuzione canary,
> verifica).** Ogni sottocomando è reale e testato end to end - `control
> diagnose` contro un provider di IA simulato (qualsiasi provider reale
> funziona, vedi [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)); `control
> deploy-canary` contro un vero repository git locale e usa e getta
> (vedi [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)). Nulla
> viene mai distribuito senza una previa approvazione umana esplicita.
> La Consegna 6 (voce/notifiche) è stata investigata e si è rivelata
> davvero bloccata, non semplicemente rimandata - vedi la sezione
> TABELLA DI MARCIA più sotto. Vedi
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) per la superficie di
> comandi esatta che esiste oggi.

---

## 1. 🛠️ PANORAMICA TECNICA

HYDRA-UMC-OPS-AGENT è il coordinatore degli incidenti di manutenzione
dell'ecosistema HYDRA-UMC/URTC. È proprietario di un unico ciclo di vita
reale - **evidenza → diagnosi → cambiamento approvato da una persona →
distribuzione canary via HYDRA-UMC-UPDATER → verifica** - senza
reimplementare l'inferenza, gli aggiornamenti o la logica di sicurezza
dell'MCU che già esistono altrove nell'ecosistema. Questo progetto
spedisce ormai cinque delle sei fasi di quel ciclo di vita:
**l'evidenza**, **la diagnosi**, **il cambiamento approvato da una
persona**, **la distribuzione canary** e **la verifica**.

Due ruoli, un solo pacchetto, ancora nessun trasporto di rete tra loro:

1. **Ruolo edge** (`edge collect`) - viene eseguito direttamente sulla
   macchina osservata (una vera cella CM5, o la propria workstation di
   uno sviluppatore). Scansiona ogni checkout fratello alla ricerca del
   proprio `hydra-umc.project.json`, controlla opzionalmente una o più
   unità systemd ed endpoint HTTP di salute, e deriva un vero
   `MaintenanceIncident` per ogni problema REALE trovato - una scansione
   pulita produce zero incidenti, mai un "tutto OK" sintetico. Tutti gli
   incidenti della stessa esecuzione condividono un unico ID di
   correlazione.
2. **Ruolo control-plane** (`control show`) - viene eseguito su una
   macchina di sviluppo e renderizza un file di snapshot salvato, in
   sola lettura: inventario dei progetti, risultati dei controlli di
   salute, e tutti gli incidenti ordinati dal più al meno grave. Non
   modifica mai il file che legge, e questa consegna non "risolve" né
   riconosce alcun incidente nemmeno da qui.
3. **Diagnosi** (`control diagnose`) - viene eseguito anch'esso sul
   ruolo control-plane. Invia un incidente già redatto a un provider di
   IA (qualsiasi provider - Anthropic e OpenAI sono integrati di serie,
   vedi [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)) e riceve indietro una
   spiegazione di causa radice proposta in testo semplice - un
   suggerimento perché lo legga una persona, mai una decisione.
4. **Cambiamento approvato da una persona** (`control propose` /
   `approve` / `reject`) - un `ChangeProposal` reale e immutabile (un
   diff unificato, una descrizione, una motivazione) che passa da
   `pending` a `approved`/`rejected` ESATTAMENTE UNA VOLTA, sempre
   attribuito a una persona reale con nome. Vedi
   [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
5. **Distribuzione canary** (`control deploy-canary`) - si rifiuta di
   essere eseguito contro qualsiasi cosa non sia una proposta
   `approved`. Applica il diff a un clone di staging indipendente,
   esegue lì il vero comando di build-test del progetto target, e
   promuove (conservando il checkout precedente come vera copia di
   backup) solo se questo passa - il checkout reale non viene mai
   toccato altrimenti.
6. **Verifica** (`control verify`) - riesegue esattamente lo stesso
   controllo reale che ha originariamente prodotto un incidente,
   usando le funzioni proprie della Consegna 1, per confermare che sia
   davvero risolto.

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

Vedi [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) per il flusso
operativo reale e completo sopra riportato.

In questa consegna non esiste nessuna invocazione predefinita/senza
argomenti né alcuna GUI - vedi
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) per la superficie di
comandi completa e reale.

## 2. 🧱 ARCHITETTURA E DECISIONI DI DESIGN

- **Un incidente viene derivato, mai dichiarato.** I metodi `add_*` di
  `IncidentBatch` restituiscono `None` quando ciò che hanno esaminato
  era effettivamente sano. Non esiste alcun percorso di codice che
  fabbrichi un incidente da un'osservazione pulita, né alcuno che
  scarti silenziosamente uno reale.
- **Un confine di protocollo si degrada onestamente, non indovina mai.**
  `check_systemd_unit_health()` solleva un `SystemdUnavailableError`
  dedicato nell'istante in cui `systemctl` non è nel `PATH` - il che
  accade sempre su questa macchina di sviluppo, e su qualsiasi host
  senza systemd - invece di riportare uno stato "inactive" inventato.
  `check_http_health()` mantiene un vero fallimento di rete
  (`status_code is None`) distinguibile da una risposta HTTP reale ma
  non sana.
- **La redazione è il pezzo di codice più critico per la sicurezza qui.**
  `log_redaction.py` è una trasformazione di testo pura e senza
  dipendenze, coperta dai propri test prima che qualsiasi altra cosa la
  consumi. Una corrispondenza del nome di una chiave deve cercare il
  nome del segreto come sottostringa di un vero token identificativo
  (`DB_PASSWORD`, `api-key`), non come una parola delimitata da `\b` -
  `_` è un carattere di parola in un'espressione regolare, quindi un
  ingenuo `\bpassword\b` non corrisponde mai a `DB_PASSWORD`.
  `MaintenanceIncident.to_dict()` riesegue `redact_secrets()` su
  `symptom` al momento della serializzazione, anche se chi chiama l'ha
  già redatto a monte - difesa in profondità per il campo con più
  probabilità di contenere una riga di log copiata e incollata.
- **Il contratto `MaintenanceIncident`/`NodeSnapshot` è fissato
  intenzionalmente, campo per campo, al "CONTRATO MINIMO" della stessa
  audit.** Vedi [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md).
  Una consegna futura che parla con un vero provider di IA o un sistema
  di ticket non dovrebbe mai dover tradurre tra due forme incompatibili.
- **La diagnosi è indipendente dal provider per design.**
  `diagnose_incident()` dipende solo da un Protocol minimo `AIProvider`
  - nessun provider di IA reale è mai fissato nel codice. Due provider
  reali (Anthropic, OpenAI) sono forniti come extra opzionali; chi
  chiama può passare qualsiasi altro oggetto che implementi lo stesso
  contratto a un solo metodo.
- **Una distribuzione canary non tocca mai il checkout reale finché un
  vero build non ha già dimostrato che il cambiamento funziona.**
  `deploy_canary()` si rifiuta di essere eseguito a meno che lo `status`
  della proposta data non sia già `approved`, poi mette in staging il
  diff in un clone locale indipendente e promuove (scambio a due
  rinomine, checkout precedente conservato come vera copia di backup)
  solo se il proprio comando di build-test di quel progetto termina
  davvero con codice `0` - lo stesso schema
  atomico-per-verifica che il proprio `install.py` di
  HYDRA-UMC-UPDATER usa già.
- **Una proposta viene decisa esattamente una volta.**
  `approve_change()`/`reject_change()` sollevano ciascuna
  `InvalidTransitionError` su qualsiasi cosa non sia una proposta
  `pending` - una seconda decisione non sovrascrive mai silenziosamente
  la prima, e ogni decisione è attribuita a un nome reale, non vuoto.
- **La verifica riesegue LO STESSO controllo reale, mai uno più
  permissivo.** `verify_incident_resolved()` chiama direttamente le
  proprie `check_http_health()`/`check_systemd_unit_health()` della
  Consegna 1 - non esiste da nessuna parte in questo progetto una
  seconda implementazione di controllo di salute, indipendente e
  soggetta a deriva.
- **La Consegna 6 è bloccata, non semplicemente saltata.** Il proprio
  contratto reale di HYDRA-UMC-VOICE-UI (`gateway.py`) è un gateway
  limitato, in INGRESSO, da trascrizione a intento, senza alcuna vera
  superficie di notifica in uscita oggi - inventarne una qui avrebbe
  significato fabbricare un'integrazione che non esiste, cosa che il
  proprio standard anti-fabbricazione di questo progetto non permette.
  Vedi la sezione TABELLA DI MARCIA più sotto.
- **Solo libreria standard per il nucleo.** `edge collect`/`control
  show`/`control propose`/`control approve`/`control reject`/`control
  verify` non necessitano di alcuna dipendenza - `urllib.request` per il
  controllo HTTP, `subprocess`/`shutil.which` per quello di systemd,
  `git` (un vero binario esterno, non un pacchetto Python) per la fase
  di distribuzione canary. Solo `control diagnose` necessita di un
  extra opzionale, e solo per il provider effettivamente usato.

## 📂 STRUTTURA DELLE DIRECTORY

```
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/
│   ├── log_redaction.py    # Redazione pura di segreti (KEY=VALUE, token Bearer, blocchi PEM)
│   ├── inventory.py        # Scansione manifesti + controlli di salute systemd/HTTP
│   ├── incident.py         # Contratto MaintenanceIncident / IncidentBatch
│   ├── edge_agent.py       # Orchestra quanto sopra in un unico NodeSnapshot
│   ├── control_plane.py    # Caricatore di snapshot in sola lettura + renderizzatore di report testuale
│   ├── diagnosis.py        # Consegna 2: suggerimento di diagnosi assistita da IA, indipendente dal provider
│   ├── change_proposal.py  # Consegna 3: ciclo di vita immutabile di ChangeProposal, approvato da una persona
│   ├── canary_deploy.py    # Consegna 4: stage + apply + verify + promote, solo su approvazione
│   ├── verification.py     # Consegna 5: riesegue il controllo reale dietro un incidente
│   └── cli.py               # Punto di ingresso dei sottocomandi edge/control per ogni consegna sopra
├── tests/                  # Test reali per tutti e 10 i moduli, incl. un fixture locale http.server, un provider di IA simulato e un vero repository git usa e getta per la distribuzione canary
├── docs/
│   ├── CLI_REFERENCE.md     # Ogni sottocomando, i suoi flag, il contratto dei codici di uscita
│   ├── INCIDENT_CONTRACT.md # La vera forma JSON di MaintenanceIncident/NodeSnapshot
│   ├── DIAGNOSIS.md         # Il contratto, i provider e il confine di sicurezza propri della Consegna 2
│   └── CHANGE_LIFECYCLE.md  # Il contratto e il confine di sicurezza propri delle Consegne 3-5
├── images/                 # Media e icone dell'app
├── tools/
│   ├── build_test.py        # Controllo di build/compilazione senza versionamento
│   └── ci_validate.py       # Validazione manifesto/CHANGELOG/docs usata dalla CI
├── build.sh / build.bat     # venv + installazione editabile + compile-check + test
├── build-test.sh / .bat     # Solo validazione di build, senza modificare nulla
├── run.sh / run.bat         # Demo reale edge collect + control show (senza argomenti), oppure inoltra un vero comando CLI
├── bump_version.py          # Incremento tipo "odometro" dell'ecosistema (pyproject.toml + __init__.py)
└── bump_manifest_version.py # Sincronizza la versione di hydra-umc.project.json con quella nativa (--sync)
```

## ⚙️ COMPILAZIONE ED ESECUZIONE

```bash
chmod +x build.sh   # una tantum
./build.sh          # crea .venv, pip install -e ".[dev]", compile-check + test
./run.sh                                          # demo reale: edge collect contro questo
                                                   # workspace GitHub, poi control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # oppure .[ai-openai] - necessario solo per control diagnose
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name NOME --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control approve proposal.json --approved-by "Il Tuo Nome"
./run.sh control deploy-canary proposal.json --live-root PERCORSO --build-test-command "bash build-test.sh"
./run.sh control verify snapshot.json --incident-id <id>
```

Su Windows: `build.bat`, poi `run.bat` (stessa demo se chiamato senza
argomenti) / `run.bat edge collect ...` / uno qualsiasi dei
sottocomandi `control ...` sopra. `build-test.sh`/`.bat` esegue lo
stesso controllo di compilazione (solo sintassi Python), senza
modificare nulla, che la propria CI di questo progetto esegue - NON
esegue da solo la suite di test; la CI esegue `pytest` come passo
separato, successivo. Esegui `./build.sh`/`build.bat` (o `pytest
tests/` direttamente) per la suite di test locale completa.

**Risoluzione dei problemi**

- `edge collect` riporta `systemdAvailable: false` a ogni esecuzione:
  questo host non ha davvero `systemctl` nel `PATH` (ogni macchina di
  sviluppo non-Linux, e alcuni container Linux minimi) - è la
  degradazione onesta attesa, non un bug. Vedi
  [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).
- `control show` fallisce con `ERROR: ...`: il file di snapshot non
  esiste, non è JSON valido, o non è un vero oggetto snapshot - riesegui
  `edge collect` e controlla il proprio percorso `--out`.
- `control diagnose` fallisce con `ERROR: the optional '<provider>'
  package is not installed`: esegui `pip install -e ".[ai-anthropic]"`
  oppure `".[ai-openai]"`, secondo `--provider`.
- `control diagnose` fallisce con `ERROR: no ... API key available`:
  imposta `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` prima di eseguirlo.
- `control deploy-canary` fallisce con `ERROR: refusing to deploy ...`:
  la proposta non è ancora `approved` - esegui prima `control approve`.
- `control deploy-canary` riporta `promoted: false`: leggi
  `buildOutput` nel JSON di risultato - il build di staging è
  davvero fallito, e il checkout reale non è mai stato toccato. Vedi
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).

## 🚀 TABELLA DI MARCIA

Le Consegne 1-5 (questa versione) spediscono **evidenza**, **diagnosi**,
**cambiamento approvato da una persona**, **distribuzione canary** e
**verifica** - il vero ciclo di vita già nominato nel proprio manifesto
e CHANGELOG di questo progetto. Cosa resta:

- **Consegna 6 - Integrazione voce/notifiche - davvero BLOCCATA, non
  semplicemente rimandata.** Il piano era mostrare un incidente critico,
  o un canary completato, tramite HYDRA-UMC-VOICE-UI. L'indagine reale
  del suo proprio codice (`gateway.py`) ha trovato che è un gateway
  limitato, in INGRESSO, da trascrizione a intento (un Watch invia
  testo, riceve una risposta), senza alcuna vera superficie di notifica
  in uscita oggi. Costruirne una qui avrebbe significato inventare un
  punto di integrazione che VOICE-UI stesso non ha - il proprio standard
  anti-fabbricazione di questo progetto non lo permette. Da rivisitare
  quando VOICE-UI (o un successore) svilupperà una vera capacità
  propria di "annuncio in ingresso dell'assistente".
- Un vero trasporto tra i ruoli edge e control-plane (oggi, spostare un
  file di snapshot tra i due è un passaggio manuale).
- Un comando di rollback per un canary già promosso che in seguito si
  rivela sbagliato in produzione - la directory `.backup-<id>` è reale
  ed è conservata, ma ripristinarla oggi è un passaggio manuale (vedi
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)).

## 🔗 Progetti Correlati

Questo progetto fa parte dell'ecosistema robotico HYDRA-UMC dello stesso autore (JuanenRac / Electro Hobby 3D). Vale la pena conoscerlo, poiché una richiesta potrebbe in realtà riguardare uno di questi invece di questo repository.

**Direttamente Correlati**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — rileva, installa e aggiorna ogni checkout dell'ecosistema; una distribuzione canary della Consegna 4 applica un cambiamento approvato attraverso la propria via di aggiornamento atomica-per-verifica già esistente di questo progetto, invece di una seconda implementazione.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — un altro fratello "Ecosystem Operations": costruisce un'immagine CM5 nuova e completamente aggiornata, invece di osservarne una già in esecuzione.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — un vero watchdog di salute della flotta basato su gRPC, con il proprio retry/backoff e rilevamento di discrepanza d'identità - un argomento correlato ma distinto (salute dei nodi di flotta dal vivo via gRPC) dalla propria raccolta di evidenza tramite manifesto/systemd/HTTP e dal ciclo di vita degli incidenti di questo progetto.

**Fa Anche Parte dell'Ecosistema**

*Hardware e Piattaforma di Base*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — la scheda madre fisica del braccio robotico: host CM5 + coprocessore STM32H745 dual-core, che coordina fino a 8 bracci utensile via CAN-OTA/SPI-OTA.
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — livello prodotto riproducibile su Raspberry Pi OS per il CM5: agente in sola lettura, config/profili validati, provisioning WiFi al primo contatto.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — il contratto JSON-Schema condiviso e la barriera di sicurezza contro cui ogni bridge valida i propri comandi.

*Backend Centrale e Client*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — il vero backend headless (REST/WebSocket) con cui parla davvero ogni client di controllo.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — dashboard di controllo web con visualizzazione 3D multi-robot in tempo reale.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — centro di comando sciame desktop (PySide6) per più server contemporaneamente.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — app di controllo nativa per Android con login biometrico e un companion Wear OS abbinato.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — app di controllo per iOS/iPadOS (Flutter) con sincronizzazione WebSocket in tempo reale.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — interfaccia touch nativa per il touchscreen DSI da 7" a bordo, incorporata direttamente nel CM5.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — creatore/editor grafico desktop di URDF che invia i modelli finiti al catalogo di STUDIO.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — barriera di coordinamento per flotte AGV/AMR tramite un publisher MQTT VDA 5050 reale.
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — coordinatore ad alto livello per celle CNC con accesso reale a stato/byte di controllo GRBL.
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — barriera di coordinamento per droidi con zampe/umanoidi, con un vero mittente di comandi per Boston Dynamics Spot.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — coordinatore di sicurezza per celle laser che legge 3 salvaguardie GPIO reali di chiave/involucro/interblocco.
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — coordinatore ad alto livello sicuro per il flusso schede del pick-and-place OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — barriera di coordinamento sicura per stampanti 3D Moonraker/Klipper, con comandi di lavoro reali e controllati.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — coordinatore di sicurezza con un vero trasporto ROS 2 rclpy, importato in modo lazy.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — barriera di coordinamento per UAV dotati di fotocamera, con un vero mittente di comandi MAVLink.

*Piattaforma Strumenti URTC*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware per la scheda fisica dell'Universal Robot Tool Controller, oltre 25 profili utensile su bus CAN.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — strumento desktop con GUI per il flashing delle schede URTC, CAN-OTA più SWD/JTAG a chip intero.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — strumento desktop di diagnostica CAN-bus dal vivo per schede URTC, un pannello per profilo utensile.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — alternativa basata su browser a URTC-TESTER tramite la Web Serial API, senza installazione locale.

*Nodo IA Visione (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — hub di integrazione per la pipeline di visione Hailo-8, con un vero controllo di prontezza hardware per fase.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — registro reale di modelli compilati con verifica di caricamento sicuro per architettura Hailo/checksum.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — generatore reale di pipeline GStreamer + config MediaMTX, con una vera barriera di integrazione HailoRT.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — vera legge di correzione Position-Based Visual Servoing, con cancello di sicurezza sullo stato di zona a monte.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — vero controllo di violazione zona e richiesta E-STOP, con imposizione della freschezza di calibrazione.

*Nodo IA Cognitivo (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — hub di integrazione per la pipeline cognitiva Hailo-10 (orchestrazione LLM/VLA/voce).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — vera codifica/decodifica di token d'azione e generazione di traiettoria per un modello Vision-Language-Action.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — vero front-end vocale (VAD + parser di intenti) con un relay verso Watch limitato e soggetto a conferma - considerato un tempo come la superficie di notifica della Consegna 6 di questo progetto, si è rivelato privo di un vero contratto di notifica in uscita oggi (vedi la sezione TABELLA DI MARCIA).
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — vera scomposizione dei task basata su regole e recupero semantico degli errori sui codici errore MCU.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — vera ricerca documentale TF-IDF (solo libreria standard) sui documenti Markdown di questo ecosistema.

*Orchestrazione e Sciame*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — hub di integrazione con un vero contratto di health-report gRPC/Protobuf e una macchina a stati di missione.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — vera coda di lavori basata su priorità con deduplicazione, su una vera API HTTP.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — vero pianificatore di percorsi 3D basato su RRT, con vera validazione delle collisioni ostacolo/spazio di lavoro.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — vera sincronizzazione di stato CRDT LWW-Element-Map, con property test per la convergenza multi-cella.

*Gemello Digitale e Simulazione*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — hub di integrazione per il motore di gemello digitale, con un vero contratto di sincronizzazione per compatibilità di versione.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — vero interblocco di sicurezza hardware-in-the-loop che instrada i comandi tra simulazione e hardware reale.
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — vera cinematica diretta e validazione dei limiti articolari su un vero sottoinsieme URDF.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — vero generatore procedurale di scene 2D con esportazione di annotazioni YOLO/COCO.

*Dati e Analisi*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — vero archivio di serie temporali basato su sqlite3, con una vera API HTTP di ingestione/query.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — vero rilevatore di anomalie FFT + baseline statistica, con monitoraggio della deriva.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — vero calcolo OEE/disponibilità sullo storico di DATALAKE, con esportazione CSV riproducibile.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — vera pipeline di ingestione CAN/WebSocket verso DATALAKE, con deduplicazione per sequenza.

*Gateway Industriale*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — hub di integrazione che inoltra ai protocolli industriali, con un vero livello di allowlist dei comandi/backpressure.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — vero spazio di indirizzi OPC-UA, verificato con una vera sessione client del protocollo binario.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — vero broker MQTT con autenticazione opzionale per client e ACL sui topic.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — veri endpoint XML `/probe` e `/current` di MTConnect, con output in modalità degradata.

*Strumenti Complementari*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — pannelli Smart Summaries e Anomaly Highlighting su DATALAKE/ANOMALY-DETECTOR, con un fallback statistico onesto.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — CLI di flotta con un vero e stabile contratto di exit-code, un client live reale della stessa API di HYDRA-UMC-SERVER.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — app companion WearOS con avvisi aptici reali e un relay vocale verso il telefono abbinato.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware per un rack di montaggio schede con decodifica reale dell'ID utensile e logica di preriscaldamento Smart Idle.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware più un vero companion di visione Python per una testa utensile di ispezione termica/RGB.

---

## 📚 Documentazione e Comunità

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — ogni sottocomando, i suoi flag, e il contratto dei codici di uscita.
- **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — la vera forma JSON di `MaintenanceIncident`/`NodeSnapshot`.
- **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — il contratto reale, i provider, le credenziali e il confine di sicurezza propri della Consegna 2.
- **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — il contratto reale, la sequenza completa stage/apply/verify/promote, e un vero flusso operativo per le Consegne 3-5.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — stack tecnologico e linee guida di codifica per una pull request.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — gli standard di comportamento attesi in questa comunità.
- **[SECURITY.md](SECURITY.md)** — come segnalare una vulnerabilità, e le reali aree di attenzione sulla sicurezza di questo progetto.
- **[SUPPORT.md](SUPPORT.md)** — dove porre domande e segnalare bug.

## 👤 AUTORE
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LICENZA

GPL-3.0 (software) / CC BY-SA 4.0 (documentazione) - vedi [LICENSE.md](LICENSE.md).
