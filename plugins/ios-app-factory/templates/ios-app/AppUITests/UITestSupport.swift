import XCTest

extension XCTestCase {
    /// Launches the app in deterministic UI-test mode.
    @MainActor
    func launchApp(_ extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-uiTesting", "-resetState"] + extra
        app.launch()
        return app
    }

    /// Captures the current screen as `scene-<name>` (kept as an xcresult attachment and,
    /// when FACTORY_SCREENSHOT_DIR is set via TEST_RUNNER_FACTORY_SCREENSHOT_DIR, written as PNG).
    @MainActor
    func snapshot(_ name: String) {
        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "scene-\(name)"
        attachment.lifetime = .keepAlways
        add(attachment)
        if let dir = ProcessInfo.processInfo.environment["FACTORY_SCREENSHOT_DIR"], !dir.isEmpty {
            let url = URL(fileURLWithPath: dir).appendingPathComponent("scene-\(name).png")
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? screenshot.pngRepresentation.write(to: url)
        }
    }
}
