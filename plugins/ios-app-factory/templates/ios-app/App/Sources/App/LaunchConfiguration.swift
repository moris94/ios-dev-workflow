import Foundation

/// Launch arguments used by UI tests and screenshot capture.
///
/// - `-uiTesting`: in-memory store, mock StoreKit client, no animations
/// - `-seedDemoData`: realistic, locale-aware sample content for screenshots
/// - `-proUnlocked`: start with the Pro entitlement (mock store only)
/// - `-resetState`: ignore persisted preferences
/// - `-mockPurchaseResult success|cancel|pending|failure`
struct LaunchConfiguration: Sendable {
    let isUITesting: Bool
    let seedDemoData: Bool
    let proUnlocked: Bool
    let resetState: Bool
    let mockPurchaseResult: MockPurchaseResult

    static let current = LaunchConfiguration(arguments: ProcessInfo.processInfo.arguments)

    init(arguments: [String]) {
        isUITesting = arguments.contains("-uiTesting")
        seedDemoData = arguments.contains("-seedDemoData")
        proUnlocked = arguments.contains("-proUnlocked")
        resetState = arguments.contains("-resetState")
        if let index = arguments.firstIndex(of: "-mockPurchaseResult"),
           arguments.indices.contains(index + 1),
           let result = MockPurchaseResult(rawValue: arguments[index + 1]) {
            mockPurchaseResult = result
        } else {
            mockPurchaseResult = .success
        }
    }

    var useMockStore: Bool { isUITesting }
}

enum MockPurchaseResult: String, Sendable {
    case success, cancel, pending, failure
}
