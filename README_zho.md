<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | 🇨🇳 <b>简体中文</b> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🔎 面向整个生态系统的只读维护事件可观测性

<p align="center">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="stdlib-only core">
  <img src="https://img.shields.io/badge/Roles-Edge%20(CM5)%20%7C%20Control--plane-367BF5.svg" alt="边缘与控制面角色">
</p>

> **状态：v0.0.7，脚手架阶段——6 项交付中的第 1-5 项(证据、诊断、经人工批准的变更、金丝雀部署、验证)。**
> 每一个子命令都是真实功能，并已进行端到端测试——`control diagnose` 针对模拟的 AI 提供方测试(任何真实提供方都可用，见 [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md))；`control deploy-canary` 针对一个真实的、用后即弃的本地 git 仓库测试(见 [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md))。没有任何事先经过明确人工批准的内容会被部署。交付 6(语音/通知)经过真实调研后被确认为确实受阻，而非只是推迟——见下方的路线图部分。关于当前真实存在的确切命令面，见 [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)。

---

## 1. 🛠️ 技术概述

HYDRA-UMC-OPS-AGENT 是 HYDRA-UMC/URTC 生态系统的维护事件协调器。它拥有唯一一条真实的生命周期——**证据 → 诊断 → 经人工批准的变更 → 通过 HYDRA-UMC-UPDATER 的金丝雀部署 → 验证**——而不重新实现生态系统其他地方已经存在的推理、更新或 MCU 安全逻辑。本项目如今已交付该生命周期六个阶段中的五个：**证据**、**诊断**、**经人工批准的变更**、**金丝雀部署**与**验证**。

两个角色，一个软件包，二者之间尚无网络传输：

1. **边缘角色**(`edge collect`) —— 直接在被观测的机器上运行(一台真实的 CM5 单元，或开发者自己的工作站)。扫描每一个同级检出目录，查找其自身的 `hydra-umc.project.json`，可选地检查一个或多个 systemd 单元和 HTTP 健康端点，并为发现的每一个真实问题派生出一个真实的 `MaintenanceIncident`——一次干净的扫描会产生零个事件，绝不会合成一个"一切正常"的假事件。同一次运行产生的所有事件共享同一个关联 ID。
2. **控制面角色**(`control show`) —— 在开发主机上运行，只读地渲染一个已保存的快照文件：项目清单、健康检查结果，以及按严重程度从高到低排序的所有事件。它从不修改自己读取的文件，本次交付也不会从这里"解决"或确认任何事件。
3. **诊断**(`control diagnose`) —— 同样运行在控制面角色上。把一个已脱敏的事件发送给某个 AI 提供方(任意提供方——Anthropic 与 OpenAI 已内置，见 [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md))，并取回一段以纯文本形式给出的、建议性的根因说明——供人阅读的一条建议，绝不是一个决定。
4. **经人工批准的变更**(`control propose` / `approve` / `reject`) —— 一份真实、不可变的 `ChangeProposal`(一份统一格式的 diff、一段描述、一段理由)，会从 `pending` 状态精确地转变**恰好一次**为 `approved`/`rejected`，且始终归属于一位具名的真实个人。见 [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)。
5. **金丝雀部署**(`control deploy-canary`) —— 除非目标提案处于 `approved` 状态，否则拒绝执行。它把 diff 应用到一个独立的暂存克隆上，在那里执行目标项目自身真实的 build-test 命令，只有在该命令通过后才会提升(将之前的检出保留为真实备份)——在其他任何情况下，真实的检出目录都绝不会被触碰。
6. **验证**(`control verify`) —— 使用交付 1 自身的函数，重新执行最初产生某个事件的那条确切的真实检查，以确认它是否真的已经解决。

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

上面的完整真实操作员流程见 [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)。

本次交付中不存在任何默认/无参数调用方式，也没有图形界面——完整、真实的命令面见 [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)。

## 2. 🧱 架构与设计决策

- **事件是被推导出来的，而不是被声明出来的。** `IncidentBatch` 的 `add_*` 方法在检查对象实际健康时返回 `None`。没有任何代码路径会从一次干净的观测中凭空捏造事件，也没有任何路径会悄悄丢弃一个真实事件。
- **协议边界诚实地降级，而绝不猜测。** `check_systemd_unit_health()` 会在 `systemctl` 不在 `PATH` 中的那一刻立即抛出专门的 `SystemdUnavailableError`——在这台开发机上每次都是如此，在任何没有 systemd 的主机上也是如此——而不是报告一个凭空捏造的"inactive"状态。`check_http_health()` 让真正的网络故障(`status_code is None`)与一个真实但不健康的 HTTP 响应保持可区分。
- **脱敏处理是这里对安全最为关键的一段代码。** `log_redaction.py` 是纯粹、无依赖的文本变换，在被其他任何代码使用之前，已由自身的测试覆盖。键名匹配必须把秘密名称当作真实标识符 token 的子串来查找(如 `DB_PASSWORD`、`api-key`)，而不是当作一个由 `\b` 界定的单词——在正则表达式中 `_` 是单词字符，因此天真的 `\bpassword\b` 永远不会匹配 `DB_PASSWORD`。`MaintenanceIncident.to_dict()` 在序列化时会对 `symptom` 再次执行 `redact_secrets()`，即便调用方早已在上游脱敏过——这是对最有可能携带一段被复制粘贴的日志行的字段所做的纵深防御。
- **`MaintenanceIncident`/`NodeSnapshot` 契约被有意地、逐字段地固定为审计自身"最小契约(CONTRATO MINIMO)"的样子。** 见 [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)。未来某次交付若要对接真实的 AI 提供方或工单系统，理应永远不必在两种不兼容的形状之间做转换。
- **诊断在设计上就与具体提供方无关。** `diagnose_incident()` 只依赖一个最小的 `AIProvider` Protocol——核心代码中从不硬编码任何具名的真实 AI 供应商。Anthropic 与 OpenAI 这两个真实提供方作为可选 extra 内置；调用方也可以传入实现同一单方法契约的任何其他对象。
- **金丝雀部署在真实构建已经证明变更可行之前，绝不会触碰真实检出。** `deploy_canary()` 会拒绝在给定提案的 `status` 尚未变为 `approved` 时执行；随后把 diff 暂存到一个独立的本地克隆中，只有当该项目自身真实的 build-test 命令确实以退出码 `0` 结束时才会提升(两次改名的交换操作，先前的检出以真实备份形式保留)——这与 HYDRA-UMC-UPDATER 自身 `install.py` 已经使用的"经验证后原子化"模式完全一致。
- **一份提案恰好只被裁决一次。** `approve_change()`/`reject_change()` 会对任何非 `pending` 状态的对象抛出 `InvalidTransitionError`——第二次裁决绝不会悄悄覆盖第一次，且每一次裁决都归属于一个真实的、非空的姓名。
- **验证会重新执行完全相同的真实检查，绝不使用更宽松的版本。** `verify_incident_resolved()` 直接调用交付 1 自身的 `check_http_health()`/`check_systemd_unit_health()`——本项目中任何地方都不存在第二套独立且容易产生偏差的健康检查实现。
- **交付 6 是被真实阻塞了，而不是简单地被跳过。** HYDRA-UMC-VOICE-UI 自身真实的契约(`gateway.py`)是一个有边界的、**入站**的"转录到意图"网关，如今没有任何真实的出站通知接口——在这里凭空造一个出来，就等于虚构一个根本不存在的集成点，而这正是本项目自身"绝不捏造"标准所不允许的。见下方的路线图部分。
- **核心部分仅使用标准库。** `edge collect`/`control show`/`control propose`/`control approve`/`control reject`/`control verify` 都不需要任何依赖——HTTP 检查用 `urllib.request`，systemd 检查用 `subprocess`/`shutil.which`，金丝雀部署阶段用 `git`(一个真实的外部二进制程序，而非 Python 包)。只有 `control diagnose` 需要一个可选 extra，且仅针对实际使用的那个提供方。

## 📂 目录结构

```
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/
│   ├── log_redaction.py    # 纯粹的秘密脱敏（KEY=VALUE、Bearer 令牌、PEM 块）
│   ├── inventory.py        # 清单扫描 + systemd/HTTP 健康检查
│   ├── incident.py         # MaintenanceIncident / IncidentBatch 契约
│   ├── edge_agent.py       # 将以上内容编排为单个 NodeSnapshot
│   ├── control_plane.py    # 只读快照加载器 + 文本报告渲染器
│   ├── diagnosis.py        # 交付 2：与提供方无关的、由 AI 辅助生成的诊断建议
│   ├── change_proposal.py  # 交付 3：不可变的、经人工批准的 ChangeProposal 生命周期
│   ├── canary_deploy.py    # 交付 4：stage + apply + verify + promote，仅在获批后执行
│   ├── verification.py     # 交付 5：重新执行某个事件背后的真实检查
│   └── cli.py               # 上述每一项交付的 edge/control 子命令入口点
├── tests/                  # 覆盖全部 10 个模块的真实测试，含一个本地 http.server fixture、一个模拟的 AI 提供方，以及一个用于金丝雀部署的真实、用后即弃的 git 仓库
├── docs/
│   ├── CLI_REFERENCE.md     # 每个子命令、其参数、退出码契约
│   ├── INCIDENT_CONTRACT.md # MaintenanceIncident/NodeSnapshot 的真实 JSON 结构
│   ├── DIAGNOSIS.md         # 交付 2 自身的契约、提供方与安全边界
│   └── CHANGE_LIFECYCLE.md  # 交付 3-5 自身的契约与安全边界
├── images/                 # 媒体资源与应用图标
├── tools/
│   ├── build_test.py        # 不涉及版本变更的构建/编译检查
│   └── ci_validate.py       # CI 使用的清单/CHANGELOG/文档校验
├── build.sh / build.bat     # 创建 venv + 可编辑安装 + 编译检查 + 测试
├── build-test.sh / .bat     # 仅执行构建校验，不修改任何内容
├── run.sh / run.bat         # 真实的 edge collect + control show 演示（不带参数时），或转发一条真实的 CLI 命令
├── bump_version.py          # 生态系统"里程表"式版本递增（pyproject.toml + __init__.py）
└── bump_manifest_version.py # 将 hydra-umc.project.json 的版本与原生版本同步（--sync）
```

## ⚙️ 构建与运行

```bash
chmod +x build.sh   # 仅需一次
./build.sh          # 创建 .venv，pip install -e ".[dev]"，编译检查 + 测试
./run.sh                                          # 真实演示：针对本 GitHub 工作区执行
                                                   # edge collect，然后执行 control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # 或 .[ai-openai] —— 仅 control diagnose 需要
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name 名称 --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control approve proposal.json --approved-by "你的姓名"
./run.sh control deploy-canary proposal.json --live-root 路径 --build-test-command "bash build-test.sh"
./run.sh control verify snapshot.json --incident-id <id>
```

在 Windows 上：先 `build.bat`，然后 `run.bat`（不带参数时执行同一演示）/
`run.bat edge collect ...` / 上面任意一个 `control ...` 子命令。
`build-test.sh`/`.bat` 执行与本项目自身 CI 相同的编译检查(仅 Python 语法)，不会改动项目版本或 CHANGELOG——但它自身并**不**运行测试套件；CI 会将 `pytest` 作为单独的、更晚的一个步骤来运行。要在本地运行完整的测试套件，请执行 `./build.sh`/`build.bat`(或直接执行 `pytest tests/`)。

**故障排查**

- `edge collect` 在每次运行中都报告 `systemdAvailable: false`：这台主机确实在 `PATH` 中没有 `systemctl`（每一台非 Linux 的开发机，以及某些精简版 Linux 容器都是如此）——这是预期中诚实的降级行为，而非缺陷。见 [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)。
- `control show` 以 `ERROR: ...` 失败：快照文件不存在、不是有效的 JSON，或不是真正的快照对象——重新运行 `edge collect` 并检查其自身的 `--out` 路径。
- `control diagnose` 以 `ERROR: the optional '<provider>' package is
  not installed` 失败：根据 `--provider` 执行 `pip install -e
  ".[ai-anthropic]"` 或 `".[ai-openai]"`。
- `control diagnose` 以 `ERROR: no ... API key available` 失败：在运行前先设置 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`。
- `control deploy-canary` 以 `ERROR: refusing to deploy ...` 失败：该提案尚未处于 `approved` 状态——先执行 `control approve`。
- `control deploy-canary` 报告 `promoted: false`：查看结果 JSON 中的 `buildOutput`——暂存环境的构建确实失败了，真实检出从未被触碰。见 [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)。

## 🚀 路线图

交付 1-5（本版本）交付**证据**、**诊断**、**经人工批准的变更**、**金丝雀部署**与**验证**——本项目自身清单和 CHANGELOG 中已经命名的真实生命周期。剩下的部分：

- **交付 6 - 语音/通知集成——真正被阻塞了，而不是仅仅推迟。** 原计划是通过 HYDRA-UMC-VOICE-UI 呈现严重事件或已完成的金丝雀部署。对其自身代码(`gateway.py`)的真实调研发现，它是一个有边界的、**入站**的"转录到意图"网关(一块 Watch 发送文本，收到回复)，如今没有任何真实的出站通知接口。在这里硬造一个出来，就等于虚构一个 VOICE-UI 自身都不存在的集成点——这正是本项目自身"绝不捏造"标准所不允许的。等到 VOICE-UI(或其继任者)真正发展出一种"接收助手通知"的能力后，再重新审视这一点。
- 边缘角色与控制面角色之间的真实传输通道（如今，把快照文件从一端搬到另一端仍是手动步骤）。
- 针对一个已提升的金丝雀事后在生产环境中被证明有问题的回滚命令——`.backup-<id>` 目录是真实存在且会被保留的，但目前恢复它仍是一个手动步骤(见 [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md))。

## 🔗 相关项目

本项目是同一作者(JuanenRac / Electro Hobby 3D)打造的 HYDRA-UMC 机器人生态系统的一部分。值得了解,因为某个请求实际上可能是关于这些项目之一,而非本仓库本身。

**直接相关**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — 检测、安装并更新生态系统中的每一个检出目录；交付 4 中的金丝雀部署正是通过本项目自身已经存在的"经验证后原子化"更新路径来应用已批准的变更，而不是另建一套实现。
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — 另一个"Ecosystem Operations"同族项目：构建一份全新、完全最新的 CM5 镜像,而不是观测一台已经在运行的机器。
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — 具备自身重试/退避与身份不匹配检测能力的真实基于 gRPC 的车队健康看门狗——这是一个与本项目自身基于清单/systemd/HTTP 的证据收集及事件生命周期相关但截然不同的课题(通过 gRPC 实时监测车队节点健康)。

**生态系统中的其他项目**

*核心硬件与平台*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — 机器人手臂的真实主板——CM5 主机 + 双核 STM32H745，通过 CAN-OTA/SPI-OTA 协调最多 8 条工具臂。
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — 面向 CM5 的可复现 Raspberry Pi OS 产品层——只读代理、经过验证的配置/配置文件、WiFi 首次配网。
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — 每个桥接都据此校验自身指令的共享 JSON-Schema 契约与安全门限边界。

*核心后端与客户端*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — 每个控制客户端真正通信的真实无头后端(REST/WebSocket)。
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — 具有实时多机器人 3D 可视化的网页控制面板。
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — 面向多台服务器的桌面(PySide6)集群指挥中心。
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — 具有生物识别登录和配对 Wear OS 伴侣应用的原生 Android 控制应用。
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — 具有实时 WebSocket 同步的 iOS/iPadOS 控制应用(Flutter)。
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — 面向机载 7 英寸 DSI 触摸屏的原生触控界面，直接嵌入 CM5 本体。
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — 将完成的模型推送到 STUDIO 自身目录的桌面版图形化 URDF 创建/编辑工具。
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — 通过真实的 VDA 5050 MQTT 发布者为 AGV/AMR 车队提供的协调边界。
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — 具备真实 GRBL 状态/控制字节访问能力的高层 CNC 单元协调器。
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — 面向足式/人形机器人的协调边界，具备真实的 Boston Dynamics Spot 指令发送器。
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — 读取 3 项真实钥匙/外壳/联锁 GPIO 安全信号的激光单元安全协调器。
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — 面向 OpenPnP 贴片机板级流程的安全高层协调器。
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — 面向 Moonraker/Klipper 3D 打印机的安全协调边界，具备真实的受控作业指令。
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — 具备真实的惰性导入 rclpy ROS 2 传输层的安全协调器。
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — 面向搭载摄像头的无人机的协调边界，具备真实的 MAVLink 指令发送器。

*URTC 工具平台*
- **[URTC](https://github.com/JuanenRac/URTC)** — 面向实体 Universal Robot Tool Controller 板卡的固件，通过 CAN 总线支持 25 种以上工具配置。
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — 面向 URTC 板卡的桌面图形烧录工具，支持 CAN-OTA 以及全芯片 SWD/JTAG。
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — 面向 URTC 板卡的桌面实时 CAN 总线诊断工具，每种工具配置对应一个面板。
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — 通过 Web Serial API 实现的浏览器版 URTC-TESTER 替代方案，无需本地安装。

*视觉 AI 节点(Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — 面向 Hailo-8 视觉流水线的集成中枢，具备逐阶段的真实硬件就绪检测。
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — 具备 Hailo 架构/校验和安全加载验证的真实编译模型注册表。
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — 具备真实 HailoRT 集成边界的真实 GStreamer 流水线 + MediaMTX 配置生成器。
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — 具备真实 Position-Based Visual Servoing 修正律，并依据上游区域状态进行安全门控。
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — 具备校准新鲜度强制检查的真实区域入侵检测与 E-STOP 请求。

*认知 AI 节点(Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — 面向 Hailo-10 认知流水线(LLM/VLA/语音编排)的集成中枢。
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — 面向 Vision-Language-Action 模型的真实动作 token 编解码与轨迹生成。
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — 具备受限、需确认的 Watch 中继的真实语音前端(VAD + 意图解析)——一度被视为本项目交付 6 的通知呈现渠道，但经查实如今并不具备真实的出站通知契约(见路线图部分)。
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — 基于真实规则的任务分解，以及针对 MCU 错误码的语义化错误恢复。
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — 面向本生态系统自身 Markdown 文档的真实纯标准库 TF-IDF 文档检索。

*编排与集群*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — 具备真实 gRPC/Protobuf 健康报告契约与任务状态机的集成中枢。
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — 基于真实 HTTP API 的真实优先级任务队列，支持去重。
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — 具备真实障碍物/工作空间碰撞校验的真实基于 RRT 的三维路径规划器。
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — 经过多单元收敛属性测试的真实 CRDT LWW-Element-Map 状态同步。

*数字孪生与仿真*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — 面向数字孪生引擎的集成中枢，具备真实的版本兼容性同步契约。
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — 在仿真与真实硬件之间路由指令的真实硬件在环安全联锁。
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — 面向真实 URDF 子集的真实正向运动学与关节限位校验。
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — 具备 YOLO/COCO 标注导出功能的真实程序化 2D 场景生成器。

*数据与分析*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — 具备真实数据摄入/查询 HTTP API 的真实 sqlite3 时序数据存储。
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — 具备漂移监测能力的真实 FFT + 统计基线异常检测器。
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — 基于 DATALAKE 历史数据的真实 OEE/可用率计算，支持可复现的 CSV 导出。
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — 面向 DATALAKE 的真实 CAN/WebSocket 数据摄入管道，支持序列去重。

*工业网关*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — 中继至工业协议的集成中枢，具备真实的指令白名单/背压控制层。
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — 经真实二进制协议客户端会话验证的真实 OPC-UA 地址空间。
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — 具备可选按客户端认证与主题 ACL 的真实 MQTT 代理。
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — 具备降级模式输出的真实 MTConnect `/probe` 与 `/current` XML 端点。

*辅助工具*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — 基于 DATALAKE/ANOMALY-DETECTOR 的智能摘要与异常高亮面板，具备诚实的统计回退机制。
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — 具备真实、稳定退出码契约的车队 CLI，是 HYDRA-UMC-SERVER 自身 API 的真实在线客户端。
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — 具备真实触觉提醒与配对手机语音中继功能的 WearOS 伴侣应用。
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — 面向板卡安装机架的固件，具备真实的工具 ID 解码与 Smart Idle 预热逻辑。
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — 面向热成像/RGB 检测工具头的固件及真实 Python 视觉伴侣程序。

---

## 📚 文档与社区

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — 每一个子命令、其参数，以及退出码契约。
- **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — `MaintenanceIncident`/`NodeSnapshot` 的真实 JSON 结构。
- **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — 交付 2 自身真实的契约、提供方、凭据与安全边界。
- **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — 交付 3-5 自身真实的契约、完整的 stage/apply/verify/promote 流程，以及一个真实的操作员流程示例。
- **[CONTRIBUTING.md](CONTRIBUTING.md)** —— 提交 Pull Request 所需的技术栈和编码规范。
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** —— 本社区所期望的行为准则。
- **[SECURITY.md](SECURITY.md)** —— 如何报告漏洞，以及本项目真实的安全关注重点。
- **[SUPPORT.md](SUPPORT.md)** —— 在哪里提问和报告缺陷。

## 👤 作者
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 许可证

GPL-3.0（软件）/ CC BY-SA 4.0（文档）—— 详见 [LICENSE.md](LICENSE.md)。
