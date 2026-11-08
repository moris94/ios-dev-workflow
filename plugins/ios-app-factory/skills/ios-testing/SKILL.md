---
name: ios-testing
description: QA for the factory iOS app — XCTest unit tests, XCUITest flows in English and Japanese, purchase/paywall tests with a mock store, the ScreenshotTests that capture every MVP scene, and the machine-readable test report from xcresult. Use for the factory "testing" stage.
user-invocable: false
---

# Testing (stage `testing`)

Inputs: `mvp.json` (acceptance criteria, screenshot scenes), the app sources.
Outputs: `AppUITests/**`, `factory/reports/tests.json` (written by the script).

## UI tests (`AppUITests/`)
- Launch with `app.launchArguments += ["-uiTesting", "-resetState"]` (+ `-seedDemoData`, `-proUnlocked` as needed).
  `-uiTesting` swaps in the mock store and disables animations; nothing touches the network.
- One test per must-feature acceptance criterion that needs UI (create, edit, delete, navigate, empty state).
- Paywall: opens at the documented trigger, shows a price and **Restore Purchases**, closing works,
  purchasing with the mock store unlocks Pro (`-mockPurchaseResult success|cancel|pending`).
- Use `accessibilityIdentifier`s, never localized text, to find elements, so the same tests pass in en and ja.
- Keep tests independent and deterministic (no sleeps; use `waitForExistence(timeout:)`).

## ScreenshotTests (`AppUITests/ScreenshotTests.swift`)
- One test per `mvp.screenshot_scenes` entry, in order, using `-seedDemoData` (and `-proUnlocked` for Pro scenes),
  status bar cleaned by the script (`xcrun simctl status_bar override`).
- Each test calls `snapshot("<scene_id>")` from `UITestSupport.swift`, which attaches the PNG as `scene-<scene_id>`
  (kept always) and writes it to `$FACTORY_SCREENSHOT_DIR` when set. The gate checks every scene id appears in this file.

## Run
```
app-factory xcode test            # unit + UI tests, en-US and ja → factory/reports/tests.json
```
The script runs `xcodebuild test` per language (`-testLanguage en|ja -testRegion US|JP`), exports results with
`xcrun xcresulttool get test-results tests` and calls `app-factory report tests en-US=… ja=…`.

Gate: report valid, zero failures, ≥5 unit and ≥2 UI tests passed, purchase/entitlement/paywall tests passed,
both locales tested, report matches current sources, screenshot scenes covered; with partial re-runs also: based on a
full run, app code identical to it, environment re-runs changed nothing, causes/notes recorded, within the limit.
## Re-running after a failure — classify the cause first
Read the failure (log in `.factory-tmp/logs/test-<locale>.log`, xcresult) and decide:

| cause | what to do | re-run |
|---|---|---|
| **app bug** (app behaves wrongly) | fix `App/**` (re-opens `implementation`) | **full**: `app-factory xcode test` |
| **environment** (simulator boot/launch timeout, springboard crash, Xcode/runner hiccup — no code at fault) | change nothing | `app-factory xcode test --only-failed --reason environment --note "<what happened>"` |
| **test defect** (wrong identifier, missing wait, wrong assertion in `AppTests/`/`AppUITests/`) | fix only the test code | `app-factory xcode test --only-failed --reason test-defect --note "<what was wrong>"` |

A partial re-run runs only the failed cases (for `test-defect` also every test of the changed test classes, in
both locales) and merges them into `factory/reports/tests.json`. It is refused when `App/**` or `project.yml`
changed since the full run, when `environment` is claimed but sources changed, after `testing.max_partial_reruns`
(default 2) partial re-runs, or without a note. `app-factory report rerun-plan --reason <cause>` shows what will run.
Tests that pass only on an environment re-run are listed as **flaky** (gate warning) — mention them in your report.
Never weaken an assertion just to make it pass, and never delete a failing test (removals are flagged).
