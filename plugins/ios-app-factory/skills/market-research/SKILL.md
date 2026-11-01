---
name: market-research
description: Evidence-based competitor and demand research for an iOS app idea, producing factory/artifacts/research/research.json + research.md with cited sources, App Store competitors, demand signals, pain points, market gaps and a GO/NO-GO verdict. Use for the factory "research" stage.
user-invocable: false
---

# Market research (stage `research`)

Input: `factory/idea.md`, `factory/config.json` (`research.min_competitors`, `research.min_sources`).
Output:
- `factory/artifacts/research/research.json` — schema `${CLAUDE_PLUGIN_ROOT}/lib/appfactory/schemas/research.schema.json`
- `factory/artifacts/research/research.md` — readable report (≥400 chars) citing `[S1]`-style ids

Example of the expected shape: `${CLAUDE_PLUGIN_ROOT}/examples/sample-app/factory/artifacts/research/research.json`
(it is an illustrative fixture with placeholder URLs — never copy its facts).

## Method

1. **Search broadly and log every query** in `search_log` (≥5; `tool` = WebSearch/WebFetch).
   Do the searches in English *and* Japanese (the app ships en + ja):
   - App Store: `site:apps.apple.com <category keywords>`, top charts for the category, "best <x> app 2026".
   - Reviews/complaints: App Store reviews, Reddit, Hacker News, note.com, Qiita/Zenn, X discussions.
   - Demand: Google Trends notes, statistics pages, articles about the problem, forum threads asking for a solution.
2. **Fetch** the pages you cite (WebFetch) — every `source` must be a page you actually opened.
   Record `retrieved_at` (today, ISO date) and a `type`.
3. **Competitors** (≥ min_competitors, ≥3 with `apps.apple.com` URLs): price model and price notes,
   rating/rating_count if visible, concrete strengths and weaknesses (from reviews, not guesses).
4. **Demand signals** (≥3, from ≥3 independent sources), each with strength `weak|moderate|strong` and
   the evidence quoted or paraphrased.
5. **Pain points** and **market gaps** — gaps must be things competitors demonstrably do badly or not at all.
6. **Verdict**: `go` only if there is real demand *and* a credible gap a small first release can win.
   Be honest — a NO-GO stops the pipeline for a human decision, which is the correct outcome for a weak idea.

## Rules

- No invented numbers, ratings, URLs or quotes. If a value is unknown, use `null`/"unknown".
- Every claim cites `source_ids` that exist in `sources`; ids are `S1`, `S2`, …; URLs are unique `https://`.
- Note monetization patterns of competitors (one-time purchase vs subscription) — the MVP prefers 買い切り (non-consumable).

## Finish

`app-factory validate factory/artifacts/research/research.json --schema research`, then
`app-factory gate research --owner <owner>` and return the summary.
