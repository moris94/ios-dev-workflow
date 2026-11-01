---
name: mvp-spec
description: Decide the MVP specification from the proposal and charter — features traced to principles with acceptance criteria, screens, SwiftData model, monetization (StoreKit 2, non-consumable first), privacy, category and the store screenshot scenes. Use for the factory "mvp" stage.
user-invocable: false
---

# MVP specification (stage `mvp`)

Inputs: proposal, charter, `factory/config.json`.
Outputs: `factory/artifacts/mvp/mvp.json` (schema `mvp`) and `mvp.md`.

## Rules checked by the gate

- `version` equals `config.app.version`.
- Every feature (`F1`…) traces to charter principles (`principle_ids`), lists `screens` that exist in `screens`,
  and has ≥1 testable `acceptance_criteria` (these become unit/UI tests).
- 1–8 `must` features. The free tier must deliver at least one must-have feature on its own.
- **Monetization is mandatory for the first release** (原則必須):
  - Prefer `model: non_consumable` (買い切り) — one `NON_CONSUMABLE` product, id
    `<bundle_id>.pro` (must start with `<bundle_id>.`), sensible `price_usd` (e.g. 2.99–9.99 based on competitor research).
  - Features unlocked by the product have `requires_pro: true`, and the product's `unlocks` lists exactly those ids.
  - `localizations` for `en-US` and `ja` — name ≤30 chars, description ≤45 chars (App Store limits). Japanese in Japanese.
  - Another model requires a ≥40-char `justification`; `none` requires a human `waiver` — never fill
    `approved_by` yourself; stop and ask.
  - Define `free_tier` (what's free) and `paywall_trigger` (when the paywall appears — must be a natural moment, not on launch).
- `screens`: ids in lowerCamel/snake (`home`, `editor`, `paywall`, `settings`). The implementation gate requires a
  SwiftUI `<Screen>View` per screen (`home` → `HomeView`).
- `data_model`: SwiftData entities (`UpperCamel`) with typed fields.
- `screenshot_scenes`: 3–10 scenes in store order. Each = `screen` + seeded `state` + `message` (the user benefit the
  screenshot sells). Include one scene that shows the Pro value (paywall or unlocked feature). The first two scenes
  carry most conversion — lead with the core benefit.
- `privacy` (data types collected, tracking) and App Store `category` (e.g. `PRODUCTIVITY`).
- `out_of_scope` — explicit list.

Finish with `app-factory gate mvp --owner <owner>`.
