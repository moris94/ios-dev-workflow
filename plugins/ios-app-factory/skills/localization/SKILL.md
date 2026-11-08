---
name: localization
description: Localize the iOS app with English as the development/default language and complete Japanese using String Catalogs (Localizable.xcstrings, InfoPlist.xcstrings) — plurals, format specifiers, natural Japanese UI copy, locale-aware formatting — verified by the localization gate. Use for the factory "localization" stage.
user-invocable: false
---

# Localization en (default) + ja (stage `localization`)

Outputs: `App/Resources/Localizable.xcstrings`, `App/Resources/InfoPlist.xcstrings`.

## Steps
1. Make sure the catalog contains every key used in code. On macOS, building the project extracts keys
   (`app-factory xcode build`); otherwise add entries manually. The gate scans Swift for
   `Text("…")`, `Button("…")`, `Label`, `Toggle`, `navigationTitle`, `String(localized:)`, `accessibilityLabel` … literals
   and fails on any key missing from the catalog.
2. For each key: `en` source (the key itself or an explicit `en` stringUnit) and a `ja` stringUnit with
   `"state": "translated"`. Plurals use `variations.plural` (`one`/`other` in en; `other` in ja).
3. Keep format specifiers identical between en and ja (`%@`, `%lld`, positional `%1$@` when the order changes).
4. Japanese quality (per charter tone of voice): natural UI Japanese, not literal translation; consistent
   です・ます or plain style; short button labels (保存, 完了, 購入を復元); full-width punctuation 「」、。;
   no spaces between Japanese and numbers unless the style guide says so; IAP wording 「買い切り」「一度の購入でずっと使えます」.
5. `InfoPlist.xcstrings`: `CFBundleDisplayName`, `CFBundleName`, and every usage-description key the app uses
   (e.g. `NSCameraUsageDescription`) in en and ja.
6. Formatting: use `Date.FormatStyle`, `.formatted()`, `Measurement`, `Decimal.FormatStyle.Currency` — never
   hand-built date/number strings. Prices only from StoreKit `displayPrice`.
7. Remove keys that are `extractionState: stale` (gate warns).

Format reference (one entry):
```json
"Add Habit": {"localizations": {"ja": {"stringUnit": {"state": "translated", "value": "習慣を追加"}}}}
```

Gate (`app-factory gate localization`): sourceLanguage `en`; every key translated to ja; no empty values;
format specifiers match; InfoPlist display name localized; all literal UI strings in code exist in the catalog;
project.yml has `developmentLanguage: en`; Info.plist lists en and ja in `CFBundleLocalizations`; ≥10 localized strings.
UI tests in the `testing` stage run in both languages; screenshots are captured in both.
