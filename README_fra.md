<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | 🇫🇷 <b>Français</b> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🔎 Observabilité en lecture seule des incidents de maintenance pour tout l'écosystème

<p align="center">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="stdlib-only core">
  <img src="https://img.shields.io/badge/Roles-Edge%20(CM5)%20%7C%20Control--plane-367BF5.svg" alt="Rôles edge et control-plane">
</p>

> **État : v0.0.6, scaffolding - Livraisons 1-5 sur 6 (preuve,
> diagnostic, changement approuvé par une personne, déploiement canari,
> vérification).** Chaque sous-commande est réelle et testée de bout en
> bout - `control diagnose` contre un fournisseur d'IA simulé (tout
> fournisseur réel fonctionne, voir
> [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)) ; `control deploy-canary`
> contre un vrai dépôt git local jetable (voir
> [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)). Rien n'est
> jamais déployé sans une approbation humaine explicite préalable. La
> Livraison 6 (voix/notifications) a été étudiée et s'est révélée
> vraiment bloquée, pas simplement reportée - voir la section FEUILLE DE
> ROUTE ci-dessous. Voir
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) pour la surface de
> commandes exacte qui existe aujourd'hui.

---

## 1. 🛠️ VUE TECHNIQUE

HYDRA-UMC-OPS-AGENT est le coordinateur d'incidents de maintenance de
l'écosystème HYDRA-UMC/URTC. Il est propriétaire d'un seul cycle de vie
réel - **preuve → diagnostic → changement approuvé par une personne →
déploiement canari via HYDRA-UMC-UPDATER → vérification** - sans
réimplémenter l'inférence, les mises à jour, ni la logique de sécurité
du MCU qui existent déjà ailleurs dans l'écosystème. Ce projet expédie
désormais cinq des six étapes de ce cycle de vie : **la preuve**, **le
diagnostic**, **le changement approuvé par une personne**, **le
déploiement canari** et **la vérification**.

Deux rôles, un seul paquet, encore aucun transport réseau entre eux :

1. **Rôle edge** (`edge collect`) - s'exécute directement sur la
   machine observée (une vraie cellule CM5, ou la propre station de
   travail d'un développeur). Scanne chaque checkout frère à la
   recherche de son propre `hydra-umc.project.json`, vérifie
   éventuellement une ou plusieurs unités systemd et des points de
   terminaison HTTP de santé, et dérive un vrai `MaintenanceIncident`
   pour chaque problème RÉEL trouvé - un scan propre produit zéro
   incident, jamais un "tout va bien" synthétique. Tous les incidents
   d'une même exécution partagent un seul ID de corrélation.
2. **Rôle control-plane** (`control show`) - s'exécute sur une machine
   de développement et rend un fichier de snapshot enregistré, en
   lecture seule : inventaire des projets, résultats des vérifications
   de santé, et tous les incidents triés du plus au moins grave. Il ne
   modifie jamais le fichier qu'il lit, et cette livraison ne "résout"
   ni ne reconnaît non plus aucun incident depuis ici.
3. **Diagnostic** (`control diagnose`) - s'exécute aussi sur le rôle
   control-plane. Envoie un incident déjà rédigé à un fournisseur d'IA
   (n'importe lequel - Anthropic et OpenAI sont intégrés d'office, voir
   [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)) et reçoit en retour une
   explication de cause racine proposée en texte brut - une suggestion
   pour qu'une personne la lise, jamais une décision.
4. **Changement approuvé par une personne** (`control propose` /
   `approve` / `reject`) - un `ChangeProposal` réel et immuable (un diff
   unifié, une description, une justification) qui passe de `pending` à
   `approved`/`rejected` EXACTEMENT UNE FOIS, toujours attribué à une
   personne réelle nommée. Voir
   [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
5. **Déploiement canari** (`control deploy-canary`) - refuse de
   s'exécuter contre autre chose qu'une proposition `approved`. Applique
   le diff à un clone de staging indépendant, exécute la propre commande
   réelle de build-test du projet cible à cet endroit, et ne promeut
   (conservant le checkout précédent comme une vraie sauvegarde) que si
   cela réussit - le checkout réel n'est jamais touché autrement.
6. **Vérification** (`control verify`) - relance exactement la même
   vérification réelle qui a produit l'incident à l'origine, en
   utilisant les propres fonctions de la Livraison 1, pour confirmer
   qu'il est vraiment résolu.

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

Voir [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) pour le flux
complet et réel d'opérateur ci-dessus.

Il n'existe ni invocation par défaut/sans argument, ni GUI, dans cette
livraison - voir [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) pour la
surface de commandes complète et réelle.

## 2. 🧱 ARCHITECTURE ET DÉCISIONS DE CONCEPTION

- **Un incident est dérivé, jamais déclaré.** Les méthodes `add_*` de
  `IncidentBatch` renvoient `None` quand ce qu'elles ont examiné était
  effectivement sain. Aucun chemin de code ne fabrique un incident à
  partir d'une observation propre, et aucun ne rejette silencieusement
  un incident réel.
- **Une frontière de protocole se dégrade honnêtement, elle ne devine
  jamais.** `check_systemd_unit_health()` lève un `SystemdUnavailableError`
  propre dès l'instant où `systemctl` n'est pas dans le `PATH` - ce qui
  arrive à chaque fois sur cette machine de développement, et sur tout
  hôte sans systemd - au lieu de rapporter un statut "inactive" inventé.
  `check_http_health()` garde une vraie panne réseau (`status_code is
  None`) distincte d'une vraie réponse HTTP mais non saine.
- **La rédaction est la pièce de code la plus critique pour la sécurité
  ici.** `log_redaction.py` est une transformation de texte pure et sans
  dépendance, couverte par ses propres tests avant que quoi que ce soit
  d'autre ne la consomme. Une correspondance de nom de clé doit
  rechercher le nom du secret comme sous-chaîne d'un vrai jeton
  identifiant (`DB_PASSWORD`, `api-key`), pas comme un mot délimité par
  `\b` - `_` est un caractère de mot en expression régulière, donc un
  `\bpassword\b` naïf ne correspond jamais à `DB_PASSWORD`.
  `MaintenanceIncident.to_dict()` relance `redact_secrets()` sur
  `symptom` au moment de la sérialisation, même si l'appelant l'a déjà
  rédigé en amont - défense en profondeur pour le champ le plus
  susceptible de porter une ligne de log copiée-collée.
- **Le contrat `MaintenanceIncident`/`NodeSnapshot` est figé à dessein,
  champ par champ, sur le propre "CONTRATO MINIMO" de l'audit.** Voir
  [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md). Une livraison
  future qui parle à un vrai fournisseur d'IA ou à un système de tickets
  ne devrait jamais avoir à traduire entre deux formes incompatibles.
- **Le diagnostic est indépendant du fournisseur par conception.**
  `diagnose_incident()` ne dépend que d'un Protocol minimal `AIProvider`
  - aucun fournisseur d'IA réel n'est jamais figé dans le code. Deux
  fournisseurs réels (Anthropic, OpenAI) sont livrés comme extras
  optionnels ; un appelant peut passer tout autre objet implémentant ce
  même contrat à une seule méthode.
- **Un déploiement canari ne touche jamais le checkout réel avant qu'un
  vrai build n'ait déjà prouvé que le changement fonctionne.**
  `deploy_canary()` refuse de s'exécuter tant que le `status` de la
  proposition donnée n'est pas `approved`, puis met en staging le diff
  dans un clone local indépendant et ne promeut (échange à deux
  renommages, checkout précédent conservé comme vraie sauvegarde) que si
  la propre commande de build-test de ce projet se termine vraiment avec
  le code `0` - le même patron atomique-par-vérification que le propre
  `install.py` de HYDRA-UMC-UPDATER utilise déjà.
- **Une proposition est décidée exactement une fois.**
  `approve_change()`/`reject_change()` lèvent chacune
  `InvalidTransitionError` sur tout ce qui n'est pas une proposition
  `pending` - une seconde décision n'écrase jamais silencieusement la
  première, et chaque décision est attribuée à un nom réel, non vide.
- **La vérification relance la MÊME vérification réelle, jamais une plus
  laxiste.** `verify_incident_resolved()` appelle directement les
  propres `check_http_health()`/`check_systemd_unit_health()` de la
  Livraison 1 - il n'existe nulle part dans ce projet une seconde
  implémentation de vérification de santé, dérivant indépendamment.
- **La Livraison 6 est bloquée, pas simplement sautée.** Le propre
  contrat réel de HYDRA-UMC-VOICE-UI (`gateway.py`) est une passerelle
  bornée, ENTRANTE, de transcription vers intention, sans aucune
  surface réelle de notification sortante aujourd'hui - en inventer une
  ici aurait signifié fabriquer une intégration qui n'existe pas, ce que
  le propre standard anti-fabrication de ce projet n'autorise pas. Voir
  la section FEUILLE DE ROUTE ci-dessous.
- **Bibliothèque standard uniquement pour le cœur.** `edge collect`/
  `control show`/`control propose`/`control approve`/`control reject`/
  `control verify` n'ont besoin d'aucune dépendance - `urllib.request`
  pour la vérification HTTP, `subprocess`/`shutil.which` pour celle de
  systemd, `git` (un vrai binaire externe, pas un paquet Python) pour
  l'étape de déploiement canari. Seul `control diagnose` a besoin d'un
  extra optionnel, et seulement pour le fournisseur réellement utilisé.

## 📂 STRUCTURE DES RÉPERTOIRES

```
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/
│   ├── log_redaction.py    # Rédaction pure de secrets (KEY=VALUE, tokens Bearer, blocs PEM)
│   ├── inventory.py        # Scan de manifestes + vérifications de santé systemd/HTTP
│   ├── incident.py         # Contrat MaintenanceIncident / IncidentBatch
│   ├── edge_agent.py       # Orchestre ce qui précède en un seul NodeSnapshot
│   ├── control_plane.py    # Chargeur de snapshot en lecture seule + rendu de rapport texte
│   ├── diagnosis.py        # Livraison 2 : suggestion de diagnostic assistée par IA, indépendante du fournisseur
│   ├── change_proposal.py  # Livraison 3 : cycle de vie immuable de ChangeProposal, approuvé par une personne
│   ├── canary_deploy.py    # Livraison 4 : stage + apply + verify + promote, uniquement sur approbation
│   ├── verification.py     # Livraison 5 : relance la vérification réelle derrière un incident
│   └── cli.py               # Point d'entrée des sous-commandes edge/control pour chaque livraison ci-dessus
├── tests/                  # Vrais tests pour les 10 modules, incl. un fixture local http.server, un fournisseur d'IA simulé et un vrai dépôt git jetable pour le déploiement canari
├── docs/
│   ├── CLI_REFERENCE.md     # Chaque sous-commande, ses flags, le contrat des codes de sortie
│   ├── INCIDENT_CONTRACT.md # La forme JSON réelle de MaintenanceIncident/NodeSnapshot
│   ├── DIAGNOSIS.md         # Le contrat, les fournisseurs et la frontière de sécurité propres à la Livraison 2
│   └── CHANGE_LIFECYCLE.md  # Le contrat et la frontière de sécurité propres aux Livraisons 3-5
├── images/                 # Médias et icônes de l'application
├── tools/
│   ├── build_test.py        # Vérification de build/compilation sans versionnage
│   └── ci_validate.py       # Validation manifeste/CHANGELOG/docs utilisée par la CI
├── build.sh / build.bat     # venv + installation éditable + compile-check + tests
├── build-test.sh / .bat     # Validation de build uniquement, sans rien modifier
├── run.sh / run.bat         # Démo réelle edge collect + control show (sans argument), ou relaie une vraie commande CLI
├── bump_version.py          # Incrément type "odomètre" de l'écosystème (pyproject.toml + __init__.py)
└── bump_manifest_version.py # Synchronise la version de hydra-umc.project.json avec la native (--sync)
```

## ⚙️ COMPILATION ET EXÉCUTION

```bash
chmod +x build.sh   # une seule fois
./build.sh          # crée .venv, pip install -e ".[dev]", compile-check + tests
./run.sh                                          # démo réelle : edge collect contre ce
                                                   # workspace GitHub, puis control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # ou .[ai-openai] - nécessaire seulement pour control diagnose
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name NOM --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control approve proposal.json --approved-by "Votre Nom"
./run.sh control deploy-canary proposal.json --live-root CHEMIN --build-test-command "bash build-test.sh"
./run.sh control verify snapshot.json --incident-id <id>
```

Sous Windows : `build.bat`, puis `run.bat` (même démo sans argument) /
`run.bat edge collect ...` / n'importe quelle sous-commande `control
...` ci-dessus. `build-test.sh`/`.bat` effectue la même vérification de
compilation (syntaxe Python uniquement), sans rien modifier, que la
propre CI de ce projet effectue - il n'exécute PAS la suite de tests
lui-même; la CI exécute `pytest` comme une étape séparée, ultérieure.
Lancez `./build.sh`/`build.bat` (ou `pytest tests/` directement) pour
la suite de tests locale complète.

**Dépannage**

- `edge collect` rapporte `systemdAvailable: false` à chaque exécution :
  cet hôte n'a vraiment pas de `systemctl` dans le `PATH` (toute machine
  de développement non-Linux, et certains conteneurs Linux minimaux) -
  c'est la dégradation honnête attendue, pas un bug. Voir
  [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).
- `control show` échoue avec `ERROR: ...` : le fichier de snapshot
  n'existe pas, n'est pas du JSON valide, ou n'est pas un vrai objet de
  snapshot - relancez `edge collect` et vérifiez son propre chemin
  `--out`.
- `control diagnose` échoue avec `ERROR: the optional '<provider>'
  package is not installed` : exécutez `pip install -e ".[ai-anthropic]"`
  ou `".[ai-openai]"`, selon `--provider`.
- `control diagnose` échoue avec `ERROR: no ... API key available` :
  définissez `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` avant de l'exécuter.
- `control deploy-canary` échoue avec `ERROR: refusing to deploy ...` :
  la proposition n'est pas encore `approved` - exécutez d'abord `control
  approve`.
- `control deploy-canary` rapporte `promoted: false` : lisez
  `buildOutput` dans le JSON de résultat - le build de staging a
  vraiment échoué, et le checkout réel n'a jamais été touché. Voir
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).

## 🚀 FEUILLE DE ROUTE

Les Livraisons 1-5 (cette version) expédient **preuve**, **diagnostic**,
**changement approuvé par une personne**, **déploiement canari** et
**vérification** - le vrai cycle de vie déjà nommé dans le propre
manifeste et CHANGELOG de ce projet. Ce qu'il reste :

- **Livraison 6 - Intégration voix/notifications - vraiment BLOQUÉE,
  pas simplement reportée.** Le plan était de faire remonter un incident
  critique, ou un canari terminé, via HYDRA-UMC-VOICE-UI. L'étude réelle
  de son propre code (`gateway.py`) a révélé que c'est une passerelle
  bornée, ENTRANTE, de transcription vers intention (un Watch envoie du
  texte, reçoit une réponse), sans aucune vraie surface de notification
  sortante aujourd'hui. En construire une ici aurait signifié inventer
  un point d'intégration que VOICE-UI lui-même n'a pas - le propre
  standard anti-fabrication de ce projet ne le permet pas. À revisiter
  une fois que VOICE-UI (ou un successeur) aura développé une vraie
  capacité propre d'« annonce entrante de l'assistant ».
- Un vrai transport entre les rôles edge et control-plane (aujourd'hui,
  déplacer un fichier de snapshot entre les deux est une étape
  manuelle).
- Une commande de restauration pour un canari déjà promu qui s'avère
  ensuite incorrect en production - le répertoire `.backup-<id>` est
  réel et conservé, mais le restaurer aujourd'hui est une étape manuelle
  (voir [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)).

## 🔗 Projets Liés

Ce projet fait partie de l'écosystème robotique HYDRA-UMC du même auteur (JuanenRac / Electro Hobby 3D). Bon à savoir, car une demande pourrait en réalité concerner l'un de ceux-ci plutôt que ce dépôt.

**Directement Liés**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — détecte, installe et met à jour chaque checkout de l'écosystème ; un déploiement canari de la Livraison 4 applique un changement approuvé via la propre voie de mise à jour atomique-par-vérification déjà existante de ce projet, plutôt qu'une seconde implémentation.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — un autre frère "Ecosystem Operations" : construit une image CM5 neuve et totalement à jour, plutôt que d'observer une déjà en fonctionnement.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — un vrai chien de garde de santé de flotte basé sur gRPC, avec son propre retry/backoff et sa détection d'incohérence d'identité - un sujet lié mais distinct (santé des nœuds de flotte en direct via gRPC) de la propre collecte de preuves par manifeste/systemd/HTTP et du cycle de vie des incidents de ce projet.

**Fait Également Partie de l'Écosystème**

*Matériel & Plateforme de Base*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — la carte mère physique du bras robotique : hôte CM5 + coprocesseur STM32H745 double cœur, coordonnant jusqu'à 8 bras-outils via CAN-OTA/SPI-OTA.
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — couche produit reproductible sur Raspberry Pi OS pour le CM5 : agent en lecture seule, config/profils validés, provisionnement WiFi de premier contact.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — le contrat JSON-Schema partagé et la barrière de sécurité contre laquelle chaque bridge valide ses commandes.

*Backend Central & Clients*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — le vrai backend headless (REST/WebSocket) auquel parle réellement chaque client de contrôle.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — tableau de bord de contrôle web avec visualisation 3D multi-robot en temps réel.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — centre de commande d'essaim de bureau (PySide6) pour plusieurs serveurs à la fois.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — application de contrôle Android native avec connexion biométrique et un compagnon Wear OS jumelé.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — application de contrôle iOS/iPadOS (Flutter) avec synchronisation WebSocket en temps réel.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — interface tactile native pour l'écran tactile DSI 7" embarqué, intégrée directement sur le CM5.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — créateur/éditeur graphique de bureau pour URDF qui envoie les modèles terminés vers le propre catalogue de STUDIO.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — frontière de coordination pour les flottes AGV/AMR via un éditeur MQTT VDA 5050 réel.
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — coordinateur haut niveau pour cellules CNC avec accès réel au statut/octets de contrôle GRBL.
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — frontière de coordination pour droïdes à pattes/humanoïdes, avec un véritable émetteur de commandes Boston Dynamics Spot.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — coordinateur de sécurité pour cellules laser lisant 3 vraies sécurités GPIO de clé/enceinte/verrouillage.
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — coordinateur haut niveau sûr pour le flux de cartes du pick-and-place OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — frontière de coordination sûre pour imprimantes 3D Moonraker/Klipper, avec de vraies commandes de tâche contrôlées.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — coordinateur de sécurité avec un vrai transport ROS 2 rclpy à importation paresseuse.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — frontière de coordination pour UAV équipés de caméra, avec un véritable émetteur de commandes MAVLink.

*Plateforme d'Outils URTC*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware pour la carte physique Universal Robot Tool Controller, plus de 25 profils d'outil sur bus CAN.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — outil de bureau à interface graphique pour flasher les cartes URTC, CAN-OTA plus SWD/JTAG puce complète.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — outil de bureau de diagnostic CAN-bus en direct pour cartes URTC, un panneau par profil d'outil.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — alternative basée navigateur à URTC-TESTER via la Web Serial API, sans installation locale.

*Nœud IA de Vision (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — hub d'intégration pour le pipeline de vision Hailo-8, avec une vraie vérification de disponibilité matérielle par étape.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — registre réel de modèles compilés avec vérification de chargement sécurisé par architecture Hailo/checksum.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — générateur réel de pipeline GStreamer + config MediaMTX, avec une vraie frontière d'intégration HailoRT.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — vraie loi de correction Position-Based Visual Servoing, verrouillée sur l'état de zone en amont.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — vraie vérification de violation de zone et demande d'E-STOP, avec application de la fraîcheur de calibration.

*Nœud IA Cognitif (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — hub d'intégration pour le pipeline cognitif Hailo-10 (orchestration LLM/VLA/voix).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — vrai encodage/décodage de jetons d'action et génération de trajectoire pour un modèle Vision-Language-Action.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — vrai front-end vocal (VAD + analyseur d'intention) avec un relais Watch borné et soumis à confirmation - envisagé un temps comme la surface de notification de la Livraison 6 de ce projet, s'est révélé n'avoir aucun vrai contrat de notification sortante aujourd'hui (voir la section FEUILLE DE ROUTE).
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — vraie décomposition de tâches basée sur des règles et récupération sémantique d'erreurs sur les codes d'erreur MCU.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — vraie recherche documentaire TF-IDF (bibliothèque standard uniquement) sur les propres documents Markdown de cet écosystème.

*Orchestration & Essaim*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — hub d'intégration avec un vrai contrat de rapport de santé gRPC/Protobuf et une machine à états de mission.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — vraie file de tâches basée sur la priorité avec déduplication, via une vraie API HTTP.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — vrai planificateur de trajectoire 3D basé sur RRT, avec vraie validation des collisions obstacle/espace de travail.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — vraie synchronisation d'état CRDT LWW-Element-Map, testée par propriétés pour la convergence multi-cellule.

*Jumeau Numérique & Simulation*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — hub d'intégration pour le moteur de jumeau numérique, avec un vrai contrat de synchronisation par compatibilité de version.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — vrai verrouillage de sécurité hardware-in-the-loop routant les commandes entre simulation et matériel réel.
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — vraie cinématique directe et validation des limites articulaires sur un vrai sous-ensemble URDF.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — vrai générateur procédural de scènes 2D avec export d'annotations YOLO/COCO.

*Données & Analytique*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — vrai magasin de séries temporelles basé sur sqlite3, avec une vraie API HTTP d'ingestion/requête.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — vrai détecteur d'anomalies FFT + ligne de base statistique, avec surveillance de dérive.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — vrai calcul OEE/disponibilité sur l'historique de DATALAKE, avec export CSV reproductible.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — vrai pipeline d'ingestion CAN/WebSocket vers DATALAKE, avec déduplication par séquence.

*Passerelle Industrielle*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — hub d'intégration relayant vers les protocoles industriels, avec une vraie couche de liste blanche de commandes/contre-pression.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — vrai espace d'adressage OPC-UA, vérifié avec une vraie session client du protocole binaire.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — vrai broker MQTT avec authentification par client optionnelle et ACL de sujets.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — vrais points de terminaison XML MTConnect `/probe` et `/current`, avec sortie en mode dégradé.

*Outils Complémentaires*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — panneaux Smart Summaries et Anomaly Highlighting sur DATALAKE/ANOMALY-DETECTOR, avec un repli statistique honnête.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — CLI de flotte avec un vrai contrat de codes de sortie stable, un vrai client en direct de la propre API de HYDRA-UMC-SERVER.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — application compagnon WearOS avec de vraies alertes haptiques et un relais vocal vers le téléphone jumelé.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware pour un rack de montage de cartes avec décodage réel d'ID d'outil et logique de préchauffage Smart Idle.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware plus un vrai compagnon de vision Python pour une tête d'outil d'inspection thermique/RGB.

---

## 📚 Documentation & Communauté

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — chaque sous-commande, ses flags, et le contrat des codes de sortie.
- **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — la forme JSON réelle de `MaintenanceIncident`/`NodeSnapshot`.
- **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — le contrat réel, les fournisseurs, les identifiants et la frontière de sécurité propres à la Livraison 2.
- **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — le contrat réel, la séquence complète stage/apply/verify/promote, et un vrai flux d'opérateur pour les Livraisons 3-5.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — pile technologique et lignes directrices de codage pour une pull request.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — les normes de comportement attendues dans cette communauté.
- **[SECURITY.md](SECURITY.md)** — comment signaler une vulnérabilité, et les véritables axes de sécurité de ce projet.
- **[SUPPORT.md](SUPPORT.md)** — où poser des questions et signaler des bugs.

## 👤 AUTEUR
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LICENCE

GPL-3.0 (logiciel) / CC BY-SA 4.0 (documentation) - voir [LICENSE.md](LICENSE.md).
