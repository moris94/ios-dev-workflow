---
name: asc-sync
description: Synchronise App Store Connect via the official REST API — app info (name, subtitle, privacy URL, category), version metadata (description, keywords, promotional text, URLs), MANUAL release type, free app price, non-consumable IAP with en/ja localizations, price schedule, availability and review screenshot, and screenshot sets — as an idempotent, ledger-protected plan with dry-run. Never submits for review. Use for the factory "asc_sync" stage.
user-invocable: false
---

# App Store Connect sync (stage `asc_sync`)

Credentials (environment only, never printed): `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY_PATH`
(or `ASC_PRIVATE_KEY` / `ASC_PRIVATE_KEY_BASE64`). JWT ES256, `aud=appstoreconnect-v1`, ≤20 min lifetime.
Prerequisite: the app record exists in App Store Connect (the API cannot create apps) with the bundle id from config.

## Commands
```
app-factory asc plan                 # dry-run: desired state vs remote → factory/asc/plan.json (+ validation)
app-factory asc plan --fixture f.json  # dry-run against a saved remote snapshot (offline)
app-factory asc apply --simulate     # full apply/verify against the built-in ASC simulator (offline rehearsal)
app-factory asc apply                # live apply (requires config asc.mode = "apply")
```
Without credentials, `plan` diffs against an empty remote and shows every operation that would be sent.
With credentials, `plan` performs read-only GETs.

## How it stays safe
- **Desired-state diff**: only changed fields are PATCHed; screenshots are compared by MD5 `sourceFileChecksum`,
  so unchanged images are never re-uploaded.
- **Ledger** (`factory/asc/ledger.json`, committed): each op has a deterministic key; applied ops are never re-sent,
  even after a crash or from another machine. POSTs are not blindly retried: an unknown outcome is marked
  `uncertain` and reconciled with a lookup before any resend. Reserved-but-uncommitted uploads are cleaned up.
- **Verification**: after apply, the remote state is re-read and re-planned; the gate requires zero remaining ops.
- **Scope**: the sync plan can never contain review submission or release endpoints (validated); `releaseType` is forced to `MANUAL`.

## Things the API does not cover (put in the final report for the human)
App Privacy "nutrition label" answers, age-rating questionnaire review, tax/banking agreements, the first app-record creation.

Gate: plan schema + request-body validation, plan current with aso/mvp/screenshots, no blocking issues; in
`apply` mode the live sync must be applied and converged. In `dry-run` mode the gate passes with a warning and
release readiness will later require the live apply.
