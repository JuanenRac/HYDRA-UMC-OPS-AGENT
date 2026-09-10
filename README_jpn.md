<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-OPS-AGENT banner" width="100%">
</p>

# 🩺 HYDRA-UMC-OPS-AGENT

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | 🇯🇵 <b>日本語</b></p>

### 🔎 エコシステム全体を対象とした、読み取り専用の保守インシデント可観測性

<p align="center">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="stdlib-only core">
  <img src="https://img.shields.io/badge/Roles-Edge%20(CM5)%20%7C%20Control--plane-367BF5.svg" alt="エッジとコントロールプレーンの役割">
</p>

> **ステータス: v0.0.8、scaffolding - 6 件の納品のうち第 1-5 弾(証拠、
> 診断、人による承認済みの変更、カナリアデプロイ、検証)。** すべての
> サブコマンドが本物であり、エンドツーエンドでテスト済みです——
> `control diagnose` は模擬の AI プロバイダーに対して(本物のプロバイ
> ダーであればどれでも動作します、
> [docs/DIAGNOSIS.md](docs/DIAGNOSIS.md) を参照)、`control
> deploy-canary` は本物の使い捨てローカル git リポジトリに対して(
> [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) を参照)。明示
> 的な人による承認が事前になければ、何もデプロイされることはありませ
> ん。納品 6(音声/通知)は調査の結果、単に先送りされているのではなく、
> 本当にブロックされていることが判明しました——詳しくは下記のロード
> マップ節を参照してください。今日実在する正確なコマンド面については
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) を参照してください。

---

## 1. 🛠️ 技術概要

HYDRA-UMC-OPS-AGENT は、HYDRA-UMC/URTC エコシステムの保守インシデント
コーディネーターです。唯一の実際のライフサイクル——**証拠 → 診断 →
人による承認済みの変更 → HYDRA-UMC-UPDATER 経由のカナリアデプロイ →
検証**——を担い、エコシステムの他の場所に既に存在する推論・更新・MCU
安全ロジックを再実装することはありません。本プロジェクトは今や、そ
のライフサイクルの 6 段階のうち 5 段階を届けています: **証拠**、
**診断**、**人による承認済みの変更**、**カナリアデプロイ**、そして
**検証**です。

2 つの役割、1 つのパッケージ、両者間のネットワーク転送はまだ存在しま
せん:

1. **エッジ役割** (`edge collect`) - 観測対象のマシン(実際の CM5 セル、
   または開発者自身のワークステーション)上で直接実行されます。兄弟
   関係にある各チェックアウトを、それぞれ自身の
   `hydra-umc.project.json` を求めてスキャンし、任意で 1 つ以上の
   systemd ユニットと HTTP ヘルスエンドポイントをチェックし、見つかっ
   た実際の問題ごとに本物の `MaintenanceIncident` を導出します——きれ
   いなスキャンはゼロ件のインシデントを生み、合成された「全て OK」を
   生むことは決してありません。同じ実行から生まれたすべてのインシデ
   ントは 1 つの相関 ID を共有します。
2. **コントロールプレーン役割** (`control show`) - 開発ホスト上で実行
   され、保存されたスナップショットファイルを読み取り専用でレンダリ
   ングします: プロジェクト一覧、ヘルスチェック結果、そして最も深刻な
   ものから順に並べられたすべてのインシデント。読み取るファイルを決
   して変更せず、この納品ではここからインシデントを「解決」したり確
   認したりすることもありません。
3. **診断** (`control diagnose`) - こちらもコントロールプレーン役割
   で実行されます。既に秘匿化済みのインシデントを AI プロバイダー
   (任意のプロバイダー——Anthropic と OpenAI が標準で組み込まれてい
   ます、[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md) を参照)に送信し、提
   案された根本原因の説明をプレーンテキストで受け取ります——人が読む
   ための提案であり、決して決定ではありません。
4. **人による承認済みの変更** (`control propose` / `approve` /
   `reject`) - 本物で不変の `ChangeProposal`(統一 diff、説明、根拠)
   が `pending` から `approved`/`rejected` へと**正確に一度だけ**遷移
   し、常に実名の実在する人物に帰属します。
   [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) を参照してく
   ださい。
5. **カナリアデプロイ** (`control deploy-canary`) - `approved` 状態の
   提案以外に対しては実行を拒否します。diff を独立したステージングク
   ローンに適用し、そこでターゲットプロジェクト自身の本物の
   build-test コマンドを実行し、それが成功した場合にのみ(以前のチェ
   ックアウトを本物のバックアップとして保持しながら)昇格します——それ
   以外の場合、実際のチェックアウトが触られることは決してありません。
6. **検証** (`control verify`) - 納品 1 自身の関数を使って、そのイン
   シデントを最初に発生させた正確に同じ実際のチェックを再実行し、そ
   れが本当に解決されたことを確認します。

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

上記の完全かつ本物のオペレーターフローについては
[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) を参照してくださ
い。この納品にはデフォルト/無引数の呼び出しも GUI も存在しません——
完全かつ本物のコマンド面については
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) を参照してください。

## 2. 🧱 アーキテクチャと設計上の決定

- **インシデントは導出されるものであり、宣言されるものではありません。**
  `IncidentBatch` の `add_*` メソッドは、調べた対象が実際に健全だった
  場合に `None` を返します。きれいな観測からインシデントを捏造する
  コードパスはなく、本物のインシデントを黙って捨てるコードパスもあり
  ません。
- **プロトコル境界は正直に劣化し、決して推測しません。**
  `check_systemd_unit_health()` は、`systemctl` が `PATH` に無い瞬間
  に専用の `SystemdUnavailableError` を送出します——これはこの開発マ
  シンでは毎回、また systemd を持たないあらゆるホストでも起こります
  ——捏造した「inactive」ステータスを報告する代わりに。
  `check_http_health()` は、本物のネットワーク障害(`status_code is
  None`)を、本物だが健全でない HTTP 応答と区別可能なままにします。
- **redaction(秘匿化)は、ここで最もセキュリティ上重要なコードです。**
  `log_redaction.py` は純粋で依存関係のないテキスト変換であり、他の
  何かがそれを利用する前に、それ自身のテストでカバーされています。
  キー名の一致は、秘密の名前を本物の識別子トークン(`DB_PASSWORD`、
  `api-key`)の部分文字列として探す必要があり、`\b` で区切られた単語
  として探してはいけません——正規表現では `_` は単語文字なので、素朴
  な `\bpassword\b` は `DB_PASSWORD` に決して一致しません。
  `MaintenanceIncident.to_dict()` は、呼び出し元が既に上流で秘匿化し
  ていたとしても、シリアライズ時に `symptom` に対して再度
  `redact_secrets()` を実行します——コピー&ペーストされたログ行を運ぶ
  可能性が最も高いフィールドに対する多層防御です。
- **`MaintenanceIncident`/`NodeSnapshot` 契約は、監査自身の「CONTRATO
  MINIMO(最小契約)」に意図的にフィールド単位で固定されています。**
  [docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md) を参照してく
  ださい。本物の AI プロバイダーやチケットシステムと話す将来の納品は、
  2 つの非互換な形の間で変換する必要が決してあってはなりません。
- **診断はプロバイダーに依存しない設計です。** `diagnose_incident()`
  は最小限の `AIProvider` プロトコルのみに依存しており、特定の AI ベ
  ンダーがコアロジックにハードコードされることは決してありません。2
  つの実際のプロバイダー(Anthropic、OpenAI)がオプションの extra とし
  て同梱されており、呼び出し元は同じ 1 メソッド契約を実装する任意の
  他のオブジェクトを渡すこともできます。
- **カナリアデプロイは、本物のビルドが変更が機能することを既に証明す
  るまで、本番のチェックアウトに一切触れません。** `deploy_canary()`
  は、与えられた提案自身の `status` が `approved` でない限り実行を拒
  否し、その後 diff を独立したローカルクローンにステージングし、その
  プロジェクト自身のビルドテストコマンドが本当にコード `0` で終了し
  た場合にのみ昇格します(2 回のリネームによるスワップ、以前のチェッ
  クアウトは本物のバックアップとして保持)——これは HYDRA-UMC-UPDATER
  自身の `install.py` が既に使用しているのと同じ「検証を経てからの原
  子的」パターンです。
- **提案は正確に一度だけ決定されます。** `approve_change()`/
  `reject_change()` は、`pending` 以外の状態に対して呼び出されると必
  ず `InvalidTransitionError` を送出します——2 度目の決定が最初の決定
  を黙って上書きすることは決してなく、すべての決定は本物の空でない名
  前に帰属します。
- **検証は同じ本物のチェックを再実行します。決して緩いチェックではあ
  りません。** `verify_incident_resolved()` は、納品 1 自身の
  `check_http_health()`/`check_systemd_unit_health()` を直接呼び出し
  ます——このプロジェクトのどこにも、独立してドリフトしうる第二のヘ
  ルスチェック実装は存在しません。
- **納品 6 はブロックされているのであり、単に省略されているのではあ
  りません。** HYDRA-UMC-VOICE-UI 自身の本物の契約(`gateway.py`)は、
  今日時点で本物のアウトバウンド通知機能を持たない、限定的でインバウ
  ンドのトランスクリプトからインテントへのゲートウェイです——ここで
  一つ発明することは、存在しない統合を捏造することを意味し、それはこ
  のプロジェクト自身の基準が許しません。下記のロードマップのセクショ
  ンを参照してください。
- **コアには標準ライブラリのみを使用します。** `edge collect`/
  `control show`/`control propose`/`control approve`/`control
  reject`/`control verify` は、依存関係を一切必要としません——HTTP
  チェックには `urllib.request`、systemd チェックには
  `subprocess`/`shutil.which`、カナリアデプロイの段階には `git`
  (Python パッケージではなく、本物の外部バイナリ)を使用します。オプ
  ションの extra を必要とするのは `control diagnose` だけで、それも
  実際に使用するプロバイダー分のみです。

## 📂 リポジトリ構成

```
HYDRA-UMC-OPS-AGENT/
├── src/hydra_umc_ops_agent/
│   ├── log_redaction.py    # 純粋な秘密の秘匿化(KEY=VALUE、Bearer トークン、PEM ブロック)
│   ├── inventory.py        # マニフェストスキャン + systemd/HTTP ヘルスチェック
│   ├── incident.py         # MaintenanceIncident / IncidentBatch 契約
│   ├── edge_agent.py       # 上記を単一の NodeSnapshot にオーケストレーション
│   ├── control_plane.py    # 読み取り専用スナップショットローダー + テキストレポートレンダラー
│   ├── diagnosis.py        # 納品 2: プロバイダーに依存しない AI 支援診断の提案
│   ├── change_proposal.py  # 納品 3: 不変で人による承認済みの ChangeProposal ライフサイクル
│   ├── canary_deploy.py    # 納品 4: ステージング + 適用 + 検証 + 昇格、承認済みのみ
│   ├── verification.py     # 納品 5: インシデントの背後にある本物のチェックを再実行
│   └── cli.py               # 上記すべての納品向けの edge/control サブコマンドエントリーポイント
├── tests/                  # 10 モジュールすべてに対する本物のテスト、ローカル http.server フィクスチャ、模擬 AI プロバイダー、カナリアデプロイ用の本物の使い捨て git リポジトリを含む
├── docs/
│   ├── CLI_REFERENCE.md     # すべてのサブコマンド、そのフラグ、終了コード契約
│   ├── INCIDENT_CONTRACT.md # MaintenanceIncident/NodeSnapshot の本物の JSON 形
│   ├── DIAGNOSIS.md         # 納品 2 自身の契約、プロバイダーと安全境界
│   └── CHANGE_LIFECYCLE.md  # 納品 3-5 自身の契約と安全境界
├── images/                 # メディアとアプリアイコン
├── tools/
│   ├── build_test.py        # バージョン管理を伴わないビルド/コンパイルチェック
│   └── ci_validate.py       # CI が使用するマニフェスト/CHANGELOG/ドキュメントの検証
├── build.sh / build.bat     # venv + 編集可能インストール + コンパイルチェック + テスト
├── build-test.sh / .bat     # 何も変更しない、ビルド検証のみ
├── run.sh / run.bat         # 本物の edge collect + control show デモ(引数なしの場合)、または本物の CLI コマンドを転送
├── bump_version.py          # エコシステム全体の「走行距離計」式インクリメント(pyproject.toml + __init__.py)
└── bump_manifest_version.py # hydra-umc.project.json のバージョンをネイティブのものと同期(--sync)
```

## ⚙️ ビルドと実行

```bash
chmod +x build.sh   # 初回のみ
./build.sh          # .venv を作成、pip install -e ".[dev]"、コンパイルチェック + テスト
./run.sh                                          # 本物のデモ: この GitHub ワークスペースに対して
                                                   # edge collect を実行し、その後 control show
./run.sh edge collect --node-name n --projects-root DIR --out FILE
./run.sh control show snapshot.json
pip install -e ".[ai-anthropic]"                  # または .[ai-openai] - control diagnose にのみ必要
ANTHROPIC_API_KEY=sk-ant-... ./run.sh control diagnose snapshot.json --incident-id <id>
./run.sh control propose snapshot.json --incident-id <id> --project-name NAME --description "..." --diff-file fix.diff --rationale "..." --out proposal.json
./run.sh control approve proposal.json --approved-by "あなたの名前"
./run.sh control deploy-canary proposal.json --live-root PATH --build-test-command "bash build-test.sh"
./run.sh control verify snapshot.json --incident-id <id>
```

Windows では: 先に `build.bat`、その後 `run.bat`(引数なしの場合は同じ
デモ) / `run.bat edge collect ...` / 上記の `control ...` サブコマン
ドのいずれか。`build-test.sh`/`.bat` は、このプロジェクト自身の CI
が実行するのと同じコンパイルチェック(Python の構文のみ)を、プロジ
ェクトのバージョンや CHANGELOG に触れずに実行します——ただしそれ自
体はテストスイートを実行しません。CI は `pytest` を別の、より後の
ステップとして実行します。完全なローカルテストスイートには
`./build.sh`/`build.bat`(または直接 `pytest tests/`)を実行してくだ
さい。

**トラブルシューティング**

- `edge collect` が毎回の実行で `systemdAvailable: false` を報告する:
  このホストには本当に `PATH` に `systemctl` がありません(非 Linux の
  開発マシンすべて、および一部の最小限の Linux コンテナ)——これは想
  定どおりの正直な劣化であり、バグではありません。
  [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) を参照してください。
- `control show` が `ERROR: ...` で失敗する: スナップショットファイル
  が存在しないか、有効な JSON でないか、本物のスナップショットオブジ
  ェクトではありません——`edge collect` を再実行し、その `--out` パス
  を確認してください。
- `control diagnose` が `ERROR: the optional '<provider>' package is
  not installed` で失敗する: `--provider` に合わせて先に
  `pip install -e ".[ai-anthropic]"` または `".[ai-openai]"` を実行し
  てください。
- `control diagnose` が `ERROR: no ... API key available` で失敗す
  る: 実行前に `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` を設定してくださ
  い。
- `control deploy-canary` が `ERROR: refusing to deploy ...` で失敗す
  る: その提案がまだ `approved` になっていません——先に
  `control approve` を実行してください。
- `control deploy-canary` が `promoted: false` を報告する: 結果 JSON
  内の `buildOutput` を読んでください——ステージングビルドが本当に失
  敗しており、本番のチェックアウトには一切触れられていません。
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) を参照してく
  ださい。

## 🚀 ロードマップ

納品 1-5(このバージョン)は**証拠**、**診断**、**人による承認済みの
変更**、**カナリアデプロイ**、**検証**を届けます——このプロジェクト
自身のマニフェストと CHANGELOG に既に名付けられている本物のライフサ
イクルです。残っているもの:

- **納品 6 - 音声/通知の統合 - 単に先送りされているのではなく、本当
  にブロックされています。** 計画では、重大なインシデントや完了した
  カナリアを HYDRA-UMC-VOICE-UI 経由で表面化する予定でした。その本物
  のコード(`gateway.py`)の実際の調査により、それは限定的で INBOUND
  (受信専用)のトランスクリプトからインテントへのゲートウェイである
  こと(Watch がテキストを送信し、返信を受け取る)が判明し、今日時点
  で本物のアウトバウンド通知/プッシュ機能を持ちません。ここで一つ構
  築することは、VOICE-UI 自身が持っていない統合ポイントを発明するこ
  とを意味し、このプロジェクト自身の捏造禁止基準がそれを許しません。
  VOICE-UI(またはその後継)が本物の「インバウンドのアシスタント告
  知」機能を自ら備えるようになったら、これを再検討します。
- エッジ役割とコントロールプレーン役割の間の本物の転送手段(現在、両
  者の間でスナップショットファイルを移動するのは手動のステップです)。
- 実行時に後から誤りだと判明した、既に昇格したカナリアのためのロール
  バックコマンド——`.backup-<id>` ディレクトリは本物で保持されます
  が、それを今日復元するのは手動のステップです(
  [docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md) を参照)。

## 🔗 関連プロジェクト

本プロジェクトは、同じ作者(JuanenRac / Electro Hobby 3D)による HYDRA-UMC ロボティクスエコシステムの一部です。リクエストが実はこの中のどれかについてのものである可能性があるため、知っておく価値があります。

**直接関連**
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — エコシステムのすべてのチェックアウトを検出・インストール・更新する。納品 4 のカナリアデプロイは、第二の実装ではなく、本プロジェクト自身の既存の「検証を経てからの原子的」更新パスを通じて承認済みの変更を適用する。
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — もう一つの「Ecosystem Operations」の兄弟プロジェクト: 既に稼働中のものを観測するのではなく、新しく完全に最新の CM5 イメージを構築する。
- **[HYDRA-UMC-DEV-SERVER](https://github.com/JuanenRac/HYDRA-UMC-DEV-SERVER)** — 再現可能な開発ホスト。候補をビルドし、その永続タスクキューを本プロジェクト自身のインシデントライフサイクルと協調させる。自分自身のタスクを承認することは決してない。
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — 独自のリトライ/バックオフとアイデンティティ不一致検出を備えた、実際の gRPC ベースのフリートヘルスウォッチドッグ——本プロジェクト自身のマニフェスト/systemd/HTTP による証拠収集とインシデントライフサイクルとは関連するが別個の課題(gRPC 経由のフリートノードのライブ健全性)。

**エコシステムの他のプロジェクト**

*コアハードウェア&プラットフォーム*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — 実際のロボットアームのマザーボード——CM5 ホスト + デュアルコア STM32H745、CAN-OTA/SPI-OTA 経由で最大 8 本のツールアームを統括。
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — CM5 向けの再現可能な Raspberry Pi OS プロダクト層——読み取り専用エージェント、検証済み設定/プロファイル、WiFi 初回接続プロビジョニング。
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — すべてのブリッジが自身のコマンドを検証する共有 JSON-Schema 契約と安全ゲートの境界。

*コアバックエンド&クライアント*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — すべての制御クライアントが実際に通信する、本物のヘッドレスバックエンド(REST/WebSocket)。
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — リアルタイムのマルチロボット 3D 可視化を備えたウェブ制御ダッシュボード。
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — 複数のサーバーを同時に扱えるデスクトップ(PySide6)スウォームコマンドセンター。
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — 生体認証ログインとペアリングされた Wear OS コンパニオンを備えたネイティブ Android 制御アプリ。
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — リアルタイム WebSocket 同期を備えた iOS/iPadOS 制御アプリ(Flutter)。
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — 本体搭載の 7 インチ DSI タッチスクリーン向けネイティブタッチ UI、CM5 自体に組み込み。
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — 完成したモデルを STUDIO 自身のカタログへ送信するデスクトップ用グラフィカル URDF 作成/編集ツール。
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — 実際の VDA 5050 MQTT パブリッシャーによる AGV/AMR フリートの調整境界。
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — 実際の GRBL ステータス/制御バイトへのアクセスを持つ、CNC セルの高レベルコーディネーター。
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — 実際の Boston Dynamics Spot コマンド送信機能を持つ、脚型/ヒューマノイドドロイドの調整境界。
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — 実際のキー/筐体/インターロック GPIO セーフガード 3 系統を読み取る、レーザーセルの安全コーディネーター。
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — OpenPnP ピックアンドプレースの基板フローを安全に統括する高レベルコーディネーター。
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — 実際にゲート制御されたジョブコマンドを持つ、Moonraker/Klipper 3D プリンター向けの安全な調整境界。
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — 実際の遅延インポート rclpy ROS 2 トランスポートを持つ安全コーディネーター。
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — 実際の MAVLink コマンド送信機能を持つ、カメラ搭載 UAV の調整境界。

*URTC ツールプラットフォーム*
- **[URTC](https://github.com/JuanenRac/URTC)** — 物理的な Universal Robot Tool Controller 基板向けファームウェア、CAN バス経由の 25 以上のツールプロファイル。
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — URTC 基板用のデスクトップ GUI 書き込みツール、CAN-OTA およびフルチップ SWD/JTAG。
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — URTC 基板向けのデスクトップ CAN バスライブ診断ツール、ツールプロファイルごとに 1 パネル。
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — Web Serial API を使ったブラウザベースの URTC-TESTER の代替、ローカルインストール不要。

*ビジョン AI ノード(Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — Hailo-8 ビジョンパイプラインの統合ハブ、段階ごとの実際のハードウェア準備状況チェック付き。
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — Hailo アーキテクチャ/チェックサムによる安全読み込み検証を備えた、実際のコンパイル済みモデルレジストリ。
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — 実際の HailoRT 統合境界を持つ、実際の GStreamer パイプライン + MediaMTX 設定生成器。
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — 上流のゾーン状態に応じて安全ゲート制御される、実際の Position-Based Visual Servoing 補正則。
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — キャリブレーションの鮮度を強制する、実際のゾーン侵入チェックと E-STOP 要求。

*コグニティブ AI ノード(Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — Hailo-10 コグニティブパイプライン(LLM/VLA/音声オーケストレーション)の統合ハブ。
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — Vision-Language-Action モデル向けの、実際のアクショントークンのエンコード/デコードと軌道生成。
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — 確認ゲート付きの限定的な Watch リレーを備えた、実際の音声フロントエンド(VAD + 意図解析)——かつて本プロジェクトの納品 6 の通知の受け皿として検討されたが、今日時点で本物のアウトバウンド通知契約を持たないことが判明した(ロードマップのセクションを参照)。
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — MCU エラーコードに対する、実際のルールベースのタスク分解と意味的エラー復旧。
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — このエコシステム自身の Markdown ドキュメントに対する、標準ライブラリのみの実際の TF-IDF 文書検索。

*オーケストレーション&スウォーム*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — 実際の gRPC/Protobuf ヘルスレポート契約とミッションステートマシンを持つ統合ハブ。
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — 実際の HTTP API 上に構築された、優先度ベースの実際のジョブキュー(重複排除付き)。
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — 実際の障害物/ワークスペース衝突検証を備えた、実際の RRT ベースの 3D 経路プランナー。
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — 複数セルの収束についてプロパティテストされた、実際の CRDT LWW-Element-Map 状態同期。

*デジタルツイン&シミュレーション*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — 実際のバージョン互換性同期契約を持つ、デジタルツインエンジンの統合ハブ。
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — シミュレーションと実際のハードウェアの間でコマンドをルーティングする、実際のハードウェア・イン・ザ・ループ安全インターロック。
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — 実際の URDF サブセットに対する、実際の順運動学と関節限界検証。
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — YOLO/COCO アノテーションのエクスポート機能を持つ、実際のプロシージャル 2D シーンジェネレーター。

*データ&分析*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — 実際の取り込み/クエリ HTTP API を備えた、実際の sqlite3 ベースの時系列ストア。
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — ドリフト監視を備えた、実際の FFT + 統計ベースラインによる異常検知器。
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — DATALAKE の履歴に対する実際の OEE/稼働率計算、再現可能な CSV エクスポート付き。
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — シーケンス重複排除機能を備えた、DATALAKE への実際の CAN/WebSocket 取り込みパイプライン。

*産業用ゲートウェイ*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — 実際のコマンド許可リスト/バックプレッシャー層を持つ、産業用プロトコルへ中継する統合ハブ。
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — 実際のバイナリプロトコルクライアントセッションで検証された、実際の OPC-UA アドレス空間。
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — クライアント単位のオプション認証とトピック ACL を備えた、実際の MQTT ブローカー。
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — 縮退モード出力を備えた、実際の MTConnect `/probe` および `/current` XML エンドポイント。

*補完ツール*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — 誠実な統計フォールバックを備えた、DATALAKE/ANOMALY-DETECTOR 上のスマートサマリーと異常ハイライトパネル。
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — 実際の安定した終了コード契約を持つフリート CLI、HYDRA-UMC-SERVER 自身の API の本物のライブクライアント。
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — 実際の触覚アラートとペアリングされたスマートフォンへの音声リレーを備えた WearOS コンパニオンアプリ。
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — 実際の工具 ID デコードと Smart Idle 予熱ロジックを備えた、基板搭載ラック用ファームウェア。
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — サーマル/RGB 検査ツールヘッド向けの、ファームウェアと実際の Python ビジョンコンパニオン。

---

## 📚 ドキュメント & コミュニティ

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — すべてのサブコマンド、そのフラグ、終了コード契約。
- **[docs/INCIDENT_CONTRACT.md](docs/INCIDENT_CONTRACT.md)** — `MaintenanceIncident`/`NodeSnapshot` の本物の JSON 形。
- **[docs/DIAGNOSIS.md](docs/DIAGNOSIS.md)** — 納品 2 自身の本物の契約、プロバイダー、認証情報、安全境界。
- **[docs/CHANGE_LIFECYCLE.md](docs/CHANGE_LIFECYCLE.md)** — 納品 3-5 自身の本物の契約、ステージング/適用/検証/昇格の完全な流れ、そして本物のオペレーターフローの例。
- **[CONTRIBUTING.md](CONTRIBUTING.md)** —— プルリクエストのための技術スタックとコーディング指針。
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** —— このコミュニティで期待される行動規範。
- **[SECURITY.md](SECURITY.md)** —— 脆弱性の報告方法と、このプロジェクトの実際のセキュリティ重点領域。
- **[SUPPORT.md](SUPPORT.md)** —— 質問の投稿先とバグの報告先。

## 👤 作者
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 ライセンス

GPL-3.0(ソフトウェア)/ CC BY-SA 4.0(ドキュメント)—— 詳細は [LICENSE.md](LICENSE.md) を参照してください。
