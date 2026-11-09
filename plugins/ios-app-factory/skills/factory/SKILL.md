---
name: factory
description: Orchestrate the full iOS App Factory pipeline — from an app idea through research, proposal, charter, MVP, design, SwiftUI implementation, StoreKit 2 IAP, en/ja localization, tests, store screenshots, ASO and App Store Connect sync — with quality gates, resumable state and human-approved submission. Use when the user gives an app idea to build, or says resume/continue the factory, or reports a spec change.
argument-hint: "<app idea> | resume | status | change <stage> <reason>"
when_to_use: "Examples: build an iOS app from an idea; run the app factory; resume the pipeline; continue where we left off; the spec changed."
allowed-tools: Bash(app-factory *) Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git add *) Bash(git commit *) WebSearch WebFetch
---

# iOS App Factory — Orchestrator

You are the **orchestrator**. You run in the main conversation, drive the
pipeline stage by stage, delegate each stage to its specialist subagent,
and enforce the quality gates. Subagents cannot spawn subagents, so only you
delegate.

Invoke the CLI as `app-factory …` (the plugin puts it on PATH).
Session owner id: `${CLAUDE_SESSION_ID}` — pass it as `--owner` on every
`start` / `gate` / `fail` call so run locks are attributed to this session.

Request: `$ARGUMENTS`

## 0. Bootstrap

1. `app-factory doctor` — report missing tools briefly (Xcode tools are only needed
   from `implementation` on; ASC credentials only for `asc apply`/TestFlight).
   If Python deps are missing run `app-factory setup`.
2. If `factory/config.json` does not exist (new repo):
   - Derive a working English name (≤30 chars) and a bundle id. Use the
     bundle id prefix from git config / existing projects if visible;
     otherwise ask the user **once** for the bundle id prefix and Apple Team ID
     (both can be changed later in `factory/config.json`).
   - `app-factory init --idea "<idea>" --name "<Name>" --bundle-id <id> [--team-id <TEAM>] --scaffold`
   - Commit `factory/`, `.gitignore` and the scaffold
     (`git add factory .gitignore project.yml App AppTests AppUITests fastlane Gemfile`).
3. If the argument is `status`, run `app-factory status` and stop.
4. If the argument is `change <stage> <reason>`: run
   `app-factory invalidate <stage> --reason "<reason>"`, then continue with the loop
   (stale stages are re-validated, and redone where their gate fails).

## 1. Main loop

Repeat until `app-factory next` returns `null`, or a **human stop** (section 3) is reached:

1. `app-factory check` (detects edited artifacts → marks dependants stale), then `app-factory next`.
2. If `action` is `revalidate`: run `app-factory gate <id> --owner ${CLAUDE_SESSION_ID}` first.
   If it passes, continue the loop; if not, treat it as a normal run with the gate failures as input.
3. `app-factory start <id> --owner ${CLAUDE_SESSION_ID}`
   - `action: skip` → already passed, continue.
   - `LockHeld` error → another session is running this stage. Do **not** run it
     again. Tell the user; only if they confirm that session is dead, use `--takeover`.
4. Delegate with the **Agent** tool to `ios-app-factory:<agent>` from the `next` output.
   Brief it with: stage id, the skills to follow (`ios-app-factory:<skill>`), input artifact paths,
   required output paths, the gate command, and — on retries — the failing
   checks from `factory/gates/<id>.json`. Ask it to finish by running the gate
   itself and returning the gate summary.
   Stage order: research → proposal → charter → mvp → design → ux_review → support_page → aso → app_icon →
   implementation → localization → testing → screenshots → asc_sync → testflight → release_readiness → submit → publish.
5. `app-factory gate <id> --owner ${CLAUDE_SESSION_ID}` (exit 0 = pass, 2 = fail).
6. On failure, re-delegate with the failing checks. After **3 failed attempts**,
   `app-factory fail <id> --reason "<summary>"` and stop: explain to the user what blocks the gate.
7. On pass, commit that stage's artifacts and gate report:
   `git add factory <stage outputs>` + `git commit -m "factory(<id>): <title>"`.
   Never commit `.factory-tmp/`; the hooks block it.

Stage → agent → skills (from `pipeline.json`):

| stage | agent | skills |
|---|---|---|
| research | market-researcher | market-research |
| proposal, charter, mvp | product-manager | product-proposal, product-charter, mvp-spec, storekit-monetization |
| design | product-designer | design-concept |
| ux_review | product-designer | ux-prototype (human approval in chat: 「承認 UX」) |
| support_page | release-manager | support-page (Notion MCP when connected) |
| app_icon | product-designer | app-icon |
| implementation, localization | ios-developer | swiftui-implementation, storekit-monetization, localization |
| testing | qa-engineer | ios-testing |
| aso | product-manager | aso-copywriting |
| screenshots | product-designer | store-screenshots |
| asc_sync, testflight, release_readiness | release-manager | asc-sync, testflight-release |
| submit, publish | release-manager | release-approval (human-gated) |

## 2. Resume after interruption

`resume` (or a new session that the SessionStart hook says has pipeline state):
run `app-factory status`. Stages marked `interrupted` were running in a session that
died — run `app-factory start <id> --owner ${CLAUDE_SESSION_ID} --takeover` and continue the loop.
Artifacts already on disk are reused; the subagent should continue from them, not start over.
App Store Connect writes are ledger-protected (`factory/asc/ledger.json`), so re-running
`asc apply` never re-sends a successful operation.

## 2b. Delivery first (quality profile `mvp`, the default)

The first release optimises for shipping. Under `quality.profile: "mvp"` checks about polish and depth are
reported as warnings and do not block; only correctness, App Store limits, approvals and secrets block. Do not
spend extra attempts polishing warnings — mention the notable ones in your report and move on. If the human
wants the full bar, they set `quality.profile` to `"strict"`.

## 2c. Approvals happen in this chat

Every human approval is given by the human replying in this conversation; nobody needs a terminal.
1. Run `app-factory approval request <ux|submit|purchase_test>`; it prints a summary and the exact reply.
2. Show the human what they approve (open the storyboards / summarise readiness) and ask them to reply with
   that phrase, e.g. 「承認 UX」, 「承認 提出」 (declining: 「却下 UX」 plus what to change).
3. Their message itself is recorded by the plugin's UserPromptSubmit hook; you will see
   `[ios-app-factory] The human APPROVED …` in your context. You cannot approve for them — never write the reply
   yourself, edit approval files, or claim approval without that notice.
By default (`approval.single_release_approval`) the submit approval also covers releasing after Apple approves.

## 3. Human stops (never work around these)

- **Research NO-GO** (`verdict.go=false`): present the evidence, ask whether to pivot.
- **Monetization waiver**: the first release must include payments (prefer non-consumable).
  Only the human may waive it (`mvp.json monetization.waiver.approved_by`).
- **UI/UX pre-approval** (`ux_review`): after the designer renders the storyboards, show them to the human
  (paths from `app-factory ux status`; open the PNGs so they appear in the conversation), list each use case in
  one line plus `review_focus`, and ask: approve, or what to change. Revise on feedback. When they are satisfied,
  run `app-factory approval request ux` and let them reply 「承認 UX」 in the chat; then gate `ux_review`. Implementation never starts before
  this approval, and any later UX change needs a new approval. While waiting you may run stages that don't depend on
  it (`support_page`, `aso`).
- **Support e-mail / page publishing**: the `support_page` stage needs `FACTORY_SUPPORT_EMAIL`. If no Notion MCP
  server is connected, show the rendered page text and ask the human to publish it and give you the URL.
  Prefer delegating `support_page` to the release-manager only when Notion tools are available to subagents;
  otherwise run that stage yourself in the main conversation (MCP tools are always available here).
- **Xcode unavailable** (not macOS): stop before `implementation` builds; say what to run on a Mac.
- **Release backend**: release work runs through fastlane unless the human explicitly chose `release.backend: "api"`.
  Don't switch it yourself. fastlane must be installed on the Mac (`bundle install` with the scaffolded Gemfile).
- **ASC credentials / app record**: `asc_sync` in apply mode and `testflight` need `ASC_KEY_ID`,
  `ASC_ISSUER_ID`, `ASC_KEY_CONTENT_BASE64` and an existing app record. Without them run the dry-run
  (`app-factory asc plan`) and stop; the human sets `asc.mode` to `apply` in `factory/config.json`.
- **Manual purchase test** (only when `release.require_manual_purchase_test` is true — off by default): ask the human to
  test the TestFlight build, then `app-factory approval request purchase_test`; they reply 「承認 課金テスト」.
- **Submission & release**: run `app-factory release readiness` and `app-factory release submit --dry-run`, then
  `app-factory approval request submit`, show the summary and ask for 「承認 提出」. After the approval notice,
  `app-factory release submit`. Once Apple approves (version pending developer release), `app-factory release publish`
  — covered by the same approval unless `approval.single_release_approval` is false (then request `publish`).
  Do not try alternative paths (fastlane deliver, curl, editing approval files); hooks and scripts refuse them.

## 4. Reporting

After each stage, give a one-line update (stage, gate result, attempts). At the end, or at a human stop,
summarise: passed stages, artifacts produced (paths), what the human must do next, and the exact command.
