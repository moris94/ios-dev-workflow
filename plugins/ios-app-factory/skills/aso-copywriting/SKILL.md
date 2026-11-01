---
name: aso-copywriting
description: App Store Optimization copy for en-US and ja — app name, subtitle, keyword field, promotional text, description, URLs and the screenshot caption for every MVP scene — grounded in research keywords and the charter's tone, within App Store character limits. Use for the factory "aso" stage.
user-invocable: false
---

# ASO metadata & captions (stage `aso`)

Inputs: research (competitors, user language in reviews), charter (tone), mvp (features, scenes), design (caption style).
Output: `factory/artifacts/aso/aso.json` (schema `aso`).

## Limits (App Store Connect) — gate-enforced
| field | limit |
|---|---|
| name | 30 |
| subtitle | 30 |
| keywords | 100 (comma-separated, **no spaces around commas**, no duplicates) |
| promotional_text | 170 (can be changed without review) |
| description | 4000 (gate: ≥300) |
| caption headline | en ≤34, ja ≤18 characters |

## Principles
- **Keyword research** (`keyword_research`, ≥4 entries with rationale and source ids): use terms real users write
  in reviews/searches in each language; Japanese keywords are not translations of English ones — research them
  separately (ひらがな/カタカナ/漢字 variants matter).
- Don't repeat words already in the name/subtitle in the keyword field (they're indexed already); no competitor
  brand names; no prices, "free", "best", "#1" in name/subtitle/keywords (App Review 2.3.7).
- Name: brand + core function; must differ from every researched competitor name.
- Subtitle: the core benefit, not a feature list.
- Description: first 3 lines sell (visible before "more"); then features, Pro (one-time purchase) explanation,
  privacy stance; ja written natively in the charter's tone.
- Captions: one per `mvp.screenshot_scenes` id — benefit-first headline (≤5 words en), optional subline.
  They will be composed onto screenshots, so they must be short and readable at thumbnail size.
- URLs: `support_url` and `privacy_policy_url` must equal `config.app.links.support` / `privacy_policy`. By default
  the `support_page` stage published one combined page and set both links to its URL, so both fields use that same URL.
  `marketing_url` is optional.

Finish with `app-factory gate aso --owner <owner>`.
