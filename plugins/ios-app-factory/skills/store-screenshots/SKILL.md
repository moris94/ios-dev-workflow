---
name: store-screenshots
description: Produce App Store screenshots in English and Japanese by capturing real app screens from XCUITest on the simulator and composing them reproducibly with the design concept's background, device frame and ASO captions at exact App Store sizes (6.9" iPhone 1320x2868 by default). Use for the factory "screenshots" stage.
user-invocable: false
---

# Store screenshots (stage `screenshots`)

Inputs: ScreenshotTests (testing stage), `design.json` `screenshot_style`, `aso.json` captions, `mvp.json` scene order,
`config.screenshots.devices` (default `iphone_6_9` → `APP_IPHONE_67`, 1320×2868; options: `iphone_6_5`, `ipad_13`).
Outputs: `factory/screenshots/raw/<locale>/<device>/<scene>.png`, `factory/screenshots/final/<locale>/<device>/NN_<scene>.png`,
`factory/screenshots/manifest.json`.

## 1. Capture real screens (macOS)
```
"${CLAUDE_PLUGIN_ROOT}/scripts/xcode/capture_screenshots.sh"
```
For each locale (en-US → `-testLanguage en -testRegion US`, ja → `ja`/`JP`) and device, the script boots the
simulator, overrides the status bar (9:41, full battery/signal), runs only `AppUITests/ScreenshotTests`, exports
the `scene-<id>` attachments and calls `app-factory screenshots collect`. Raw images must be genuine captures:
the gate verifies their pixel size matches the simulator class.

## 2. Compose
```
app-factory screenshots render
```
Deterministic Pillow renderer: background (solid/gradient/pattern from the design), caption block with kinsoku-aware
Japanese wrapping, rounded device frame with soft shadow, RGB PNG without alpha. Fonts: SF/Helvetica for en,
Hiragino for ja on macOS (Noto CJK on Linux); override in `config.screenshots.fonts`. The renderer refuses fonts
that lack glyphs for the caption (no tofu boxes).

## 3. Review
Open a few finals (Read tool on the PNG) and check: caption readable at thumbnail size, nothing important hidden behind
the caption, consistent with the design concept, Japanese line breaks natural. To change copy, edit `aso.json`
(re-gate `aso`), then re-render — never edit images by hand (hooks block writes to `final/`).

Gate: every locale × device × scene present, exact dimensions, RGB/no alpha, hashes match manifest, raw captures
come from the right simulator class, captions equal aso.json, recipe digest current, re-rendering is byte-identical.
