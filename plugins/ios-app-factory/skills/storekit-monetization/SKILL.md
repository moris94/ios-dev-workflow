---
name: storekit-monetization
description: StoreKit 2 monetization for the first release — non-consumable (買い切り) Pro unlock by default — covering product definition in mvp.json, the PurchaseManager (Transaction.updates, currentEntitlements, verification, finish, AppStore.sync restore), an App Review-compliant paywall, local StoreKit testing (Products.storekit, SKTestSession) and sandbox/TestFlight purchase checks. Use when specifying or implementing in-app purchases.
user-invocable: false
---

# StoreKit 2 monetization

## Spec (mvp stage)
- Default: one `NON_CONSUMABLE` product `<bundle_id>.pro`, price from research (typically $2.99–$9.99).
- Subscriptions only with a written justification (ongoing server cost / continuous content). Consumables only for genuinely consumable value.
- Free tier must be genuinely useful; paywall appears at a natural moment (hitting a free limit or tapping a Pro feature), never on first launch.

## Implementation (template `App/Sources/Store/`)
- `StoreClient` protocol abstracts StoreKit (`products(for:)`, `purchase(_:)`, `currentEntitlementIDs()`, `sync()`, `updates`) so logic is unit-testable with `MockStoreClient`.
- `PurchaseManager` (`@MainActor @Observable`):
  - starts a `Task` over `Transaction.updates` at launch; verifies (`VerificationResult.verified` only), updates entitlements, calls `transaction.finish()`;
  - derives `isPro` from `Transaction.currentEntitlements` (ignores revoked/refunded: `revocationDate == nil`);
  - `purchase(productID:)` handles `.success`, `.userCancelled`, `.pending` (Ask to Buy) distinctly;
  - `restore()` calls `AppStore.sync()` then refreshes entitlements;
  - product IDs only via generated `ProductCatalog`.
- Paywall (`PaywallView`) — App Review 3.1.1/3.1.2 and HIG: localized `displayPrice` from StoreKit (never hard-coded), clear one-time-purchase wording ("One-time purchase" / 「買い切り」), what is unlocked, a visible **Restore Purchases** button, close button, links to Terms/Privacy, loading and error states, no fake urgency.
- Never gate data the user already created behind the paywall (export/view stays free).

## Testing
- Unit tests with `MockStoreClient`: purchase success → isPro, cancel → not pro, pending → not pro + message, revoked → not pro, restore → refresh.
- `StoreKitConfigurationTests` with `SKTestSession(configurationFileNamed: "Products")` to purchase/refund against the local config.
- UI tests launch with `-uiTesting` (mock store) and assert the paywall shows price and restore button in en and ja.
- Optional (`release.require_manual_purchase_test`): a human confirms a TestFlight/sandbox purchase test in the chat (「承認 課金テスト」): purchase, restore on reinstall, en/ja paywall.

## App Store Connect
`app-factory asc plan/apply` creates the IAP (`/v2/inAppPurchases`), en-US/ja localizations, price schedule (base territory USA, auto-equalized), availability, and the App Review screenshot from the paywall capture. First-time IAPs are submitted together with the app version at submission.
