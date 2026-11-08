# ios-app-factory 設計書

## 0. 調査した前提仕様（2026-11 時点）

**Claude Code Plugin**（https://code.claude.com/docs/en/plugins-reference ほか）
- マニフェストは `.claude-plugin/plugin.json`（必須は `name` のみ）。`skills/<name>/SKILL.md`、`agents/*.md`、`hooks/hooks.json`、`bin/`（有効時に Bash の PATH へ追加）は既定の場所から読み込まれる。
- `${CLAUDE_PLUGIN_ROOT}` は Hook のコマンド/引数と Skill/Agent の本文で展開されるが、Claude の Bash 環境変数には入らない → Skill 本文ではパスを展開済みで渡し、補助として `bin/app-factory` を PATH に置く。
- Hook は exec 形式（`command` + `args`）を使う。PreToolUse は終了コード 2 でブロックし、stderr が理由として Claude に渡る。SessionStart の stdout はコンテキストに追加される。
- プラグインの Subagent では `hooks` / `mcpServers` / `permissionMode` が無視される → ガードはすべてプラグインの `hooks/hooks.json` に置く。Subagent は他の Subagent を起動できない → オーケストレーターはメイン会話の Skill にする。
- SKILL.md のフロントマター: `name`, `description`, `when_to_use`, `argument-hint`, `disable-model-invocation`, `user-invocable`, `allowed-tools` 等。`$ARGUMENTS`, `${CLAUDE_SESSION_ID}` が展開される。
- `claude plugin validate --strict` で検証（YAML 不正のフロントマターはここで検出された）。

**App Store Connect API**
- JWT: ES256、ヘッダ `kid`/`typ: JWT`、ペイロード `iss`, `iat`, `exp`（最大 20 分）, `aud: appstoreconnect-v1`。
- JSON:API 形式。主なリソース: `apps`, `appInfos`/`appInfoLocalizations`, `appStoreVersions`/`appStoreVersionLocalizations`, `appScreenshotSets`/`appScreenshots`（予約 → `uploadOperations` へ PUT → `uploaded: true` + `sourceFileChecksum`(MD5) でコミット）, `/v2/inAppPurchases` + `inAppPurchaseLocalizations` + `inAppPurchasePriceSchedules` + `inAppPurchaseAvailabilities` + `inAppPurchaseAppStoreReviewScreenshots`, `appPriceSchedules`, `builds`, `reviewSubmissions`/`reviewSubmissionItems`, `inAppPurchaseSubmissions`, `appStoreVersionReleaseRequests`。
- アプリレコードは API で作成できない。App のプライバシー（栄養ラベル）は API 非対応。

**デザイン Skills**: Anthropic 公式の `frontend-design`（`anthropics/skills`、`claude-plugins-official`）。その「AI 生成デザインに多い既定値」の一覧を、デザインゲートの定番配色検出に取り入れている。加えて Apple Human Interface Guidelines の参照を必須にしている。

## 1. 全体アーキテクチャ

```
 human ──/ios-app-factory:factory <idea>──▶ Orchestrator Skill (main thread)
                                              │  app-factory next/start/gate (state machine)
                                              ▼
            ┌──────────── Subagents (one per discipline) ───────────────┐
            │ market-researcher  product-manager  product-designer      │
            │ ios-developer      qa-engineer      release-manager       │
            └───────┬──────────────────────────────────────────┬────────┘
                    │ writes artifacts (JSON+MD)               │ runs scripts/xcode/*.sh (macOS)
                    ▼                                          ▼
            factory/artifacts/**  ──▶  gates/*.py  ──▶  factory/gates/<stage>.json
                    │                                          │
                    └──▶ engine.py: state.json, locks, digests, staleness, history
                                               │
              asc/ planner → executor(+ledger) → App Store Connect API  (never submits)
              release.py readiness → approval.py (human, TTY, HMAC) → submit/publish
                         ▲
              hooks/: PreToolUse(Bash, Write|Edit) + SessionStart  (enforcement layer)
```

責務の分離:
- **Skills** = 専門知識と手順（19 個。オーケストレーター、状態表示、工程ごとの専門 Skill、人間承認）
- **Subagents** = 役割とツール権限（6 個）。工程の Skill をプリロード
- **エンジン（Python）** = 決定的な処理: 状態、ロック、ダイジェスト、ゲート、コード生成、合成、API 計画/実行、承認
- **スクリプト（bash）** = OS 依存の外部操作（xcodegen、xcodebuild、simctl、xcresulttool、fastlane）
- **Hooks** = 強制（エージェントが手順を外れても止まる層）

## 2. 工程定義（pipeline.json）

各工程は `id, agent, skills, depends_on, inputs, outputs{include,exclude}, gate, human_approval` を持つ。出力の所有権は重ならない（例: `*.xcstrings` は localization のもので implementation からは除外、`AppUITests/` は testing のもの）。そのため、ある工程の作業が別の合格済み工程を無関係に stale にすることはない。

```
research → proposal → charter → mvp → design → ux_review(人間承認) → support_page → aso → app_icon
                                                                        ↓
                                   implementation → localization → testing
                                                                      ↓
                                                     screenshots ← (testing, design, aso)
                                                          ↓
                                   asc_sync → testflight → release_readiness → submit → publish
```

- `ux_review`: 代表ユースケース（初回体験・中核タスク・課金など 3〜5 件）を手順とワイヤーフレームで定義し、デザインのパレットでストーリーボードを描画する。人間が `app-factory approve ux` で承認する（リリース承認と同じ仕組みで、ux.json とストーリーボードのダイジェストに結び付く）。implementation はこの工程に依存し、testing ゲートは各ユースケースが UI テストでカバーされていることを確認する。
- `support_page`: 未指定ならサポート＋プライバシーポリシーを 1 ページ（英日）にまとめる。メールは `FACTORY_SUPPORT_EMAIL` から取り、コミットする下書きはプレースホルダーのまま。Notion MCP があれば Claude が投稿し、無ければ文面を表示して人間が投稿する。`support-page record` が URL を `app.links.support` と `privacy_policy` の両方に書き込み、ASO・`AppLinks.swift`・ASC が同じ URL を使う。
- `app_icon`: デザイナーが文字なしのベクター仕様（`icon.json`）を書き、エンジンがライト/ダーク/ティントの 3 種を決定的に描画する。ゲートは憲章・デザイン・ASO との対応、パレット、コントラスト、64px での占有率、再描画の一致を確認する。アイコンのファイルはこの工程が所有し、implementation の出力から除外している。

## 3. 成果物（明示的な契約）

| 成果物 | Schema | 生成 |
|---|---|---|
| research.json | research | agent |
| proposal.json | proposal | agent |
| charter.json | charter | agent |
| mvp.json | mvp | agent |
| design.json | design | agent |
| aso.json | aso | agent |
| support_page/page.md, publication.json | support_publication | `support-page draft/record` |
| app_icon/icon.json | app_icon | agent → `icon render` |
| build.json / tests.json | build_report / test_report | scripts → `app-factory report` |
| screenshots/manifest.json | screenshots_manifest | `screenshots render` |
| asc/plan.json | asc_plan | `asc plan` |
| testflight.json | testflight_report | `testflight verify` |
| purchase-test.json | purchase_test | human (`evidence`) |
| approvals/*.json | approval | human (`approve`) |
| config.json | config | `init` + human |

生成コード（`DesignTokens.swift`, `ProductCatalog.swift`, `Products.storekit`, `AppLinks.swift`）は成果物から決定的に作られる。ゲートはメモリ上で再生成して比較し、手編集や再生成忘れを検出する。

## 4. 品質ゲート

ゲートは純粋関数で、リポジトリ内のファイル（とスクリプトの出力したレポート）だけを読み、ネットワークを使わない。各チェックは `{id, passed, severity(error|warning), message, details}`。error が 1 件でもあれば不合格。代表的な「鮮度」チェックは **source digest**（`project.yml`, `App/**`, `AppTests/**`, `AppUITests/**` のハッシュ）で、ビルド・試験・TestFlight が同じソースから作られたことを保証する。

## 5. 状態管理

- `factory/state.json`: 工程ごとの `status`(pending/running/passed/failed/stale/interrupted)、`attempts`、`run_id`、`owner`、`input_digest`、`output_digest`、`gate_report`、`reason`。一時ファイル + fsync + rename で原子的に書き、`fcntl.flock` のミューテックスで直列化する。
- `factory/history.jsonl`: 追記専用のイベントログ（監査用）
- `.factory-tmp/locks/<stage>.lock`: `O_EXCL` で作るランロック（owner, run_id, heartbeat）。同じ owner なら再入可、ハートビートが失効したら引き継ぎ可、`--takeover` で明示的に引き継げる。
- **stale 検出**（`refresh`）: 合格済み工程について (a) 上流が合格でない、(b) 入力ダイジェスト（上流の出力ダイジェスト + 宣言入力。`file.json#key` は指定キーのみ）が変わった、(c) 自分の出力が変わった、のいずれかで stale にする。トポロジカル順に 1 パスで伝播する。
- ゲート合格で出力ダイジェストが変われば、下流の合格済み工程は即座に stale になる。

## 6. App Store Connect 操作方針

**リリースのバックエンド**: 既定は `release.backend = "fastlane"`。メタデータとスクリーンショットは `deliver`、TestFlight は `pilot`、ビルド状態・公開は Spaceship、審査提出は `deliver submit_for_review` で行う。レーンは `app-factory` が起動し、結果を JSON で受け取る。IAP・アプリ価格・IAP の初回提出は fastlane に対応機能がないため、ASC API を使う。`"api"` を明示した場合は、以下の自前 API クライアントですべてを処理する。どちらのバックエンドでも、計画・検証・台帳・収束確認の仕組みは共通。


1. **望ましい状態を宣言**（`asc/state.py: desired_state`）: config + aso + mvp + screenshots manifest から作る
2. **リモートの状態を正規化**（live GET / fixture / empty）
3. **差分 → Plan**（`planner.py`）: 変わったフィールドだけ PATCH、無いものは POST、画像は MD5 で比較。操作には `{ref:…}`（前の操作で得た ID）と `{lookup:…}`（実行時の読み取り専用の解決: 価格ポイント・地域）のプレースホルダーを使う
4. **検証**（`validate_plan`）: リソース型ごとの許可属性・関係、PATCH の id、作成時に id を付けない、文字数上限、`releaseType=MANUAL`、提出/公開系エンドポイントの禁止
5. **実行**（`executor.py`）: 台帳で冪等性を保つ。成功済みはスキップ。POST はリトライしない。結果が不明な POST は `uncertain` にし、次回は照合（reconcile）してから続行する。予約だけ済んだアップロードは削除してからやり直す。429/5xx は冪等なメソッドに限り指数バックオフで再試行
6. **収束確認**: 適用後に再取得して再 Plan し、0 件であることを `sync-report.json` に記録し、ゲートで要求する

提出（`release submit`）と公開（`release publish`）は別モジュールで、同じ台帳（scope 付き）を使う。どちらも実行直前に readiness を再計算し、承認を検証する。

## 7. 人間承認

承認の種類: `ux`（実装前の UI/UX、UX ダイジェストに結び付く）、`submit` / `publish`（リリース準備のダイジェストに結び付く）。

| 層 | 仕組み |
|---|---|
| CLI | `approve` は TTY 必須、`CLAUDECODE` 環境では拒否、アプリ名・版・ビルドを含むフレーズの入力が必要 |
| データ | 承認は readiness ダイジェストに束縛され、リポジトリ外の鍵で HMAC-SHA256 署名され、有効期限を持つ |
| 実行 | `release submit/publish` は readiness を再計算し、署名・期限・ダイジェストを検証 |
| Hook | approve/evidence の実行、承認なしの submit/publish、直接の API 提出、fastlane の deliver/submit、承認・台帳・状態の編集、鍵の参照を拒否 |
| API | 同期 Plan に提出系パスを含められない。バージョンは常に `releaseType=MANUAL` |
| ゲート | submit/publish のゲートは有効な承認と live 実行を要求する |

## 8. 機密情報とログ

- 資格情報は環境変数からだけ読む（`ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_CONTENT_BASE64`）。JWT はメモリ上で署名する。例外は `xcodebuild -authenticationKeyPath` 用の一時ファイルで、`.factory-tmp/asc-key/`（0600）に書き出し、スクリプト終了時に trap で削除する。
- 出力はすべて `redact()` を通す。マスク対象は、秘密らしい名前の環境変数の値（`*_PATH` は除く）、PEM 秘密鍵、JWT、`Authorization: Bearer` の値。
- 詳細ログは `.factory-tmp/logs/`（gitignore）だけに書く。fastlane のログもここに置き、失敗時の抜粋もマスクしてから表示する。
- Hook が `.p8` の読み出し、秘密環境変数の echo、`printenv`/`env` を止める。

## 9. 試験の部分再実行

`tests.json` は `runs`（最初は全件実行、その後に部分再実行）を持ち、同じテスト ID とロケールについては最新の結果で統合する。部分再実行を許すのは、原因が `environment`（ソース無変更）か `test-defect`（アプリのダイジェスト＝`project.yml`＋`App/**` が全件実行時と同一で、変わったのはテストコードだけ）の場合に限る。`test-defect` では、変更されたテストクラスの全テストを両ロケールで再実行させる。回数の上限、原因のメモ、失敗ケースの網羅は、レポート作成時とゲートの両方で検証する。再実行でだけ通ったテストは flaky として警告にする。

## 10. テスト戦略

- 単体: engine / gates / l10n / codegen / screenshots / asc（planner, executor, ledger, JWT）/ approval / guards / redact
- 統合: `test_e2e.py` が CLI で全 18 工程を通す（macOS 専用の手順はレポートを書くヘルパーで代替し、ASC は内蔵シミュレーターを使う）
- 構造: `test_plugin_structure.py` が pipeline ↔ agents ↔ skills ↔ gates ↔ schemas の参照整合性、フロントマター、実行権限、テンプレートのプレースホルダーを検証
- 外部: `claude plugin validate --strict`
