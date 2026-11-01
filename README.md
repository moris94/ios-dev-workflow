# ios-dev-workflow — iOS App Factory plugin for Claude Code

アプリのアイデアを 1 つ渡すと、**競合・需要調査 → 企画書 → 憲章 → MVP（課金必須・買い切り優先）→ デザイン → サポート/プライバシーページ公開 → ASO → アプリアイコン → SwiftUI 実装 → 日英ローカライズ → 単体/UI 試験 → ストア用スクリーンショット → App Store Connect 設定 → TestFlight → リリース準備確認** までを自動で進める、再利用可能な Claude Code プラグイン **`ios-app-factory`** です。

各工程は明示的な成果物（JSON Schema 付き）でつながり、機械的に検証できる品質ゲートを通過しないと次へ進みません。状態はリポジトリに保存されるので、セッションが切れても途中から再開できます。**審査提出と公開は、人間が自分の端末で承認したときだけ実行されます。**（Hooks と実行スクリプトの両方で強制）

```
/plugin marketplace add moris94/ios-dev-workflow
/plugin install ios-app-factory@ios-dev-workflow
```

（Claude Code 2.1.275 以降は 1 行で: `/plugin install ios-app-factory --marketplace moris94/ios-dev-workflow`）

---

## 目次
1. [できること](#できること)
2. [リポジトリ構成](#リポジトリ構成)
3. [必要環境](#必要環境)
4. [インストール](#インストール)
5. [初期設定](#初期設定)
6. [実行方法](#実行方法)
7. [ワークフローと品質ゲート](#ワークフローと品質ゲート)
8. [成果物](#成果物)
9. [状態管理・再開・重複防止・仕様変更](#状態管理再開重複防止仕様変更)
10. [App Store Connect 連携](#app-store-connect-連携)
11. [人間の承認による審査提出・公開](#人間の承認による審査提出公開)
12. [設定リファレンス](#設定リファレンス)
13. [Git に保存するもの・しないもの](#git-に保存するものしないもの)
14. [プラグイン自体のテスト](#プラグイン自体のテスト)
15. [トラブルシューティング](#トラブルシューティング)
16. [検証状況と制約](#検証状況と制約)

詳細設計: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## できること

| 工程 | 担当 Subagent | Skill | 主な成果物 |
|---|---|---|---|
| 1. 競合・需要調査 | market-researcher | market-research | `research.json/.md`（出典付き） |
| 2. 企画書 | product-manager | product-proposal | `proposal.json/.md` |
| 3. 憲章 | product-manager | product-charter | `charter.json/.md` |
| 4. MVP 仕様（課金必須・買い切り優先） | product-manager | mvp-spec, storekit-monetization | `mvp.json/.md` |
| 5. デザインコンセプト | product-designer | design-concept | `design.json/.md` → `DesignTokens.swift` |
| 6. サポート＋プライバシーポリシーページ（日英・1 ページ）を Notion で公開 | release-manager | support-page | `page.md`, `publication.json` |
| 7. ASO メタデータ・キャプション | product-manager | aso-copywriting | `aso.json` |
| 8. アプリアイコン（デザイン・憲章・ASO から） | product-designer | app-icon | `icon.json` → `AppIcon.appiconset`（ライト/ダーク/ティント） |
| 9. SwiftUI 実装＋ビルド検証 | ios-developer | swiftui-implementation, storekit-monetization | `App/`, `AppTests/`, `build.json` |
| 10. 日英ローカライズ | ios-developer | localization | `*.xcstrings` |
| 11. 単体・UI 試験 | qa-engineer | ios-testing | `AppUITests/`, `tests.json` |
| 12. ストア用スクリーンショット | product-designer | store-screenshots | `factory/screenshots/**` |
| 13. App Store Connect 設定 | release-manager | asc-sync | `factory/asc/plan.json`, ledger |
| 14. TestFlight | release-manager | testflight-release | `testflight.json` |
| 15. リリース準備確認 | release-manager | testflight-release | `readiness.json` |
| 16. 審査提出（**人間承認**） | release-manager | release-approval | `submission.json` |
| 17. 公開（**人間承認**） | release-manager | release-approval | `release.json` |

全体の制御は **Orchestrator Skill**（`/ios-app-factory:factory`）がメイン会話で行います（Subagent は Subagent を起動できないため）。

## リポジトリ構成

```
.claude-plugin/marketplace.json        # このリポジトリ = マーケットプレイス
plugins/ios-app-factory/
├── .claude-plugin/plugin.json          # プラグインマニフェスト
├── skills/                             # 18 Skills（オーケストレーター + 専門領域）
├── agents/                             # 6 Subagents（調査/PM/デザイン/開発/QA/リリース）
├── hooks/hooks.json, run_hook.py       # PreToolUse(Bash, Write/Edit) + SessionStart
├── bin/app-factory                     # ワークフロー CLI（プラグイン有効時は PATH 上）
├── lib/appfactory/                     # Python エンジン
│   ├── pipeline.json                   # 工程定義（依存・入出力・ゲート・担当）
│   ├── schemas/*.schema.json           # 成果物の JSON Schema
│   ├── engine.py, locking.py           # 状態・ロック・ダイジェスト・stale 検出
│   ├── gates/                          # 工程ごとの品質ゲート
│   ├── asc/                            # App Store Connect: JWT, client, planner, executor, ledger, simulator
│   ├── screenshots/                    # 再現可能なスクリーンショット合成
│   ├── approval.py, guards.py          # 人間承認・Hook ロジック
│   └── codegen.py, l10n.py, release.py …
├── scripts/xcode/*.sh                  # OS 依存操作（xcodegen/xcodebuild/simctl/fastlane）
├── templates/ios-app/                  # SwiftUI + SwiftData + StoreKit 2 アプリ雛形（XcodeGen）
├── examples/sample-app/                # 成果物の形式例（テスト用フィクスチャ）
└── tests/                              # pytest（115 件）
docs/ARCHITECTURE.md                    # 設計書
```

## 必要環境

| 用途 | 必要なもの |
|---|---|
| ワークフロー全般 | Claude Code、Python 3.9+（`jsonschema`, `Pillow`, `PyJWT[crypto]`, `requests`） |
| 実装・試験・撮影・TestFlight | macOS + Xcode 16 以降、iOS 17+ シミュレーター、[XcodeGen](https://github.com/yonaskolb/XcodeGen)、Fastlane（Bundler 推奨） |
| App Store Connect 連携 | App Store Connect API キー（App Manager 以上）、アプリレコード（API では作成不可） |
| 日本語スクリーンショット | 日本語フォント（macOS はヒラギノを自動検出。Linux は Noto Sans CJK） |

調査〜デザイン、ASO、ASC の dry-run は Linux でも動きます。ビルド・試験・撮影は macOS が必要です。

## インストール

**マーケットプレイスから（推奨）**
```
/plugin marketplace add moris94/ios-dev-workflow
/plugin install ios-app-factory@ios-dev-workflow
```

**ローカルの clone から（開発・検証用）**
```bash
git clone https://github.com/moris94/ios-dev-workflow
cd ~/work/MyNewApp            # 新しい iOS アプリのリポジトリ
claude --plugin-dir ~/path/to/ios-dev-workflow/plugins/ios-app-factory
```

**Python 依存関係**（初回のみ。`~/.local/share/ios-app-factory/venv` に入ります）
```bash
app-factory setup            # Claude Code 内なら ${CLAUDE_PLUGIN_ROOT}/bin/app-factory setup
app-factory doctor           # 依存・ツール・資格情報の有無・フォント・Git 衛生を確認
```

**macOS ツール**
```bash
xcode-select --install
brew install xcodegen
gem install bundler          # 雛形の Gemfile で fastlane を固定
```

## 初期設定

### 1. App Store Connect API キー（環境変数のみ）

App Store Connect →「ユーザとアクセス」→「統合」→「App Store Connect API」でキーを発行し、`.p8` を安全な場所に保存します（**リポジトリの外**）。

```bash
export ASC_KEY_ID=XXXXXXXXXX
export ASC_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export ASC_PRIVATE_KEY_PATH=$HOME/.appstoreconnect/AuthKey_XXXXXXXXXX.p8
# 代替: ASC_PRIVATE_KEY（PEM 本文）または ASC_PRIVATE_KEY_BASE64
```

- 値はログ・標準出力に出しません（自動マスク）。Hooks が `.p8` の読み出し、`printenv`、秘密値の `echo` をブロックします。
- JWT は ES256、`aud=appstoreconnect-v1`、有効期限は最大 20 分で自動更新されます。

### 2. アプリレコード
App Store Connect の「マイ App」で、`factory/config.json` と同じ Bundle ID のアプリを 1 度だけ作成します（API ではアプリを新規作成できません）。

### 3. サポート URL・プライバシーポリシー URL

**指定しない場合（既定）**: `support_page` 工程が、サポートとプライバシーポリシーを 1 つにまとめた日英のページを生成・公開し、その URL を `app.links.support` と `app.links.privacy_policy` の**両方**に設定します。

```bash
export FACTORY_SUPPORT_EMAIL=support@example.com          # 必須: ページに埋め込むサポート用メールアドレス
export FACTORY_NOTION_PARENT_PAGE=https://www.notion.so/... # 任意: 「Web で公開」済みの親ページ
```

- メールアドレスは環境変数からのみ読み込みます。リポジトリに保存されるのは `{{SUPPORT_EMAIL}}` を含む下書き（`factory/artifacts/support_page/page.md`）だけです。アドレスを埋め込んだ版は `.factory-tmp/`（Git 対象外）に作られます。
- **Notion MCP が接続されている場合**: Claude が Notion にページを作成し（再実行時は同じページを更新）、公開 URL を記録します。Notion の API と MCP には「Web で公開」を切り替える操作がないため、**公開済みの親ページの下に作る**のが確実です（子ページは公開設定を引き継ぎます）。公開されていない場合は、Notion で「共有 → Web で公開」を有効にするよう案内されます。
- **Notion MCP が接続されていない場合**: 完成したページの文面が表示されます。好きな場所（Notion、GitHub Pages、自分のサイトなど）で公開し、URL を伝えてください。Claude が `app-factory support-page record --url <URL> --provider manual` を実行します。
- 記録時に URL が HTTP 200 を返すか確認します。ページを編集した場合は、再公開して記録し直さないとゲートを通りません。

**自分のページを使う場合**: `factory/config.json` の `app.links.support` / `app.links.privacy_policy` を設定しておくと、ページは生成されず（`support-page use-existing`）、その URL が使われます。

どちらの場合も、同じ URL がアプリ内リンク（`AppLinks.swift`: 設定画面と課金画面）と ASC メタデータに使われ、ASO ゲートで一致を確認します。

## 実行方法

新しい（空でもよい）アプリのリポジトリで Claude Code を起動し、オーケストレーターを呼びます。

```
/ios-app-factory:factory 通知に頼らず続けられる、静かな習慣トラッカー
```

オーケストレーターの処理:
1. `app-factory init --scaffold` で `factory/`（設定・状態）と SwiftUI 雛形を作成（Bundle ID の接頭辞と Team ID だけ最初に確認します）
2. `app-factory next` → `start` → 担当 Subagent に委任 → `gate` を繰り返す
3. ゲート不合格なら失敗項目を渡して最大 3 回まで再実行。それでも駄目なら停止して理由を報告
4. 工程ごとに成果物とゲート結果をコミット

| 操作 | コマンド |
|---|---|
| 途中から再開 | `/ios-app-factory:factory resume` |
| 状況確認 | `/ios-app-factory:factory-status` または `app-factory status` |
| 仕様変更 | `/ios-app-factory:factory change mvp 無料枠を 10→20 件に変更` |
| 審査提出・公開（人間） | `/ios-app-factory:release-approval submit` の案内に従う |

### 人間の作業が必要な地点（自動では越えません）
- 調査結果が **NO-GO** のとき（方向転換するか判断）
- `FACTORY_SUPPORT_EMAIL` の設定。Notion MCP が無い場合は、サポート/プライバシーページの公開と URL の連絡
- 課金なしで出す場合の **waiver**（MVP では課金が原則必須）
- macOS でのビルド・試験・撮影（Linux 環境では手前で停止）
- `asc.mode` を `apply` にする判断と API キーの用意
- TestFlight ビルドでの **課金テストの記録**: `app-factory evidence purchase-test`
- **審査提出・公開の承認**: `app-factory approve submit` / `app-factory approve publish`

### CLI リファレンス（抜粋）
```bash
app-factory init --idea "..." --name "MyApp" --bundle-id com.you.myapp [--team-id TEAMID] --scaffold
app-factory status [--json] | next | check | revalidate
app-factory start <stage> --owner <id> [--takeover] [--force]
app-factory gate <stage> --owner <id>          # 0=合格, 2=不合格
app-factory invalidate <stage> --reason "..."  # 仕様変更 → 依存工程を stale に
app-factory validate <file> --schema <name>
app-factory codegen                             # DesignTokens / ProductCatalog / Products.storekit / AppLinks
app-factory support-page status|draft|render|record --url URL [--provider notion|manual]|use-existing
app-factory icon render | icon preview           # アイコン一式の生成 / 60・120・180px のプレビュー
app-factory screenshots render
app-factory asc plan [--fixture f.json] | asc apply [--simulate]
app-factory testflight verify [--simulate]
app-factory release readiness | release submit [--dry-run] | release publish [--dry-run]
app-factory approve submit|publish              # 人間専用・対話端末のみ
app-factory doctor
```
macOS 用スクリプト: `scripts/xcode/build.sh`, `test.sh`, `capture_screenshots.sh`, `testflight_upload.sh`

## ワークフローと品質ゲート

全ゲート共通: 上流工程が合格済みであること。結果は `factory/gates/<stage>.json` に入出力ダイジェスト付きで保存されます。

| 工程 | 主なチェック（すべて機械判定） |
|---|---|
| research | Schema、出典 ID の解決、出典 ≥8・競合 ≥5（≥3 件は apps.apple.com）、独立した需要根拠 ≥3、検索ログ ≥5、未来日付なし、GO 判定 |
| proposal | 差別化 ≥2 件に出典、must 機能 1–7、無料モデル不可 |
| charter | 原則 3–7（検証方法付き）、非目標 ≥2、日本語トーンが日本語 |
| mvp | 機能→原則のトレース、受入基準、画面定義、**課金必須**（無い場合は人間の waiver）、買い切り以外は理由必須、Product ID 接頭辞、IAP 名 ≤30・説明 ≤45、無料枠に価値、スクショシーン 3–10 |
| support_page | 英日の Support / Privacy Policy 見出し、メールはプレースホルダーのみ（直書き禁止）、課金・復元・収集データ種別の記載、公開内容=現行の下書き、公開 https URL が HTTP 200、support と privacy の両リンクが同じ公開 URL |
| app_icon | Schema（文字レイヤーなし）、憲章の原則・デザインコンセプト・ストア名との対応、ASO キーワードの反映、HIG の参照、デザインパレットの色のみ、主モチーフのコントラスト ≥3:1（ライト/ダーク）、レイヤー ≤12、64px での占有率 12–75%、生成物が最新、1024px RGB アルファなし |
| design | WCAG コントラスト（本文 4.5:1、UI 3:1、ライト/ダーク）、定番 AI 配色との ΔE ≥12、Apple HIG と Design Skill の参照記録、キャプションのコントラスト |
| implementation | 必須ファイル、生成コード最新、TODO/プレースホルダーなし、SwiftData、StoreKit 2（`Transaction.updates`/`currentEntitlements`/`AppStore.sync`/`finish`）、画面ごとの View、iOS 17+、version/build 一致、アイコンあり、単体テスト ≥5、**現行ソースでのビルド成功** |
| localization | sourceLanguage en、全キー ja 翻訳済み、空値なし、書式指定子一致、コード中の文字列が全てカタログにある、InfoPlist 表示名、CFBundleLocalizations |
| testing | 失敗 0、単体 ≥5・UI ≥2、課金系テスト合格、en と ja で実行、現行ソースと一致、全シーンの ScreenshotTests |
| aso | 名前/サブタイトル ≤30、キーワード ≤100・形式・重複、プロモ ≤170、説明 300–4000、日本語、キャプション長、価格表記なし、URL 一致、競合名と非重複 |
| screenshots | locale×device×scene 全数、正確な解像度、RGB/アルファなし、ハッシュ一致、生画像がシミュレーター解像度、キャプション一致、レシピ最新、**再レンダリングでバイト一致** |
| asc_sync | Plan の Schema、リクエスト構造検証、提出/公開系 API を含まない、最新の成果物から生成、apply 時は適用後の再 Plan が 0 件 |
| testflight | processingState VALID、version/build 一致、試験済みソースと一致、暗号化申告 |
| release_readiness | 全前工程合格、ASC 収束（live）、TestFlight=試験=現行ソース、人間による課金テスト記録 |
| submit / publish | 署名付き人間承認が readiness と一致・期限内、live で実行済み |

## 成果物

| パス | 内容 | Git |
|---|---|---|
| `factory/config.json` | 設定 | ✔ |
| `factory/idea.md` | 入力アイデア | ✔ |
| `factory/artifacts/<stage>/*` | 工程成果物（JSON + Markdown） | ✔ |
| `factory/artifacts/support_page/page.md`, `publication.json` | サポート/プライバシーページの下書き（メールはプレースホルダー）と公開記録 | ✔ |
| `App/Resources/Assets.xcassets/AppIcon.appiconset/*` | `icon.json` から生成したアイコン（ライト/ダーク/ティント） | ✔ |
| `factory/gates/<stage>.json` | ゲート結果（チェック一覧・入出力ダイジェスト） | ✔ |
| `factory/state.json`, `history.jsonl` | 実行状態・イベント履歴 | ✔ |
| `factory/reports/*.json` | build / tests / testflight / purchase-test / submission / release | ✔ |
| `factory/screenshots/{raw,final}/`, `manifest.json` | 撮影画像と合成済みストア画像 | ✔ |
| `factory/asc/plan.json`, `ledger.json`, `sync-report.json` | ASC 変更計画・送信済み操作台帳 | ✔ |
| `factory/approvals/*.json` | 人間承認（署名付き） | ✔ |
| `.factory-tmp/` | ログ、ロック、DerivedData、xcresult、生成途中ファイル | ✘（gitignore） |

## 状態管理・再開・重複防止・仕様変更

- **永続化**: `factory/state.json` は一時ファイル + fsync + rename で原子的に更新され、ファイルロックで直列化されます。コミットされるので、別マシン・別セッションからも再開できます。
- **再開**: 実行中のセッションが消えるとロックのハートビートが失効し（既定 30 分）、工程は `interrupted` になります。SessionStart Hook が新しいセッションに状態と次の手順を伝え、`/ios-app-factory:factory resume` で引き継ぎます。
- **重複実行の防止**: 工程ごとのランロックを `O_EXCL` で作成します。所有者（Claude セッション ID）が違えば `LockHeld` で拒否されます。合格済みで入出力が変わっていない工程は `skip` になります。
- **API 再送防止**: ASC の各操作は決定的キーを持ち、`ledger.json` に結果を記録します。成功済みの操作は二度と送りません。結果が不明な POST は `uncertain` として記録し、再送前に照合（GET）します。
- **仕様変更**: 各工程は「上流の出力ダイジェスト + 宣言入力（設定は関係するキーのみ）」を記録します。成果物を直接編集した場合も `invalidate` した場合も、該当工程と下流工程が `stale` になり、ゲートで再検証されます。

## App Store Connect 連携

| モード | コマンド | 内容 |
|---|---|---|
| dry-run（オフライン） | `app-factory asc plan` | 資格情報なし: 空のリモートと比較して全操作を表示・検証 |
| dry-run（ライブ読取） | `app-factory asc plan`（資格情報あり） | GET のみで現在値と差分を計算 |
| dry-run（スナップショット） | `app-factory asc plan --fixture snap.json` | 保存済みのリモート状態と比較 |
| 予行演習 | `app-factory asc apply --simulate` | 内蔵 ASC シミュレーターに適用 → 収束を確認（ネットワーク不要） |
| 本番適用 | `asc.mode: "apply"` にして `app-factory asc apply` | 差分のみ送信 → 再取得して残り 0 件を確認 |

設定する項目: アプリ情報（名前、サブタイトル、プライバシー URL、カテゴリ）、バージョン（説明、キーワード、プロモーションテキスト、URL、**releaseType=MANUAL**）、アプリ価格（無料）、非消耗型 IAP（作成、en/ja ローカライズ、価格スケジュール、全地域での販売、審査用スクリーンショット）、スクリーンショットセット（MD5 で比較し、変わった画像だけアップロード、順序を固定）。

API で設定できないため人間が行うもの: App のプライバシー（栄養ラベル）、年齢制限の質問票、契約・税務・口座、アプリレコードの初回作成。

## 人間の承認による審査提出・公開

1. Claude: `app-factory release readiness`（`ready: true` を確認）→ `app-factory release submit --dry-run`
2. **人間が自分のターミナルで**:
   ```bash
   cd MyNewApp && app-factory approve submit
   # → 「SUBMIT MyApp 1.0.0 (3)」を正確に入力
   ```
3. Claude: `app-factory release submit` → ゲート `submit`
4. Apple の審査通過後（`PENDING_DEVELOPER_RELEASE`）、人間が `app-factory approve publish`、続けて Claude が `app-factory release publish`

強制の仕組み（多層）:
- **スクリプト**: `approve` は TTY 必須で、Claude Code 内（`CLAUDECODE`）からは拒否します。確認フレーズの入力が必要です。承認は readiness ダイジェスト（ビルド・メタデータ・スクショ・IAP・ASC 状態）に束縛され、リポジトリ外の鍵（`~/.config/ios-app-factory/approver.key`、0600）で HMAC 署名され、期限（既定 72 時間）が切れると無効です。`release submit|publish` は毎回 readiness を再計算して検証します。
- **Hooks**: Claude による `approve` / `evidence` の実行、承認なしの `release submit|publish`、`reviewSubmissions` 等への直接 API 呼び出し、`fastlane deliver`/`submit_for_review`/`automatic_release`、承認ファイル・台帳・状態・ゲート結果の編集、承認鍵の参照をすべてブロックします。
- ASC の同期 Plan には提出・公開系エンドポイントを入れられません（検証で拒否）。バージョンは常に手動リリースです。

## 設定リファレンス

`factory/config.json`（`app-factory init` が生成。Schema: `lib/appfactory/schemas/config.schema.json`）

| キー | 既定 | 説明 |
|---|---|---|
| `app.name` / `project_name` / `scheme` | – | 表示名 / Xcode プロジェクト名 |
| `app.bundle_id`, `team_id`, `sku` | – | |
| `app.version`, `build_number` | `1.0.0`, `1` | `project.yml` と一致が必要（ゲートで確認） |
| `app.locales` / `primary_locale` | `["en-US","ja"]` / `en-US` | 英語が既定、日本語は必須 |
| `app.min_ios` | `17.0` | SwiftData のため 17 以上 |
| `app.links.support` / `privacy_policy` / `terms` | null / null / Apple 標準 EULA | 未指定なら `support_page` 工程が公開ページの URL を両方に設定。アプリ内リンクと ASC メタデータで共用 |
| `research.min_competitors` / `min_sources` | 5 / 8 | 調査ゲートのしきい値 |
| `asc.mode` | `dry-run` | `apply` で本番 ASC に書き込み |
| `asc.app_id`, `price_base_territory`, `remote_fixture` | null, `USA`, null | |
| `screenshots.devices` | `["iphone_6_9"]` | `iphone_6_9`(1320×2868, APP_IPHONE_67), `iphone_6_5`, `ipad_13` |
| `screenshots.fonts` | {} | 例 `{"ja": "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"}` |
| `release.require_manual_purchase_test` | true | 人による課金テスト記録を必須にする |
| `release.approval_ttl_hours` | 72 | 承認の有効期限 |
| `locks.stale_after_minutes` | 30 | ロック失効（再開可能になるまで）の時間 |

環境変数: `FACTORY_SUPPORT_EMAIL`（サポートページに載せるメールアドレス）, `FACTORY_NOTION_PARENT_PAGE`（任意: 公開済みの Notion 親ページ）, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY_PATH`（or `ASC_PRIVATE_KEY[_BASE64]`）, `FACTORY_SIMULATOR`（撮影・試験用シミュレーター名の上書き）, `FACTORY_APPROVER_KEY_PATH`, `FACTORY_REHEARSAL=1`（シミュレーター結果を受け入れる予行演習。本番 ASC には影響しません）, `FACTORY_DEBUG=1`（マスク済みのスタックトレース）。

## Git に保存するもの・しないもの

`app-factory init` が `.gitignore` に追記します: `.factory-tmp/`、`*.xcodeproj/`（XcodeGen で生成）、`DerivedData/`、`*.xcresult`、`*.ipa`、`fastlane/report.xml` など、`*.p8`、`.env*`、`xcuserdata/`。Hooks は `git add -f` と、一時ファイル・秘密ファイルを含む `git commit` をブロックします。ログ・試行錯誤・中間ファイルはすべて `.factory-tmp/` に置かれます。

## プラグイン自体のテスト

```bash
cd plugins/ios-app-factory
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q                        # 115 tests
claude plugin validate --strict .           # マニフェスト・Skills・Agents・Hooks の検証
```

`tests/test_e2e.py` は、1 つのアイデア（サンプル成果物）から全 17 工程を CLI 経由で通します。ASC シミュレーターへの適用・冪等性・承認なし提出の拒否・人間承認後の提出・Apple 承認待ちの公開拒否・公開まで含みます。ほかに、クラッシュ後の再開、セッション喪失からの引き継ぎ、同時実行の拒否、仕様変更の伝播、Hook のブロック、秘密情報のマスク、JWT のクレーム、スクリーンショットの再現性を検証しています。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `LockHeld: ... Refusing duplicate execution` | 別セッションがその工程を実行中です。そのセッションが終了済みなら 30 分待つか `app-factory start <stage> --takeover`、または `app-factory unlock <stage>` |
| 工程が `stale` になった | 上流の成果物か関係する設定が変わっています。`app-factory status` で理由を確認し、`app-factory revalidate` かオーケストレーターの `resume` で再検証 |
| `build.fresh` / `tests.fresh` が不合格 | ビルド・試験後にソースが変わっています。`scripts/xcode/build.sh` / `test.sh` を再実行 |
| `codegen:...` が不合格 | `design.json`/`mvp.json`/設定の変更が生成コードに反映されていません → `app-factory codegen` |
| `this step needs macOS with Xcode` | ビルド・試験・撮影・TestFlight は Mac で実行してください。その他の工程は Linux でも可 |
| `xcodegen not found` | `brew install xcodegen` |
| シミュレーターが見つからない | `xcrun simctl list devices available` で名前を確認し `FACTORY_SIMULATOR="iPhone 16 Pro Max"` |
| `font ... lacks glyphs for ja` | 日本語フォントを `screenshots.fonts.ja` に指定（Linux: `fonts-noto-cjk`） |
| `App record ... not found` | App Store Connect でアプリを作成し、Bundle ID を確認。必要なら `asc.app_id` を設定 |
| `HTTP 401`（ASC） | キー ID・Issuer ID・.p8 の組み合わせ、キーの権限（App Manager 以上）、システム時刻を確認 |
| `HTTP 409`（ASC） | 既に存在するか、編集できない状態のバージョンです。`asc plan` で差分を確認。台帳により二重作成はされません |
| `uncertain` が台帳に残る | 次回の `asc apply` が照合（GET）してから続行します。手動での台帳編集は不要です（Hook で禁止） |
| `build N not found yet` | TestFlight で処理中です。数分後に `app-factory testflight verify` を再実行 |
| `HUMAN APPROVAL REQUIRED` | 人間が自分のターミナルで `app-factory approve submit`。承認後に何かが変わると無効になるので、`release readiness` からやり直してください |
| `approval requires an interactive terminal` | Claude Code の `!` やスクリプトからは承認できません。通常のターミナルで実行してください |
| `approver key ... must not be group/world accessible` | `chmod 600 ~/.config/ios-app-factory/approver.key` |
| Python の import エラー | `app-factory setup`（venv を作り依存をインストール） |
| `set FACTORY_SUPPORT_EMAIL` | サポートページに載せるメールアドレスを環境変数に設定してから、`support-page render` を再実行 |
| `publication.reachable` が不合格 | ページが非公開です。Notion で「共有 → Web で公開」を有効にする（または公開済みの親ページの下に移す）→ `support-page record` を再実行 |
| `publication.current` が不合格 | `page.md` を編集した後、再公開していません。render → 公開 → record をやり直してください |
| Notion にページが重複した | `publication.json` の `notion_page_id` があれば、再実行時はそのページを更新します。重複したページは Notion 上で削除してください |
| `legibility.coverage` / `glyph.contrast` が不合格 | アイコンのモチーフが小さすぎる・大きすぎる・薄すぎます。`app-factory icon preview` で 60px 表示を見て `icon.json` を調整 |
| `palette.from-design` が不合格 | デザインパレット外の色は、`extra_colors` に理由付きで追加するか、パレット内の色に変更 |
| Hook に止められた | メッセージに正しい手順（`app-factory` コマンド）が表示されます。回避はしないでください |

## 検証状況と制約

- この環境（Linux）で実行・検証したもの: Python エンジン、全ゲート、ASC の Plan・検証、シミュレーターへの適用・クラッシュ復旧・冪等性、承認と Hooks、スクリーンショット合成（Noto CJK）、アイコン描画、サポートページの生成と記録、全 115 テスト、`claude plugin validate --strict`。
- Notion への実際の投稿は、MCP ツールを使う Claude の手順（Skill）として実装しています。Notion MCP を接続した環境での実投稿はまだ試していません（テストでは公開 URL の確認を代替しています）。
- **macOS / Xcode が必要なため、ここでは実行できていないもの**: SwiftUI 雛形のコンパイル、XCTest/XCUITest の実行、シミュレーターでの撮影、Fastlane での TestFlight アップロード、実際の App Store Connect への書き込み。雛形の Swift コードと `scripts/xcode/*.sh` は、初回は Mac で `build.sh` → `test.sh` を流して確認してください（失敗はそれぞれのゲートで検出されます）。
- App Store Connect API の仕様は Apple 公式ドキュメント（JWT ES256、`/v1`・`/v2` の JSON:API リソース、スクリーンショットの予約→アップロード→コミット、`reviewSubmissions`）に基づいています。ただし内蔵シミュレーターは Apple のサーバー側検証を再現しません。初回の本番適用前に、必ずライブ読み取りの dry-run（資格情報ありの `asc plan`）で差分を確認してください。
- スクリーンショットの既定は 6.9 インチ iPhone（1320×2868、`APP_IPHONE_67`）です。iPad 対応アプリは `ipad_13` を追加してください。
