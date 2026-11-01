---
name: product-charter
description: Define the product charter (憲章) — mission, value proposition, 3–7 testable product principles, non-goals, quality bar, bilingual tone of voice and decision rules — that every later stage (MVP, design, copy) must trace back to. Use for the factory "charter" stage.
user-invocable: false
---

# Product charter (stage `charter`)

Inputs: `factory/artifacts/proposal/proposal.json`, research.
Outputs: `factory/artifacts/charter/charter.json` (schema `charter`) and `charter.md`.

## How to write good principles

Each principle (`P1`…`P7`, 3–7 total) has:
- `statement` — a decision-making rule, not a slogan ("One-thumb capture: logging takes ≤ 2 taps").
- `rationale` — why, referencing research findings.
- `check` — how a reviewer/test verifies it (this is what later gates and QA use).

Also:
- `non_goals` (≥2) — what the app deliberately won't do in v1 (protects MVP scope).
- `quality_bar` — accessibility (Dynamic Type, VoiceOver, contrast), performance (cold start, no jank), privacy
  (data stays on device by default; SwiftData local store).
- `tone_of_voice` — `en-US` and `ja` (write the Japanese guidance in Japanese: です・ます調 or casual, and why).
- `decision_rules` — tie-breakers ("If a feature needs an account, it's out of v1").

Principles are referenced by id from `mvp.json` features and `design.json` — keep ids stable once published;
changing them later invalidates downstream stages.

Finish with `app-factory gate charter --owner <owner>`.
