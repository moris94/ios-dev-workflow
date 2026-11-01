---
name: swiftui-implementation
description: Implement the MVP as a SwiftUI + SwiftData iOS 17+ app on the factory template (XcodeGen project.yml), wire generated design tokens and product catalog, write unit tests from acceptance criteria, and verify with an xcodebuild build report. Use for the factory "implementation" stage.
user-invocable: false
---

# SwiftUI implementation (stage `implementation`)

Inputs: `mvp.json`, `design.json`, charter. Template already rendered by `app-factory init --scaffold`
(re-render missing files with `app-factory scaffold`).
Outputs (gate-checked): `project.yml`, `App/Sources/**`, `App/Resources/**` (except `*.xcstrings`, owned by
`localization`), `AppTests/**`, `factory/reports/build.json`.

## Project layout (template)

```
project.yml                      XcodeGen spec (targets App, AppTests, AppUITests; scheme with StoreKit config)
App/Sources/App/AppMain.swift    @main, ModelContainer, PurchaseManager injection, launch configuration
App/Sources/App/LaunchConfiguration.swift  UI-test hooks (-uiTesting, -seedDemoData, -proUnlocked, -resetState)
App/Sources/Models/              SwiftData @Model types (from mvp.data_model)
App/Sources/Store/               PurchaseManager (StoreKit 2), StoreClient protocol, ProductCatalog (generated)
App/Sources/Design/              DesignTokens (generated), shared components
App/Sources/Features/<Screen>/   <Screen>View.swift per mvp.screens id (home → HomeView)
App/Resources/                   Assets, Products.storekit (generated), PrivacyInfo.xcprivacy, *.xcstrings
AppTests/                        XCTest unit tests (Swift Testing @Test also counts)
AppUITests/                      XCUITest + ScreenshotTests (owned by qa / testing stage)
```

## Steps

1. `app-factory codegen` — regenerates `DesignTokens.swift`, `ProductCatalog.swift`, `Products.storekit` from
   artifacts. Never hand-edit them (the hooks block it); change `design.json`/`mvp.json` and regenerate.
2. Replace the template sample feature with the MVP: SwiftData models from `data_model`, one `<Screen>View`
   per `mvp.screens`, navigation, empty states, and the free/Pro split (`PurchaseManager.isPro`,
   `ProductCatalog.proFeatureIDs`). Follow `storekit-monetization` for the paywall.
3. Use only `DesignTokens.Palette/Typography/Metrics` for colours/fonts/spacing; Dynamic Type everywhere;
   VoiceOver labels on icon-only controls; respect Reduce Motion.
4. All user-facing strings as `LocalizedStringKey`/`String(localized:)` with English source text — the
   `localization` stage translates the extracted catalog. Use `Text(verbatim:)` only for non-language content.
5. Add `accessibilityIdentifier`s for every element UI tests and screenshots need
   (convention: `<screen>.<element>`, e.g. `home.addButton`).
6. Seeded demo data for screenshots lives in `LaunchConfiguration` (`-seedDemoData`), locale-aware
   (Japanese sample content when the app runs in `ja`). Screenshots must look real, not lorem ipsum.
7. Unit tests in `AppTests/` for each must-feature acceptance criterion that is testable without UI, and for
   entitlement logic (≥5 tests; the gate counts them). Use in-memory `ModelConfiguration(isStoredInMemoryOnly: true)`.
8. Build: `"${CLAUDE_PLUGIN_ROOT}/scripts/xcode/build.sh"` (runs xcodegen + xcodebuild, writes
   `factory/reports/build.json` with the source digest). Fix every error; keep warnings near zero.

Gate (`app-factory gate implementation`): required files, generated files current, no TODO/FIXME/placeholder,
SwiftData @Model + container, StoreKit 2 (`Transaction.updates`, `currentEntitlements`, `AppStore.sync`, `finish()`),
one `<Screen>View` per MVP screen, iOS 17+, ≥5 unit tests, successful build of the *current* sources.

On Linux/without Xcode the build cannot run: finish code + tests, then stop and report that
`scripts/xcode/build.sh` must be run on a Mac (the gate will stay failed until then).
