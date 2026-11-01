# ios-app-factory

Claude Code plugin that turns an app idea into a store-ready SwiftUI app: evidence-based market research,
proposal, product charter, MVP with StoreKit 2 one-time purchase, distinctive accessible design, SwiftUI +
SwiftData implementation, English + Japanese localization, unit/UI tests, reproducible App Store screenshots,
ASO metadata and an idempotent App Store Connect API sync. Every stage is connected by schema-validated
artifacts and machine-checked quality gates; state is persisted for resume; review submission and release
require an explicit human approval enforced by hooks and by the scripts.

Install:

```
/plugin marketplace add moris94/ios-dev-workflow
/plugin install ios-app-factory@ios-dev-workflow
```

Run in a new app repository: `/ios-app-factory:factory <your app idea>`.

Full documentation (Japanese): [../../README.md](../../README.md) · design: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)
