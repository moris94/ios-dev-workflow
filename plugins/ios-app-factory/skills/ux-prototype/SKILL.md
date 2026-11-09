---
name: ux-prototype
description: Define the app's 3–5 representative use cases (first run, core task, purchase/restore, …) as step-by-step UI/UX flows with wireframes and en/ja key copy, render them as storyboards in the design palette, and get them approved by a human before any implementation starts. Use for the factory "ux_review" stage.
user-invocable: false
---

# Representative use cases — UI/UX pre-approval (stage `ux_review`)

Inputs: `mvp.json` (features, screens, acceptance criteria, monetization), `charter.json` (principles, tone),
`design.json` (palette, shape), research (competitor UX pain points).
Outputs:
- `factory/artifacts/ux/ux.json` — schema `${CLAUDE_PLUGIN_ROOT}/lib/appfactory/schemas/ux.schema.json`
- `factory/artifacts/ux/ux.md` — readable review document (flows, rationale, open questions)
- `factory/artifacts/ux/storyboards/UCn.png` — rendered by `app-factory ux render` (never hand-edited)

Example: `${CLAUDE_PLUGIN_ROOT}/examples/sample-app/factory/artifacts/ux/ux.json`.

## 1. Choose the representative use cases (3–5)
They must together cover **every must-have feature** and include:
- `first_run` — the very first session: empty state → first success (charter's "time to value");
- `core` — the job users come back for, in ≤ 6 steps;
- `monetization` (when the MVP sells IAP) — the paywall at its natural trigger, price, one-time-purchase wording,
  **Restore Purchases**, and what happens after buying / cancelling;
- optionally `recovery` (errors, undo, delete) or `settings`.
Each use case: persona, trigger, goal, features, charter principles, success criteria, edge cases.

## 2. Describe each step with a wireframe
`screen` (an mvp screen id), `action` (what the user does), `expected` (what they see next), optional `copy`
(`en-US` + natural `ja`), and a `wireframe`: `title`, `presentation` (`root|push|sheet`), `nav` (`leading`/`trailing`
labels), `components` (stacked top to bottom: `text`, `list`, `button`, `field`, `toggle`, `card`, `empty`,
`segmented`, `price`, `image`, `divider`) and `tap` — the index of the component the user acts on, or
`"leading"`/`"trailing"` for a navigation-bar item (required on every step except the last).
Use realistic content (no lorem ipsum); the reviewer judges the experience, so the copy matters.

## 3. Render and self-review
```
app-factory ux render     # → factory/artifacts/ux/storyboards/UCn.png
```
Open every storyboard with the Read tool. Check against the charter: number of taps, clarity of the first-run screen,
honest paywall, consistent wording in both languages. Put the decisions the human should weigh in `review_focus`.

## 4. Human approval (in the chat — you cannot give it)
Report to the orchestrator: storyboard paths, one line per use case, and `review_focus`. The orchestrator shows them,
runs `app-factory approval request ux`, and the human either asks for changes (revise ux.json → render again) or
replies 「承認 UX」 in the conversation; the plugin's hook records that reply. The approval is bound to the exact
ux.json + storyboards; any later change needs a new approval. `app-factory ux status` shows whether it is approved.

Gate (`app-factory gate ux_review`): schema; screens/features/principles exist; all must features covered; first-run,
core and (with IAP) monetization use cases present; paywall shows Restore Purchases; Japanese copy is Japanese; tap
targets marked; storyboards current; valid human approval of the current UX.

Downstream: implementation follows the approved flows; the testing gate requires every use case id to be covered by a
UI test (mark the test with `// UCn`).
