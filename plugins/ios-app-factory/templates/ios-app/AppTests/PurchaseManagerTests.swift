import XCTest
@testable import __PROJECT_NAME__

@MainActor
final class PurchaseManagerTests: XCTestCase {
    private let pro = ProductCatalog.proUnlocking.first ?? ProductCatalog.all[0]

    func testPurchaseSuccessUnlocksPro() async {
        let manager = PurchaseManager(client: MockStoreClient(result: .success))
        await manager.start()
        XCTAssertFalse(manager.isPro)
        let outcome = await manager.purchase(productID: pro)
        XCTAssertEqual(outcome, .purchased)
        XCTAssertTrue(manager.isPro)
        XCTAssertEqual(manager.phase, .idle)
    }

    func testPurchaseCancelledKeepsFreeTier() async {
        let manager = PurchaseManager(client: MockStoreClient(result: .cancel))
        await manager.start()
        let outcome = await manager.purchase(productID: pro)
        XCTAssertEqual(outcome, .cancelled)
        XCTAssertFalse(manager.isPro)
    }

    func testPurchasePendingAskToBuyIsNotPro() async {
        let manager = PurchaseManager(client: MockStoreClient(result: .pending))
        await manager.start()
        await manager.purchase(productID: pro)
        XCTAssertEqual(manager.phase, .pending)
        XCTAssertFalse(manager.isPro)
    }

    func testPurchaseFailureReportsError() async {
        let manager = PurchaseManager(client: MockStoreClient(result: .failure))
        await manager.start()
        let outcome = await manager.purchase(productID: pro)
        XCTAssertNil(outcome)
        if case .failed = manager.phase {} else { XCTFail("expected failed phase") }
    }

    func testRestoreReflectsExistingEntitlement() async {
        let manager = PurchaseManager(client: MockStoreClient(owned: [pro]))
        await manager.restore()
        XCTAssertTrue(manager.isPro)
    }

    func testProductsLoadedForCatalog() async {
        let manager = PurchaseManager(client: MockStoreClient())
        await manager.loadProducts()
        XCTAssertEqual(Set(manager.products.map(\.id)), Set(ProductCatalog.all))
        XCTAssertNotNil(manager.proProduct)
    }
}

final class FeatureAccessTests: XCTestCase {
    func testFreeTierHasLimit() {
        let access = FeatureAccess(isPro: false)
        XCTAssertTrue(access.canCreateItem(currentCount: FeatureAccess.freeItemLimit - 1))
        XCTAssertFalse(access.canCreateItem(currentCount: FeatureAccess.freeItemLimit))
    }

    func testProIsUnlimited() {
        XCTAssertTrue(FeatureAccess(isPro: true).canCreateItem(currentCount: 10_000))
    }

    func testProFeaturesLockedForFreeUsers() {
        for feature in ProductCatalog.proFeatureIDs {
            XCTAssertFalse(FeatureAccess(isPro: false).isUnlocked(featureID: feature))
            XCTAssertTrue(FeatureAccess(isPro: true).isUnlocked(featureID: feature))
        }
    }

    func testLaunchConfigurationParsesArguments() {
        let config = LaunchConfiguration(arguments: ["app", "-uiTesting", "-proUnlocked", "-mockPurchaseResult", "pending"])
        XCTAssertTrue(config.isUITesting)
        XCTAssertTrue(config.proUnlocked)
        XCTAssertEqual(config.mockPurchaseResult, .pending)
        XCTAssertFalse(config.seedDemoData)
    }
}
