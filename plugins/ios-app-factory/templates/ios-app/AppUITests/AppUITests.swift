import XCTest

/// Flows from mvp.json acceptance criteria. Elements are found by accessibility identifier,
/// so the same tests pass in English and Japanese (test.sh runs both).
final class AppUITests: XCTestCase {
    @MainActor
    func testEmptyStateThenAddNote() {
        let app = launchApp()
        XCTAssertTrue(app.descendants(matching: .any)["home.emptyState"].waitForExistence(timeout: 5))
        app.buttons["home.addButton"].tap()
        let title = app.textFields["editor.title"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        title.typeText("Groceries")
        app.buttons["editor.save"].tap()
        XCTAssertTrue(app.buttons["home.row"].firstMatch.waitForExistence(timeout: 5))
    }

    @MainActor
    func testEditExistingNote() {
        let app = launchApp(["-seedDemoData"])
        let row = app.buttons["home.row"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        row.tap()
        XCTAssertTrue(app.textFields["editor.title"].waitForExistence(timeout: 5))
        app.buttons["editor.cancel"].tap()
    }

    @MainActor
    func testPaywallShowsPriceAndRestore() {
        let app = launchApp()
        app.buttons["home.settingsButton"].tap()
        app.buttons["settings.unlockPro"].tap()
        XCTAssertTrue(app.buttons["paywall.buyButton"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["paywall.restoreButton"].exists)
        XCTAssertTrue(app.staticTexts["paywall.terms"].exists)
        app.buttons["paywall.close"].tap()
    }

    @MainActor
    func testPurchaseUnlocksPro() {
        let app = launchApp(["-mockPurchaseResult", "success"])
        app.buttons["home.settingsButton"].tap()
        app.buttons["settings.unlockPro"].tap()
        let buy = app.buttons["paywall.buyButton"]
        XCTAssertTrue(buy.waitForExistence(timeout: 5))
        buy.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings.proStatus"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testPendingPurchaseShowsMessage() {
        let app = launchApp(["-mockPurchaseResult", "pending"])
        app.buttons["home.settingsButton"].tap()
        app.buttons["settings.unlockPro"].tap()
        app.buttons["paywall.buyButton"].tap()
        XCTAssertTrue(app.staticTexts["paywall.pending"].waitForExistence(timeout: 5))
    }
}
