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
"${CLAUDE_PLUGIN_ROOT}/scripts/xcode/test.sh"            # unit + UI tests, en-US and ja → factory/reports/tests.json
```
The script runs `xcodebuild test` per language (`-testLanguage en|ja -testRegion US|JP`), exports results with
`xcrun xcresulttool get test-results tests` and calls `app-factory report tests en-US=… ja=…`.

Gate: report valid, zero failures, ≥5 unit and ≥2 UI tests passed, purchase/entitlement/paywall tests passed,
both locales tested, report matches current sources, screenshot scenes covered.
When a test fails because of an app bug, fix the app (that re-opens `implementation`, which must re-pass its gate).
