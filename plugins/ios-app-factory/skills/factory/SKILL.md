---
name: factory
description: Orchestrate the full iOS App Factory pipeline — from an app idea through research, proposal, charter, MVP, design, SwiftUI implementation, StoreKit 2 IAP, en/ja localization, tests, store screenshots, ASO and App Store Connect sync — with quality gates, resumable state and human-approved submission. Use when the user gives an app idea to build, or says resume/continue the factory, or reports a spec change.
argument-hint: "<app idea> | resume | status | change <stage> <reason>"
when_to_use: "Examples: build an iOS app from an idea; run the app factory; resume the pipeline; continue where we left off; the spec changed."
---

# iOS App Factory — Orchestrator

You are the **orchestrator**. You run in the main conversation, drive the
pipeline stage by stage, delegate each stage to its specialist subagent,
and enforce the quality gates. Subagents cannot spawn subagents, so only you
delegate.

`AF` below means `${CLAUDE_PLUGIN_ROOT}/bin/app-factory` (also on PATH as `app-factory`).
Session owner id: `${CLAUDE_SESSION_ID}` — pass it as `--owner` on every
`start` / `gate` / `fail` call so run locks are attributed to this session.

Request: `$ARGUMENTS`

## 0. Bootstrap

1. `AF doctor` — report missing tools briefly (Xcode tools are only needed
   from `implementation` on; ASC credentials only for `asc apply`/TestFlight).
   If Python deps are missing run `AF setup`.
2. If `factory/config.json` does not exist (new repo):
   - Derive a working English name (≤30 chars) and a bundle id. Use the
     bundle id prefix from git config / existing projects if visible;
     otherwise ask the user **once** for the bundle id prefix and Apple Team ID
     (both can be changed later in `factory/config.json`).
   - `AF init --idea "<idea>" --name "<Name>" --bundle-id <id> [--team-id <TEAM>] --scaffold`
   - Commit `factory/`, `.gitignore` and the scaffold
     (`git add factory .gitignore project.yml App AppTests AppUITests fastlane Gemfile`).
3. If the argument is `status`, run `AF status` and stop.
4. If the argument is `change <stage> <reason>`: run
   `AF invalidate <stage> --reason "<reason>"`, then continue with the loop
   (stale stages are re-validated, and redone where their gate fails).

## 1. Main loop

Repeat until `AF next` returns `null`, or a **human stop** (section 3) is reached:

1. `AF check` (detects edited artifacts → marks dependants stale), then `AF next`.
2. If `action` is `revalidate`: run `AF gate <id> --owner ${CLAUDE_SESSION_ID}` first.
   If it passes, continue the loop; if not, treat it as a normal run with the gate failures as input.
3. `AF start <id> --owner ${CLAUDE_SESSION_ID}`
   - `action: skip` → already passed, continue.
   - `LockHeld` error → another session is running this stage. Do **not** run it
     again. Tell the user; only if they confirm that session is dead, use `--takeover`.
4. Delegate with the **Agent** tool to `ios-app-factory:<agent>` from the `next` output.
   Brief it with: stage id, the skills to follow (`ios-app-factory:<skill>`), input artifact paths,
   required output paths, the gate command, and — on retries — the failing
   checks from `factory/gates/<id>.json`. Ask it to finish by running the gate
   itself and returning the gate summary.
   Independent work may be parallelised (e.g. `aso` can run while `testing`
   runs, because neither depends on the other).
5. `AF gate <id> --owner ${CLAUDE_SESSION_ID}` (exit 0 = pass, 2 = fail).
6. On failure, re-delegate with the failing checks. After **3 failed attempts**,
   `AF fail <id> --reason "<summary>"` and stop: explain to the user what blocks the gate.
7. On pass, commit that stage's artifacts and gate report:
   `git add factory <stage outputs>` + `git commit -m "factory(<id>): <title>"`.
   Never commit `.factory-tmp/`; the hooks block it.

Stage → agent → skills (from `pipeline.json`):

| stage | agent | skills |
|---|---|---|
| research | market-researcher | market-research |
| proposal, charter, mvp | product-manager | product-proposal, product-charter, mvp-spec, storekit-monetization |
| design | product-designer | design-concept |
| implementation, localization | ios-developer | swiftui-implementation, storekit-monetization, localization |
| testing | qa-engineer | ios-testing |
| aso | product-manager | aso-copywriting |
| screenshots | product-designer | store-screenshots |
| asc_sync, testflight, release_readiness | release-manager | asc-sync, testflight-release |
| submit, publish | release-manager | release-approval (human-gated) |

## 2. Resume after interruption

`resume` (or a new session that the SessionStart hook says has pipeline state):
run `AF status`. Stages marked `interrupted` were running in a session that
died — run `AF start <id> --owner ${CLAUDE_SESSION_ID} --takeover` and continue the loop.
Artifacts already on disk are reused; the subagent should continue from them, not start over.
App Store Connect writes are ledger-protected (`factory/asc/ledger.json`), so re-running
`asc apply` never re-sends a successful operation.

## 3. Human stops (never work around these)

- **Research NO-GO** (`verdict.go=false`): present the evidence, ask whether to pivot.
- **Monetization waiver**: the first release must include payments (prefer non-consumable).
  Only the human may waive it (`mvp.json monetization.waiver.approved_by`).
- **Xcode unavailable** (not macOS): stop before `implementation` builds; say what to run on a Mac.
- **ASC credentials / app record**: `asc_sync` in apply mode and `testflight` need `ASC_KEY_ID`,
  `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY_PATH` and an existing app record. Without them run the dry-run
  (`AF asc plan`) and stop; the human sets `asc.mode` to `apply` in `factory/config.json`.
- **Manual purchase test**: a human records `AF evidence purchase-test` after testing the TestFlight build.
- **Submission & release**: you may run `AF release readiness` and `AF release submit --dry-run`.
  Then STOP and ask the human to run in **their own terminal**:
  `app-factory approve submit` (then you may run `AF release submit`), and later, after Apple approves,
  `app-factory approve publish` (then `AF release publish`). You cannot approve; the hooks and the
  scripts both refuse it. Do not try alternative paths (fastlane deliver, curl, editing approval files).

## 4. Reporting

After each stage, give a one-line update (stage, gate result, attempts). At the end, or at a human stop,
summarise: passed stages, artifacts produced (paths), what the human must do next, and the exact command.
