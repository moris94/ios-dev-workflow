import StoreKit
import StoreKitTest
import XCTest
@testable import __PROJECT_NAME__

/// Exercises the real StoreKit 2 code path against the local Products.storekit configuration.
final class StoreKitConfigurationTests: XCTestCase {
    func testAllCatalogProductsExistInStoreKitConfiguration() async throws {
        let session = try SKTestSession(configurationFileNamed: "Products")
        session.resetToDefaultState()
        session.disableDialogs = true
        let products = try await StoreKitClient().products(for: ProductCatalog.all)
        XCTAssertEqual(Set(products.map(\.id)), Set(ProductCatalog.all))
        XCTAssertTrue(products.allSatisfy { !$0.displayPrice.isEmpty })
    }

    func testPurchaseGrantsEntitlementAndRefundRevokesIt() async throws {
        let session = try SKTestSession(configurationFileNamed: "Products")
        session.resetToDefaultState()
        session.disableDialogs = true
        session.clearTransactions()
        let client = StoreKitClient()
        let pro = try XCTUnwrap(ProductCatalog.proUnlocking.first)

        let outcome = try await client.purchase(productID: pro)
        XCTAssertEqual(outcome, .purchased)
        let owned = await client.currentEntitlementIDs()
        XCTAssertTrue(owned.contains(pro))

        if let transaction = session.allTransactions().first(where: { $0.productIdentifier == pro }) {
            try session.refundTransaction(identifier: transaction.identifier)
            let afterRefund = await client.currentEntitlementIDs()
            XCTAssertFalse(afterRefund.contains(pro))
        }
    }
}
