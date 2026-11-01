---
name: design-concept
description: Create a distinctive, accessible iOS design concept from the product charter — concept narrative, light/dark palette with WCAG contrast, Dynamic Type typography, shape/spacing tokens and the store-screenshot visual style — by consulting trusted design skills (Anthropic frontend-design) and Apple's Human Interface Guidelines, avoiding generic AI-template looks. Use for the factory "design" stage.
user-invocable: false
---

# Design concept (stage `design`)

Inputs: charter (principles, tone), MVP (screens, scenes), research (competitor visuals).
Outputs: `factory/artifacts/design/design.json` (schema `design`) and `design.md`.
Then `app-factory codegen` turns it into `App/Sources/Design/DesignTokens.swift`.

## 1. Consult trusted sources first (recorded in `references`)

1. **Design skills.** Check which design skills are available (the skill list in your context; if missing,
   recommend `/plugin install frontend-design@claude-plugins-official` or `anthropics/skills` → `frontend-design`).
   Follow Anthropic's **frontend-design** process: ground the design in the subject matter, write a compact
   token plan, then *review the plan against the brief and revise anything that reads as a default*. Its
   calibration list of AI-default looks (cream + terracotta, near-black + acid accent, SaaS card kit, gradient washes,
   ALL-CAPS eyebrows) applies to apps too.
   Record each as `{"type": "skill", "name": "frontend-design", "source": "anthropics/skills", "how_used": "..."}`.
2. **Apple HIG** (required by the gate): https://developer.apple.com/design/human-interface-guidelines/ —
   color (dynamic system colors, dark mode), typography (Dynamic Type text styles), layout, in-app purchase
   (paywall clarity, restore button), accessibility. Record as `type: guideline`.
3. Competitor visuals from research → list what you deliberately do differently.

## 2. Make deliberate choices

- `concept`: a name, a narrative tied to `derived_from_principles` (charter ids), 3–6 keywords.
- `anti_generic`: ≥3 `avoided_cliches` you considered and rejected, ≥2 `signature_elements` (the one or two
  memorable things — e.g. a specific shape language, an illustration motif, a type treatment), rationale.
- `color.light` / `color.dark`: `background, surface, text_primary, text_secondary, accent, accent_text, separator`.
  Gate: text ≥4.5:1 on background and surface, accent_text ≥4.5:1 on accent, accent ≥3:1 on background,
  accent must be ΔE ≥12 away from template defaults (Tailwind indigo/violet, iOS system blue used as-is,
  Claude terracotta, …). Derive the palette from the subject matter, not from a framework.
- `typography`: SwiftUI `Font.Design` (`default|rounded|serif|monospaced`, optionally a different
  `display_design` for titles) and Dynamic Type styles for `title/headline/body/caption` — never fixed sizes.
  Japanese renders in Hiragino; check that the chosen design reads well in both scripts.
- `shape` (corner radius, card style), `spacing.unit`, optional `iconography` (SF Symbols weight/rendering) and `motion`.
- `screenshot_style`: background (`solid|gradient|pattern`, 1–4 colours, angle, pattern), `caption_color`
  (≥3:1 on every background stop), `caption_weight`, `layout` (`caption_top|caption_bottom`), `device_frame`, `frame_color`.
  The store screenshots must look like *this* app's world, consistent with the in-app palette.

## 3. Verify

`app-factory validate factory/artifacts/design/design.json --schema design`, then
`app-factory gate design --owner <owner>`. Contrast failures: fix the colours, do not lower thresholds.
In `design.md` include the token table, light/dark swatches (hex), the rationale and the references.
