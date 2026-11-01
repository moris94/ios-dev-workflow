import XCTest

/// One test per mvp.json `screenshot_scenes` entry (ids must match).
/// Run by scripts/xcode/capture_screenshots.sh per language and device.
final class ScreenshotTests: XCTestCase {
    @MainActor
    func test01Home() {
        let app = launchApp(["-seedDemoData"])
        XCTAssertTrue(app.buttons["home.row"].firstMatch.waitForExistence(timeout: 10))
        snapshot("home")
    }

    @MainActor
    func test02Editor() {
        let app = launchApp(["-seedDemoData"])
        app.buttons["home.row"].firstMatch.tap()
        XCTAssertTrue(app.textFields["editor.title"].waitForExistence(timeout: 10))
        snapshot("editor")
    }

    @MainActor
    func test03Pro() {
        let app = launchApp(["-seedDemoData"])
        app.buttons["home.settingsButton"].tap()
        app.buttons["settings.unlockPro"].tap()
        XCTAssertTrue(app.buttons["paywall.buyButton"].waitForExistence(timeout: 10))
        snapshot("pro")
    }
}
