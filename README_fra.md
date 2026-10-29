<!-- =============================================================================
HYDRA-UMC-OPS-AGENT - Maintenance-incident coordinator
Copyright (C) JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | 🇫🇷 <b>Français</b> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a> | <a href="README_por.md">🇵🇹 Português</a></p>

### 🔎 Observabilité en lecture seule des incidents de maintenance pour tout l'écosystème

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Language">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="Core">
  <img src="https://img.shields.io/badge/Tests-322%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.1.9-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-0F6CBD.svg" alt="Maturity">
</p>

---

> **État de la sûreté et de la cybersécurité :** cet écosystème n'est pas un système de sécurité certifié. Il n'existe pas encore de chaîne d'E-STOP matérielle, ni de limites ou de verrouillages imposés par le firmware, ni de commande de mouvement vérifiée ; les images de firmware sont contrôlées par CRC-32 et une signature Ed25519, et une compilation de version refuse les clés de développement publiées (les têtes d'outil et les cartes d'extension derrière le relais utilisent encore les chargeurs d'URTC, qui prennent un HMAC-SHA256 à clé partagée au lieu d'une signature) ; TLS et TLS mutuel sont optionnels et désactivés par défaut ; aucune carte propre n'a encore été assemblée ni testée. Lisez la [base de sécurité](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md) et le [modèle de menaces](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md) avant de vous fier à une affirmation d'ici pour la sécurité d'une personne.

---

## 📋 En un coup d'œil

| | |
|---|---|
| Version | `0.1.9` |
| Maturité | Fonctionnel |
| Tests | 322 (`python -m pytest -q tests`) |
| Technologie | Python 3.11+ / JSON Schema / systemd (edge role, Linux only) / two optional AI provider APIs (provider-agnostic diagnosis) / git (staging clone + git apply for the real canary deploy path) |
| Cible | Le Raspberry Pi CM5 d'une cellule HYDRA-UMC |
| Sur matériel réel | Pas encore : aucune exécution sur du matériel réel n'est consignée pour cette version |

**Aller à :** [Présentation](#-présentation) · [Architecture](#-architecture) · [Démarrage rapide](#-démarrage-rapide) · [Tests](#-tests) · [Structure du dépôt](#-structure-du-dépôt) · [Projets liés](#-projets-liés)

## 🚦 État du projet

Chaque ligne est une partie de ce dépôt et le feu dit où elle en est aujourd'hui. Elle est écrite d'après ce que le dépôt peut montrer (tests, compilations, exécutions), pas d'après ce qui est prévu.

🟢 Fait et vérifié · 🟡 Fonctionne, avec des limites connues · 🟠 À moitié fait ou pas encore vérifié · 🔴 Pas fait ou ne fonctionne pas

| Domaine | État | Ce que cela veut dire ici |
|---|---|---|
| Logiciel | 🟡 | Fonctionne pour son usage principal ; la vérification d'honnêteté ci-dessus liste ce qui manque encore |
| Tests | 🟢 | 322 tests automatiques, exécutés à chaque modification |
| Matériel réel | 🔴 | Pas encore : aucune exécution sur du matériel réel n'est consignée pour cette version |
| Documentation | 🟢 | README en huit langues, vérifié par rapport au manifeste à chaque modification |

## 🎯 Présentation

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
   (n'importe lequel - `anthropic` et OpenAI sont intégrés d'office, voir
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

Voir [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) pour le flux
complet et réel d'opérateur ci-dessus.

Il n'existe ni invocation par défaut/sans argument, ni GUI, dans cette
livraison - voir [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) pour la
surface de commandes complète et réelle.

## 🧩 Rôle dans HYDRA-UMC

**HYDRA-UMC-OPS-AGENT** est le coordinateur des incidents de maintenance de l'écosystème. Il possède un seul cycle de vie (preuves, diagnostic, changement approuvé par une personne, déploiement canari via `HYDRA-UMC-UPDATER`, vérification) et ne réimplémente ni l'inférence, ni les mises à jour, ni la logique de sécurité des contrôleurs.

## 🏛️ Architecture

<p align="center">
  <img src="images/architecture.svg" alt="HYDRA-UMC-OPS-AGENT architecture" width="100%">
</p>

### ARCHITECTURE ET DÉCISIONS DE CONCEPTION

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
  champ par champ, sur un "CONTRATO MINIMO" explicite.** Voir
  [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md). Une livraison
  future qui parle à un vrai fournisseur d'IA ou à un système de tickets
  ne devrait jamais avoir à traduire entre deux formes incompatibles.
- **Le diagnostic est indépendant du fournisseur par conception.**
  `diagnose_incident()` ne dépend que d'un Protocol minimal `AIProvider`
  - aucun fournisseur d'IA réel n'est jamais figé dans le code. Deux
  fournisseurs réels (`anthropic`, OpenAI) sont livrés comme extras
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
- **Une approbation est une signature, pas un champ.** `approve_change()` signe, avec la clé privée Ed25519 de l'approbateur lui-même, une déclaration de ce qui est exactement approuvé : la proposition, le SHA-256 du diff, qui approuve, jusqu'à quand, le commit du checkout visé et si les chemins protégés sont autorisés. `deploy_canary()` ne l'accepte que si la signature est valide face à un registre de clés *publiques* d'approbateurs ; qui peut seulement écrire le fichier de la proposition ne peut donc rien approuver. Un diff est aussi refusé s'il contient quelque chose ayant la forme d'un vrai secret ou s'il touche des fichiers de CI, de build-test ou de service sans le dire ; le build-test s'exécute avec un environnement minimal ; un service peut être arrêté et contrôlé autour de l'échange avec retour arrière automatique ; et chaque proposition, approbation, déploiement, retour arrière et purge est ajouté à un journal d'audit chaîné par hachage. Voir [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
- **La vérification relance la MÊME vérification réelle, jamais une plus
  laxiste.** `verify_incident_resolved()` appelle directement les
  propres `check_http_health()`/`check_systemd_unit_health()`/
  `check_project_manifest()` de la Livraison 1 - il n'existe nulle part
  dans ce projet une seconde implémentation de vérification de santé,
  dérivant indépendamment. Un incident de manifeste portant un vrai
  `base_commit:` (capturé au mieux à la détection) est en plus vérifié
  face au contrôle partagé `compare_runs()` de HYDRA-UMC-SDK - le
  commit du checkout doit avoir réellement bougé, pas seulement le
  fichier qui paraît corrigé sur disque. Voir
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
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
  l'étape de déploiement canari et pour la capture du `base_commit:`
  d'un incident de manifeste. Seuls `control diagnose` (un extra `ai-*`)
  et la revérification `compare_runs()` d'un incident de manifeste
  (l'extra `sdk`) ont besoin d'une dépendance optionnelle, chacun
  uniquement pour ce qui l'utilise réellement.

## 🚀 Démarrage rapide

Nécessite Python 3.11 ou plus récent.

```bash
./build.sh  # Linux, macOS (build.bat on Windows)
./run.sh    # demo: edge collect on a throwaway sample project, then control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
```

## 🧪 Tests

322 tests automatiques s'exécutent avec `python -m pytest -q tests`. Ils n'ont besoin ni de matériel ni de rien en dehors de cette machine.

La CI exécute `HYDRA_UMC_CI=1 python tools/ci_validate.py`, qui vérifie le manifeste, les documents, les huit README et les images.

## 🏗️ Compilation et publication

```bash
chmod +x build.sh   # une seule fois
./build.sh          # crée .venv, pip install -e ".[dev]", compile-check + tests
./run.sh                                          # démo réelle : edge collect contre un projet
                                                   # d'exemple jetable, puis control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # ou .[ai-openai] - nécessaire seulement pour control diagnose
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name NOM --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control keygen --name you --key-out you.pem --public-out you.pub
./run.sh control approve proposal.json --approved-by you --key you.pem --live-root PATH
./run.sh control deploy-canary proposal.json --live-root PATH --build-test-command "bash build-test.sh" --approvers approvers.json
pip install -e ".[signing]"                       # needed to sign and to verify approvals (cryptography)
pip install -e ".[sdk]"                           # nécessaire seulement pour revérifier le base_commit d'un incident de manifeste
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
- `control deploy-canary` échoue avec `ERROR: ... signed approval` / `not a registered approver` / `expired` / `approved for commit` : l'approbation manque, a été faite avec une clé absente du registre, a expiré ou a été donnée pour un autre état du checkout. Approuvez à nouveau avec `control approve --key VOTRECLE --live-root CHEMIN`. Une proposition approuvée en éditant le fichier, ou avant que les approbations soient signées, n'est jamais acceptée.
- `control deploy-canary` rapporte `promoted: false` : lisez
  `buildOutput` dans le JSON de résultat - le build de staging a
  vraiment échoué, et le checkout réel n'a jamais été touché. Voir
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).

## 📂 Structure du dépôt

<p align="center">
  <img src="images/repository-structure.svg" alt="Repository structure of HYDRA-UMC-OPS-AGENT" width="100%">
</p>

<details>
<summary>Version texte de l'arborescence</summary>

```text
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/   code source
│   ├── __init__.py            Version du paquet
│   ├── _atomic.py             Écritures de fichier durables et atomiques pour les magasins, propositions et résultats
│   ├── approval_signing.py    Signatures Ed25519 des approbations ; registre des approbateurs
│   ├── audit_journal.py       Journal d'audit chaîné par hachage, en ajout seul
│   ├── diff_policy.py         Ce qu'un diff peut contenir et toucher (formes de secret, chemins protégés, taille)
│   ├── log_redaction.py       Rédaction pure de secrets (KEY=VALUE, tokens Bearer, blocs PEM)
│   ├── inventory.py           Scan de manifestes + vérifications de santé systemd/HTTP
│   ├── incident.py            Contrat MaintenanceIncident / IncidentBatch
│   ├── edge_agent.py          réunit les pièces en un NodeSnapshot
│   ├── control_plane.py       Chargeur de snapshot en lecture seule + rendu de rapport texte
│   ├── diagnosis.py           Livraison 2 : suggestion de diagnostic assistée par IA, indépendante du fournisseur
│   ├── change_proposal.py     Livraison 3 : cycle de vie immuable de ChangeProposal, approuvé par une personne
│   ├── canary_deploy.py       Livraison 4 : stage + apply + verify + promote, uniquement sur approbation
│   ├── verification.py        Livraison 5 : relance la vérification réelle derrière un incident
│   ├── cli.py                 sous-commandes edge et control
│   └── incident_store.py      La couche durable et dédupliquée des incidents : un enregistrement ouvert par (nœud, composant), résolu seulement si ce composant a été revérifié et est sain
├── tests/                     Vrais tests pour les 11 modules, incl. un fixture local http.server, un fournisseur d'IA simulé et un vrai dépôt git jetable pour le déploiement canari
├── docs/                      documents du projet
├── images/                    Médias et icônes de l'application
├── tools/                     outils du projet et vérifications de la CI
├── .github/                   workflow de CI et modèles de tickets
├── build.sh / build.bat       venv + installation éditable + compile-check + tests
├── run.sh / run.bat           Démo réelle edge collect + control show (sans argument), ou relaie une vraie commande CLI
├── bump_version.py            Incrément de version type compteur kilométrique (exécuté seulement par la commande `bump` explicite)
├── bump_manifest_version.py   Synchronise la version de hydra-umc.project.json avec la native (--sync)
├── CHANGELOG.md               ce qui a changé à chaque version
├── build-test.sh              vérification de build sans modification
├── hydra-umc.project.json     manifeste : version, maturité, famille
├── pyproject.toml             métadonnées du paquet
└── test.sh                    lance les tests
```

</details>

## 🗺️ Feuille de route et limites connues

**Limites connues aujourd'hui**

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

## 🌍 Langues

Ce README et les documents du dépôt existent en huit langues : anglais, espagnol, allemand, français, italien, japonais, chinois et portugais (Portugal). Ils sont écrits ensemble et la CI vérifie que les huit fichiers ont les mêmes sections et les mêmes liens. Ce dépôt n'a ni écran ni catalogue de messages propre, il n'y a donc aucune chaîne d'interface à traduire.

## 🔗 Projets liés

Ce projet fait partie de l'écosystème robotique HYDRA-UMC du même auteur (JuanenRac / Electro Hobby 3D). Bon à savoir, car une demande pourrait en réalité concerner l'un de ceux-ci plutôt que ce dépôt.

**Directement Liés**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — détecte, installe et met à jour chaque checkout de l'écosystème. Un déploiement canari ici suit le même schéma d'atomicité par vérification mais en est une implémentation propre, pas un appel à l'outil de mise à jour ; les deux peuvent donc diverger : l'outil de mise à jour refuse d'avancer en fast-forward un checkout qui porte un commit local d'un canari, et indique lequel.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — un autre frère "Ecosystem Operations" : construit une image CM5 neuve et totalement à jour, plutôt que d'observer une déjà en fonctionnement.
- **[HYDRA-UMC-DEV-SERVER](https://github.com/JuanenRac/HYDRA-UMC-DEV-SERVER)** — hôte de développement reproductible qui compile des candidats et coordonne sa file d'attente de tâches durable avec le cycle de vie des incidents propre à ce projet ; il n'approuve jamais ses propres tâches.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — un vrai chien de garde de santé de flotte basé sur gRPC, avec son propre retry/backoff et sa détection d'incohérence d'identité - un sujet lié mais distinct (santé des nœuds de flotte en direct via gRPC) de la propre collecte de preuves par manifeste/systemd/HTTP et du cycle de vie des incidents de ce projet.

**Fait Également Partie de l'Écosystème**

*Matériel & Plateforme de Base*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — la conception de la carte mère du bras robotique : hôte CM5 + coprocesseur STM32H745 double cœur, destinée à coordonner jusqu'à 8 bras-outils via CAN-OTA/SPI-OTA (firmware à un stade précoce ; aucune carte assemblée pour l'instant).
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — couche produit reproductible sur Raspberry Pi OS pour le CM5 : agent en lecture seule, config/profils validés, provisionnement WiFi de premier contact.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — le contrat JSON-Schema partagé et la barrière logicielle de contrôle des jobs contre laquelle chaque bridge valide ses commandes (pas une fonction de sécurité certifiée).

*Backend Central & Clients*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — le vrai backend headless (REST/WebSocket) auquel parle réellement chaque client de contrôle.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — tableau de bord de contrôle web avec visualisation 3D multi-robot en temps réel.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — centre de commande d'essaim de bureau (PySide6) pour plusieurs serveurs à la fois.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — application de contrôle Android native avec connexion biométrique et un compagnon Wear OS jumelé.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — application de contrôle iOS/iPadOS (Flutter) avec synchronisation WebSocket en temps réel.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — interface tactile native pour l'écran tactile DSI 7" embarqué, intégrée directement sur le CM5.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — créateur/éditeur graphique de bureau pour URDF qui envoie les modèles terminés vers le propre catalogue de STUDIO.
- **[HYDRA-UMC-EDITOR-STL](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-STL)** — éditeur de bureau de modèles STL, transformant/remplaçant/retirant/ajoutant de vraies pièces dans le même catalogue de modèles qu'édite aussi HYDRA-UMC-EDITOR-URDF.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — frontière de coordination pour les flottes AGV/AMR via un éditeur MQTT VDA 5050 (testé uniquement contre une flotte émulée).
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — coordinateur haut niveau pour cellules CNC avec accès au statut/octets de contrôle GRBL (testé uniquement contre un émulateur).
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — frontière de coordination pour droïdes à pattes/humanoïdes, avec un émetteur de commandes Boston Dynamics Spot (testé uniquement contre un émulateur).
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — coordinateur de cellules laser lisant 3 signaux GPIO de clé/enceinte/verrouillage (testé uniquement contre une puce simulée ; il ne peut ni armer ni tirer un laser).
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — coordinateur haut niveau sûr pour le flux de cartes du pick-and-place OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — frontière de coordination sûre pour imprimantes 3D Moonraker/Klipper, avec de vraies commandes de tâche contrôlées.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — coordinateur avec un transport ROS 2 rclpy à importation paresseuse (pas encore exécuté contre une installation ROS 2).
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — frontière de coordination pour UAV équipés de caméra, avec un émetteur de commandes MAVLink (testé uniquement contre un émulateur).

*Plateforme d'Outils URTC*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware pour la carte physique Universal Robot Tool Controller, plus de 25 profils d'outil sur bus CAN.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — outil de bureau à interface graphique pour flasher les cartes URTC, CAN-OTA plus SWD/JTAG puce complète.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — outil de bureau de diagnostic CAN-bus en direct pour cartes URTC, un panneau par profil d'outil.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — alternative basée navigateur à URTC-TESTER via la Web Serial API, sans installation locale.
- **[URTC-GATEWAY](https://github.com/JuanenRac/URTC-GATEWAY)** — passerelle devant le bus CAN d'URTC : liste d'identifiants autorisés, limite de débit et clé de session ; logiciel testé sur ordinateur, pas encore sur un bus réel.

*Nœud IA de Vision (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — hub d'intégration pour le pipeline de vision Hailo-8, avec une vraie vérification de disponibilité matérielle par étape.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — registre réel de modèles compilés avec vérification de chargement sécurisé par architecture Hailo/checksum.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — générateur réel de pipeline GStreamer + config MediaMTX, avec une vraie frontière d'intégration HailoRT.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — loi de correction Position-Based Visual Servoing avec autorisation conditionnée à l'état de zone ; pas encore d'estimation de pose par caméra.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — logique v0 de violation de zone, de fraîcheur de calibration et de demande d'E-STOP qui lit les positions d'objets dans un fichier ; aucun détecteur ne l'alimente et aucun E-STOP physique n'y est encore relié.

*Nœud IA Cognitif (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — hub d'intégration pour le pipeline cognitif Hailo-10 (orchestration LLM/VLA/voix).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — vrai encodage/décodage de jetons d'action et génération de trajectoire pour un modèle Vision-Language-Action.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — vrai front-end vocal (VAD + analyseur d'intention) avec un relais Watch borné et soumis à confirmation - envisagé un temps comme la surface de notification de la Livraison 6 de ce projet, s'est révélé n'avoir aucun vrai contrat de notification sortante aujourd'hui (voir la section FEUILLE DE ROUTE).
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — vraie décomposition de tâches basée sur des règles et récupération sémantique d'erreurs sur les codes d'erreur MCU.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — vraie recherche documentaire TF-IDF (bibliothèque standard uniquement) sur les propres documents Markdown de cet écosystème.
- **[HYDRA-UMC-LOCAL-TECHNICIAN](https://github.com/JuanenRac/HYDRA-UMC-LOCAL-TECHNICIAN)** — technicien de maintenance IA local et à portes de politique pour l'écosystème lui-même - observe, diagnostique et propose des corrections ; les deux niveaux de risque les plus élevés ne sont délibérément pas encore implémentés.

*Orchestration & Essaim*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — hub d'intégration avec un vrai contrat de rapport de santé gRPC/Protobuf et une machine à états de mission.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — vraie file de tâches basée sur la priorité avec déduplication, via une vraie API HTTP.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — vrai planificateur de trajectoire 3D basé sur RRT, avec vraie validation des collisions obstacle/espace de travail.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — vraie synchronisation d'état CRDT LWW-Element-Map, testée par propriétés pour la convergence multi-cellule.

*Jumeau Numérique & Simulation*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — hub d'intégration pour le moteur de jumeau numérique, avec un vrai contrat de synchronisation par compatibilité de version.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — routeur hardware-in-the-loop avec un verrouillage logiciel de collision entre simulation et matériel réel (testé sans matériel réel).
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
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — application compagnon WearOS avec des motifs d'alerte haptique et un relais vocal vers le téléphone jumelé (pas encore exécutée sur une montre physique).
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — catalogue de capacités d'adaptateurs externes, GET uniquement par conception.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware pour un rack de montage de cartes avec décodage réel d'ID d'outil et logique de préchauffage Smart Idle.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware plus un vrai compagnon de vision Python pour une tête d'outil d'inspection thermique/RGB.

## 📚 Documentation

Où lire la suite :

* **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — chaque sous-commande, ses flags, et le contrat des codes de sortie.
* **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — la forme JSON réelle de `MaintenanceIncident`/`NodeSnapshot`.
* **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — le contrat réel, les fournisseurs, les identifiants et la frontière de sécurité propres à la Livraison 2.
* **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — le contrat réel, la séquence complète stage/apply/verify/promote, et un vrai flux d'opérateur pour les Livraisons 3-5.
* [Base de sécurité de l'écosystème](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md)
* [Modèle de menaces de l'écosystème](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md)
* [Journal des modifications de ce dépôt](CHANGELOG.md)
* [Licence de ce dépôt](LICENSE.md)

## 🤝 Contribuer et communauté

* Avant une pull request, exécutez `HYDRA_UMC_CI=1 py -3 tools/ci_validate.py` (ou `HYDRA_UMC_CI=1 python3 tools/ci_validate.py`) : il doit afficher `CI_VALIDATION=PASS`. N'exécutez pas `build.sh` ni `build.bat` pour cette vérification ; compiler n'est pas vérifier.
* Les huit README sont écrits à partir d'une source unique dans HYDRA-UMC-DOCS ; ne les modifiez pas à la main. Changez la source et réécrivez-les avec `tools/make_readmes.py`.
* N'affirmez pas dans un README ce qui n'a pas tourné : écrivez « simulé » ou « non essayé sur matériel » quand c'est la vérité.
* Voir [CONTRIBUTING.md](CONTRIBUTING.md), le [code de conduite](CODE_OF_CONDUCT.md), [SECURITY.md](SECURITY.md) et [SUPPORT.md](SUPPORT.md).

## 👤 AUTEUR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENCE

GPL-3.0-or-later - [LICENSE](LICENSE).
