---
name: product-proposal
description: Write the evidence-backed app proposal (企画書) from the research artifact — problem, target users, value proposition, differentiation vs named competitors, key features, monetization hypothesis, success metrics, risks. Use for the factory "proposal" stage.
user-invocable: false
---

# App proposal (stage `proposal`)

Inputs: `factory/idea.md`, `factory/artifacts/research/research.json` (+ `.md`).
Outputs:
- `factory/artifacts/proposal/proposal.json` — schema `proposal` (`${CLAUDE_PLUGIN_ROOT}/lib/appfactory/schemas/proposal.schema.json`)
- `factory/artifacts/proposal/proposal.md` — 企画書 for humans (≥400 chars, English with a short Japanese summary at the top)

## Content rules

- `problem` and `value_proposition` must follow from research pain points and gaps.
- `differentiation` (≥2): each point names the competitors it beats in `vs_competitors` and cites
  `evidence_source_ids` from research.
- `key_features` (≥3) with `must/should/could`; 1–7 `must` items. Be ruthless: a first release
  wins by doing one job clearly better.
- `monetization_hypothesis`: default to `non_consumable` (one-time Pro unlock). Choose another model only
  when research shows it is clearly better, and explain why. `free` is not acceptable for the first release.
- `success_metrics` (≥2) must be measurable (e.g. "paywall → purchase ≥ 4% in first 30 days").
- `risks` with mitigations (App Review, competition, scope).

Finish with `app-factory gate proposal --owner <owner>`.
