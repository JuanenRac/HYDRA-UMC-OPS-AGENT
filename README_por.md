<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a> | 🇵🇹 <b>Português</b></p>

### 🔎 Observabilidade só de leitura de incidentes de manutenção para todo o ecossistema

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="núcleo só com a biblioteca padrão">
  <img src="https://img.shields.io/badge/Roles-Edge%20(CM5)%20%7C%20Control--plane-367BF5.svg" alt="papéis de periferia e de plano de controlo">
</p>

> **Estado: v0.1.5, estrutura base (scaffolding) - Entregas 1-5 de 6
> (evidências, diagnóstico, alteração aprovada por uma pessoa, implementação
> canário, verificação).** Cada subcomando é real e está testado de ponta a
> ponta - o `control diagnose` contra um fornecedor de IA simulado (qualquer
> fornecedor real funciona, veja [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)); o
> `control deploy-canary` contra um repositório git local real e descartável
> (veja [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)). Nada é
> implementado sem uma aprovação humana explícita primeiro. A Entrega 6
> (voz/notificação) foi investigada e encontrada genuinamente bloqueada, não
> apenas adiada - veja a secção ROTEIRO abaixo. Veja
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) para a superfície exata de
> comandos que existe hoje.

---

**Verificação de honestidade - o que realmente funciona hoje:** as cinco entregas já lançadas - evidências (`inventory.py`, `edge_agent.py`, `incident.py`), diagnóstico (`diagnosis.py`), alteração aprovada por uma pessoa (`change_proposal.py`), implementação canário (`canary_deploy.py`) e verificação (`verification.py`), mais a fronteira de redação (`log_redaction.py`) e a CLI (`cli.py`) - são reais e estão testadas de ponta a ponta (202 testes mais 6 subtestes a passar em todos os 12 ficheiros de testes). A fase de implementação canário é exercitada de verdade contra um repositório git local real e descartável, não contra um mock. O diagnóstico só é testado contra um `AIProvider` simulado - o `AnthropicProvider`/`OpenAIProvider` são implementações reais do mesmo protocolo, mas nenhum foi exercitado contra uma chamada real à API da Anthropic ou da OpenAI nesta suite de testes (não há chave disponível neste ambiente). Os papéis de periferia e de plano de controlo comunicam hoje apenas através de um ficheiro de instantâneo guardado - ainda não há transporte de rede entre eles. A Entrega 6 (voz/notificação) está genuinamente bloqueada, não apenas adiada: o HYDRA-UMC-VOICE-UI não tem hoje nenhuma superfície real de notificação de saída com que integrar. Veja o `CHANGELOG.md` para saber exatamente o que foi entregue até agora.

---

## 1. 🛠️ VISÃO TÉCNICA GERAL

O HYDRA-UMC-OPS-AGENT é o coordenador de incidentes de manutenção do ecossistema
HYDRA-UMC/URTC. É dono de um ciclo de vida real - **evidências →
diagnóstico → alteração aprovada por uma pessoa → implementação canário via
HYDRA-UMC-UPDATER → verificação** - sem reimplementar inferência,
atualizações nem lógica de segurança do MCU que já existem noutros pontos do
ecossistema. Este projeto traz agora cinco das seis etapas desse ciclo de vida:
**evidências**, **diagnóstico**, **alteração aprovada por uma pessoa**,
**implementação canário** e **verificação**.

Dois papéis, um só pacote, ainda sem transporte de rede entre eles:

1. **Papel de periferia (edge)** (`edge collect`) - corre diretamente na
   máquina observada (um controlador de célula CM5 real, ou a própria estação
   de trabalho de quem desenvolve). Percorre cada checkout irmão à procura do
   seu `hydra-umc.project.json`, verifica opcionalmente uma ou mais unidades
   systemd e pontos de saúde HTTP, e deriva um `MaintenanceIncident` real por
   cada problema REAL que encontra - uma varredura limpa produz zero
   incidentes, nunca um «tudo bem» sintético. Todos os incidentes da mesma
   execução partilham um único ID de correlação.
2. **Papel de plano de controlo** (`control show`) - corre num anfitrião de
   desenvolvimento e apresenta, só de leitura, um ficheiro de instantâneo
   guardado: inventário de projetos, resultados das verificações de saúde e
   todos os incidentes ordenados com o mais grave primeiro. Nunca altera o
   ficheiro que lê, e esta entrega também nunca «resolve» nem reconhece um
   incidente a partir daqui.
3. **Diagnóstico** (`control diagnose`) - corre também no papel de plano de
   controlo. Envia um incidente já redigido a um fornecedor de IA (qualquer
   fornecedor - a Anthropic e a OpenAI vêm de origem, veja
   [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)) e recebe de volta uma explicação em
   texto simples da causa-raiz proposta - uma sugestão para uma pessoa ler,
   nunca uma decisão.
4. **Alteração aprovada por uma pessoa** (`control propose` / `approve` /
   `reject`) - uma `ChangeProposal` real e imutável (um diff unificado, uma
   descrição, uma justificação) que passa de `pending` a `approved`/`rejected`
   EXATAMENTE UMA VEZ, sempre atribuída a uma pessoa real com nome. Veja
   [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
5. **Implementação canário** (`control deploy-canary`) - recusa-se a correr
   contra qualquer coisa que não seja uma proposta `approved`. Aplica o diff a
   um clone de preparação independente, corre aí o comando real de
   compilação-e-teste do próprio projeto de destino e só promove (guardando o
   checkout anterior como cópia de segurança real) se isso passar - de outro
   modo o checkout em produção nunca é tocado.
6. **Verificação** (`control verify`) - volta a executar a mesma verificação
   real que originou um incidente, usando as próprias funções da Entrega 1,
   para confirmar que está genuinamente resolvido.

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

Veja [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) para o fluxo
completo e real do operador acima.

Não há invocação por omissão nem interface gráfica nesta entrega - veja
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) para a superfície real e
completa de comandos.

## 2. 🧱 ARQUITETURA E DECISÕES DE DESENHO

- **Um incidente é derivado, nunca declarado.** Os métodos `IncidentBatch.add_*`
  devolvem `None` quando aquilo que examinaram estava de facto saudável. Não
  existe nenhum caminho de código que fabrique um incidente a partir de uma
  observação limpa, nem nenhum que descarte em silêncio um incidente real.
- **Uma fronteira de protocolo degrada com honestidade, nunca adivinha.**
  O `check_systemd_unit_health()` levanta um `SystemdUnavailableError` distinto
  no instante em que o `systemctl` não está no `PATH` - o que acontece sempre
  nesta máquina de desenvolvimento e em qualquer anfitrião sem systemd - em
  vez de reportar um estado «inativo» inventado. O `check_http_health()`
  mantém uma falha de rede real (`status_code is None`) distinguível de uma
  resposta HTTP real mas não saudável.
- **A redação é a peça de código mais crítica para a segurança aqui.**
  O `log_redaction.py` é uma transformação de texto pura, sem dependências,
  coberta por si própria antes de qualquer outra coisa a consumir. Uma
  correspondência de nome de chave tem de procurar o nome do segredo como
  substring de um token identificador real (`DB_PASSWORD`, `api-key`), não como
  palavra delimitada por `\b` - o `_` é um carácter de palavra em regex, pelo
  que um `\bpassword\b` ingénuo nunca corresponde a `DB_PASSWORD`. O
  `MaintenanceIncident.to_dict()` volta a correr o `redact_secrets()` sobre o
  `symptom` no momento da serialização, embora cada chamador já o tenha
  redigido a montante - defesa em profundidade para o campo com mais
  probabilidade de transportar uma linha de registo copiada e colada.
- **O contrato `MaintenanceIncident`/`NodeSnapshot` está fixado de propósito,
  campo a campo, num «CONTRATO MINIMO» explícito.** Veja
  [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md). Uma entrega posterior
  que fale com um fornecedor de IA real ou com um sistema de tickets nunca
  deveria precisar de traduzir entre duas formas incompatíveis.
- **O diagnóstico é agnóstico quanto ao fornecedor por desenho.** O
  `diagnose_incident()` depende apenas de um Protocol `AIProvider` mínimo -
  nunca se fixa no núcleo da lógica um fornecedor de IA real e nomeado. Dois
  fornecedores reais (Anthropic, OpenAI) vêm como extras opcionais; quem
  chama pode passar qualquer outro objeto que implemente o mesmo contrato de
  um só método.
- **Uma implementação canário nunca toca no checkout em produção até uma
  compilação real já ter provado que a alteração funciona.** O
  `deploy_canary()` recusa-se a correr de todo a menos que o `status` da
  própria proposta seja `approved`; depois prepara o diff num clone local
  independente e só promove (troca por dois renomeamentos, checkout anterior
  guardado como cópia de segurança real) se o comando de compilação-e-teste
  desse projeto sair de facto com `0` - o mesmo padrão atómico-por-verificação
  que o `install.py` do próprio HYDRA-UMC-UPDATER já usa.
- **Uma proposta é decidida exatamente uma vez.** O `approve_change()`/
  `reject_change()` levantam cada um um `InvalidTransitionError` perante tudo
  o que não seja uma proposta `pending` - uma segunda decisão nunca substitui
  em silêncio a primeira, e cada decisão é atribuída a um nome real e não
  vazio.
- **A verificação volta a correr a MESMA verificação real, nunca uma mais
  laxa.** O `verify_incident_resolved()` chama diretamente o
  `check_http_health()`/`check_systemd_unit_health()`/
  `check_project_manifest()` da própria Entrega 1 - não existe em lado nenhum
  deste projeto uma segunda implementação de verificações de saúde que derive
  por conta própria. Um incidente de manifesto com um `base_commit:` real
  (melhor esforço, capturado na deteção) é além disso confrontado com o
  controlo de «sucesso aparente» `compare_runs()` partilhado do HYDRA-UMC-SDK -
  o commit do próprio checkout tem de ter avançado de facto, não apenas o
  ficheiro parecer corrigido em disco. Veja
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).
- **A Entrega 6 está bloqueada, não ignorada.** O contrato real do
  HYDRA-UMC-VOICE-UI (`gateway.py`) é uma passagem de entrada, limitada, de
  transcrição para intenção, sem nenhuma superfície real de notificação de
  saída hoje - inventar uma aqui teria significado fabricar uma integração que
  não existe, o que o padrão deste projeto não permite. Veja a secção ROTEIRO
  abaixo.
- **Só a biblioteca padrão no núcleo.** O `edge collect`/`control show`/
  `control propose`/`control approve`/`control reject`/`control verify` não
  precisam de nenhuma dependência - `urllib.request` para a verificação HTTP,
  `subprocess`/`shutil.which` para a verificação do systemd, `git` (um binário
  externo real, não um pacote Python) para a fase de implementação canário e
  para a captura do `base_commit:` de um incidente de manifesto. Só o
  `control diagnose` (um extra `ai-*`) e a reverificação com `compare_runs()`
  de um incidente de manifesto (o extra `sdk`) precisam de uma dependência
  opcional, cada uma só para o que realmente a usa.

## 📂 ESTRUTURA DE DIRETÓRIOS

```
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/
│   ├── _atomic.py          # Escritas de ficheiro duráveis e do tipo tudo-ou-nada para armazéns, propostas e resultados
│   ├── log_redaction.py    # Redação pura de segredos (KEY=VALUE, tokens Bearer, blocos PEM)
│   ├── inventory.py        # Varredura de manifestos + verificações de saúde systemd/HTTP
│   ├── incident.py         # Contrato MaintenanceIncident / IncidentBatch
│   ├── edge_agent.py       # Orquestra o anterior num único NodeSnapshot
│   ├── control_plane.py    # Carregador de instantâneos só de leitura + renderizador de relatório em texto
│   ├── diagnosis.py        # Entrega 2: sugestão de diagnóstico assistida por IA, agnóstica quanto ao fornecedor
│   ├── change_proposal.py  # Entrega 3: ciclo de vida imutável de ChangeProposal, aprovado por uma pessoa
│   ├── canary_deploy.py    # Entrega 4: preparar + aplicar + verificar + promover, só aprovado
│   ├── verification.py     # Entrega 5: volta a executar a verificação real por trás de um incidente
│   └── cli.py               # Ponto de entrada dos subcomandos edge/control para cada entrega acima
├── tests/                  # Testes reais para os 11 módulos, incl. um fixture local http.server, um fornecedor de IA simulado e um repositório git real e descartável para a implementação canário
├── docs/
│   ├── CLI_REFERENCE.md     # Cada subcomando, opções, códigos de saída
│   ├── INCIDENT_CONTRACT.md # A forma JSON real de MaintenanceIncident/NodeSnapshot
│   ├── DIAGNOSIS.md         # O contrato da Entrega 2, fornecedores e fronteira de segurança
│   └── CHANGE_LIFECYCLE.md  # O contrato das Entregas 3-5 e a fronteira de segurança
├── images/                 # Multimédia e ícones da aplicação
├── tools/
│   ├── build_test.py        # Verificação de compilação sem subir a versão
│   └── ci_validate.py       # Validação de manifesto/CHANGELOG/documentação usada pelo CI
├── build.sh / build.bat     # venv + instalação editável + verificação de compilação + testes
├── build-test.sh / .bat     # Apenas validação de compilação sem alterações
├── run.sh / run.bat         # Demonstração real de edge collect + control show (sem argumentos), ou reencaminha um comando real da CLI
├── bump_version.py          # Subida «conta-quilómetros» do ecossistema (pyproject.toml + __init__.py)
└── bump_manifest_version.py # Sincroniza a versão do hydra-umc.project.json com a nativa (--sync)
```

## ⚙️ GUIA DE COMPILAÇÃO E EXECUÇÃO

```bash
chmod +x build.sh   # uma só vez
./build.sh          # cria o .venv, pip install -e ".[dev]", verificação de compilação + testes
./run.sh                                          # demonstração real: edge collect contra este
                                                   # espaço de trabalho do GitHub, depois control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # ou .[ai-openai] - só necessário para control diagnose
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name NAME --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control approve proposal.json --approved-by "Your Name"
./run.sh control deploy-canary proposal.json --live-root PATH --build-test-command "bash build-test.sh"
pip install -e ".[sdk]"                           # só necessário para reverificar o base_commit de um incidente de manifesto
./run.sh control verify snapshot.json --incident-id <id>
```

No Windows: `build.bat` e depois `run.bat` (a mesma demonstração quando chamado
sem argumentos) / `run.bat edge collect ...` / qualquer dos subcomandos
`control ...` acima. O `build-test.sh`/`.bat` faz a mesma verificação
não alteradora de sintaxe Python que o fluxo de CI deste projeto faz, sem
tocar na versão do projeto nem no CHANGELOG - NÃO executa a suite de testes em
si; o CI corre o `pytest` como um passo próprio, separado e posterior. Execute
`./build.sh`/`build.bat` (ou `pytest tests/` diretamente) para a suite de
testes local completa.

**Resolução de problemas**

- O `edge collect` reporta `systemdAvailable: false` em todas as execuções:
  este anfitrião genuinamente não tem `systemctl` no `PATH` (toda a máquina de
  desenvolvimento que não seja Linux, e alguns contentores Linux mínimos) - é a
  degradação honesta pretendida, não um erro. Veja
  [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).
- O `control show` falha com `ERROR: ...`: o ficheiro de instantâneo não
  existe, não é JSON válido ou não é um objeto de instantâneo real - volte a
  executar o `edge collect` e confirme o caminho do seu `--out`.
- O `control diagnose` falha com `ERROR: the optional '<provider>' package is
  not installed`: execute primeiro `pip install -e ".[ai-anthropic]"` ou
  `".[ai-openai]"`, de acordo com o `--provider`.
- O `control diagnose` falha com `ERROR: no ... API key available`: defina
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` antes de o executar.
- O `control deploy-canary` falha com `ERROR: refusing to deploy ...`: a
  proposta ainda não está `approved` - execute primeiro `control approve`.
- O `control deploy-canary` reporta `promoted: false`: leia o `buildOutput` no
  JSON do resultado - a compilação de preparação falhou de facto, e o
  checkout em produção nunca foi tocado. Veja
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md).

## 🚀 ROTEIRO

As Entregas 1-5 (esta versão) trazem **evidências**, **diagnóstico**,
**alteração aprovada por uma pessoa**, **implementação canário** e
**verificação** - o ciclo de vida real já nomeado no próprio manifesto e no
CHANGELOG deste projeto. O que falta:

- **Entrega 6 - Integração de voz/notificação - genuinamente BLOQUEADA, não
  apenas adiada.** O plano era fazer chegar um incidente crítico, ou uma
  implementação canário concluída, através do HYDRA-UMC-VOICE-UI. A
  investigação real do código do próprio VOICE-UI (`gateway.py`) concluiu que é
  uma passagem LIMITADA DE ENTRADA de transcrição para intenção (um Watch
  envia texto e recebe uma resposta), sem nenhuma superfície real de
  notificação de saída/push hoje. Construir uma aqui significaria inventar um
  ponto de integração que o próprio VOICE-UI não tem - o padrão de não
  fabricação deste projeto não o permite. Volte a considerar isto quando o
  VOICE-UI (ou um sucessor) ganhar uma capacidade real de «anúncio de
  assistente de entrada».
- Um transporte real entre os papéis de periferia e de plano de controlo (hoje,
  mover um ficheiro de instantâneo entre eles é um passo manual).
- Um comando de reversão para uma implementação canário promovida que mais
  tarde se revele errada em execução - o diretório `.backup-<id>` é real e
  é conservado, mas restaurá-lo hoje é um passo manual (veja
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)).

## 🔗 Projetos relacionados

Este projeto faz parte do ecossistema de robótica HYDRA-UMC do mesmo autor (JuanenRac / Electro Hobby 3D). Vale a pena conhecê-los, porque um pedido pode ser, na verdade, sobre um destes e não sobre este repositório.

**Diretamente relacionados**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — deteta, instala e atualiza cada checkout do ecossistema; uma implementação canário da Entrega 4 aplica uma alteração aprovada pelo caminho de atualização atómico-por-verificação já existente neste projeto, em vez de uma segunda implementação.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — outro irmão de «Operações do ecossistema»: constrói uma imagem nova e totalmente atual do CM5 em vez de observar uma que já está a correr.
- **[HYDRA-UMC-DEV-SERVER](https://github.com/JuanenRac/HYDRA-UMC-DEV-SERVER)** — anfitrião de desenvolvimento reproduzível que constrói candidatos e coordena a sua fila de tarefas durável com o ciclo de vida de incidentes deste projeto; nunca aprova as suas próprias tarefas.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — um vigilante real de saúde da frota por gRPC, com repetição/recuo próprios e deteção de identidade incoerente - uma preocupação relacionada mas distinta (saúde em direto dos nós da frota por gRPC) da recolha de evidências por manifesto/systemd/HTTP e do ciclo de vida de incidentes deste projeto.

**Também fazem parte do ecossistema**

*Hardware e plataforma centrais*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — a placa-mãe física do braço robótico: anfitrião CM5 + STM32H745 de dois núcleos, que orquestra até 8 braços de ferramenta por CAN-OTA/SPI-OTA.
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — camada de produto reproduzível do Raspberry Pi OS para o CM5: agente só de leitura, configuração/perfis validados, aprovisionamento Wi-Fi de primeiro contacto.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — o contrato JSON-Schema partilhado e a fronteira de portas de segurança contra a qual cada bridge valida os seus comandos.

*Backend central e clientes*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — o back-end headless real (REST/WebSocket) com que todos os clientes de controlo realmente comunicam.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — painel web de controlo com visualização 3D em tempo real de vários robôs.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — centro de comando de enxame para desktop (PySide6) para vários servidores ao mesmo tempo.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — aplicação Android nativa de controlo, com início de sessão biométrico e um companheiro Wear OS emparelhado.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — aplicação de controlo para iOS/iPadOS (Flutter) com sincronização WebSocket em tempo real.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — interface tátil nativa para o ecrã tátil DSI de 7" integrado, executada no próprio CM5.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — criador/editor gráfico de URDF para desktop que envia os modelos concluídos para o catálogo do STUDIO.
- **[HYDRA-UMC-EDITOR-STL](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-STL)** — editor de modelos STL para desktop que transforma/substitui/remove/adiciona peças reais no mesmo catálogo de modelos que o HYDRA-UMC-EDITOR-URDF também edita.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — fronteira de coordenação para frotas AGV/AMR através de um publicador MQTT VDA 5050 real.
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — coordenador de células CNC de alto nível com acesso real ao estado GRBL e aos bytes de controlo.
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — fronteira de coordenação para droides com patas/humanoides, com um emissor real de comandos para o Boston Dynamics Spot.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — coordenador de segurança de células laser que lê 3 proteções reais por GPIO (chave, caixa e interlock).
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — coordenador seguro de fluxo de placa de alto nível para pick-and-place com OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — fronteira de coordenação segura para impressoras 3D Moonraker/Klipper, com comandos de trabalho reais protegidos por portas.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — coordenador de segurança com um transporte ROS 2 real baseado em rclpy importado sob demanda.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — fronteira de coordenação para UAV com câmara, com um emissor real de comandos MAVLink.

*Plataforma de ferramentas URTC*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware da placa física Universal Robot Tool Controller, mais de 25 perfis de ferramenta por barramento CAN.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — ferramenta gráfica de gravação para desktop das placas URTC, por CAN-OTA e também SWD/JTAG de chip completo.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — ferramenta de diagnóstico CAN em tempo real para desktop das placas URTC, com um painel por perfil de ferramenta.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — alternativa no navegador ao URTC-TESTER através da Web Serial API, sem instalação local.

*Nó de IA de visão (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — centro de integração do pipeline de visão Hailo-8, com uma verificação real de prontidão de hardware por fase.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — registo real de modelos compilados com verificação segura de carga por arquitetura Hailo e soma de verificação.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — pipeline GStreamer real e gerador de configuração MediaMTX com uma fronteira de integração HailoRT real.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — lei de correção real de servovisão baseada em posição, protegida pelo estado da zona a montante.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — verificação real de violação de zonas e pedido de E-STOP, com exigência de calibração recente.

*Nó de IA cognitiva (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — centro de integração do pipeline cognitivo do Hailo-10 (orquestração de LLM/VLA/voz).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — codificação/descodificação real de tokens de ação e geração de trajetórias para um modelo Visão-Linguagem-Ação.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — front-end de voz real (VAD + analisador de intenções) com um relé para o Watch limitado e sujeito a confirmação - considerado em tempos como superfície de notificação da Entrega 6 deste projeto, mas sem nenhum contrato real de notificação de saída hoje (veja a secção ROTEIRO).
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — decomposição real de tarefas baseada em regras e recuperação semântica de erros sobre os códigos de erro do MCU.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — pesquisa real de documentos TF-IDF só com a biblioteca padrão sobre a documentação Markdown deste ecossistema.
- **[HYDRA-UMC-LOCAL-TECHNICIAN](https://github.com/JuanenRac/HYDRA-UMC-LOCAL-TECHNICIAN)** — técnico de manutenção de IA local, protegido por políticas, para o próprio ecossistema: observa, diagnostica e propõe correções; os dois níveis de maior risco não estão implementados de propósito.

*Orquestração e enxame*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — centro de integração com um contrato real de relatório de saúde gRPC/Protobuf e uma máquina de estados de missões.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — fila real de trabalhos por prioridade com deduplicação, sobre uma API HTTP real.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — planeador real de trajetórias 3D baseado em RRT com validação real de colisões com obstáculos e espaço de trabalho.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — sincronização real de estado CRDT LWW-Element-Map, testada por propriedades para a convergência de várias células.

*Gémeo digital e simulação*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — centro de integração do motor de gémeo digital, com um contrato real de sincronização de compatibilidade de versões.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — interlock de segurança real de hardware-in-the-loop que encaminha comandos entre a simulação e o hardware real.
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — cinemática direta real e validação de limites de juntas sobre um subconjunto real de URDF.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — gerador procedural real de cenas 2D com exportação de anotações YOLO/COCO.

*Dados e análise*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — armazém real de séries temporais sobre sqlite3 com uma API HTTP real de ingestão/consulta.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — detetor real de anomalias por FFT e linha de base estatística, com monitorização de deriva.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — cálculo real de OEE/disponibilidade sobre o histórico do DATALAKE, com exportação CSV reprodutível.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — pipeline real de ingestão CAN/WebSocket para o DATALAKE, com deduplicação por sequência.

*Gateway industrial*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — centro de integração que retransmite para protocolos industriais, com uma camada real de lista de comandos permitidos e contrapressão.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — espaço de endereços OPC-UA real, verificado com uma sessão de cliente real do protocolo binário.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — broker MQTT real com autenticação opcional por cliente e ACL de tópicos.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — endpoints XML MTConnect `/probe` e `/current` reais com saída em modo degradado.

*Ferramentas complementares*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — painéis de Resumos Inteligentes e Realce de Anomalias sobre o DATALAKE/ANOMALY-DETECTOR, com um recurso estatístico honesto.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — CLI da frota com um contrato de códigos de saída real e estável, um cliente vivo genuíno da API do HYDRA-UMC-SERVER.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — aplicação companheira WearOS com alertas hápticos reais e um relé de voz para o telemóvel emparelhado.
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — catálogo de capacidades de adaptadores externos, só GET por desenho.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware de um rack de montagem de placas com descodificação real do ID da ferramenta e lógica de pré-aquecimento Smart Idle.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware mais um companheiro de visão em Python real para uma cabeça de ferramenta de inspeção térmica/RGB.

---

## 📚 Documentação e comunidade

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — cada subcomando, as suas opções e o contrato de códigos de saída.
- **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — a forma JSON real de `MaintenanceIncident`/`NodeSnapshot`.
- **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — o contrato real da Entrega 2, fornecedores, credenciais e fronteira de segurança.
- **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — o contrato real das Entregas 3-5, a sequência completa preparar/aplicar/verificar/promover e um exemplo de fluxo real do operador.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — pilha tecnológica e diretrizes de código para um pull request.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — as normas de comportamento esperadas nesta comunidade.
- **[SECURITY.md](SECURITY.md)** — como comunicar uma vulnerabilidade e as áreas de segurança em que este projeto se concentra.
- **[SUPPORT.md](SUPPORT.md)** — onde fazer perguntas e comunicar erros.

## 👤 AUTOR
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LICENÇA

GPL-3.0 (software) / CC BY-SA 4.0 (documentação) - veja [LICENSE.md](LICENSE.md).

