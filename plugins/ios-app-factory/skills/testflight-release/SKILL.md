---
name: testflight-release
description: Archive and upload the tested build to TestFlight with Fastlane (API key auth), verify processing via the App Store Connect API, guide the human sandbox purchase test, and compute the release-readiness digest that a human approves. Use for the factory "testflight" and "release_readiness" stages.
user-invocable: false
---

# TestFlight & release readiness

## testflight
1. Make sure `config.app.build_number` is higher than any uploaded build (bump it in `factory/config.json`
   and `project.yml` together; this re-opens dependent stages, which is intended).
2. `app-factory xcode testflight` — runs `bundle exec fastlane beta`
   (`build_app` + `upload_to_testflight` with `skip_submission: true`, internal testers only,
   `app_store_connect_api_key` from env). It never distributes externally or submits.
3. `app-factory testflight verify` — waits for the build in App Store Connect and writes
   `factory/reports/testflight.json` (processing state must be `VALID`; build must come from the tested sources).
   Re-run later if the build is still processing.
Offline rehearsal: `app-factory testflight verify --simulate`.

## release_readiness
1. Ask the human to test the TestFlight build on a device with a Sandbox account (purchase, restore after reinstall,
   paywall in English and Japanese) and record it in **their** terminal: `app-factory evidence purchase-test`.
   (The hooks block the agent from recording evidence.)
2. `app-factory release readiness` — checks every pre-release stage passed, live ASC sync converged,
   TestFlight build == tested sources == current sources, purchase evidence for this build; writes
   `factory/artifacts/release/readiness.json` with a `readiness_digest`.
3. `app-factory gate release_readiness`.
4. `app-factory release submit --dry-run` to show exactly what submission will do, then hand over to the human
   (see `release-approval`).
