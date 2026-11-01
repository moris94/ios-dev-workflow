import SwiftData
import SwiftUI

@main
struct AppMain: App {
    @State private var purchaseManager: PurchaseManager
    private let modelContainer: ModelContainer

    init() {
        let launch = LaunchConfiguration.current
        let client: any StoreClient = launch.useMockStore ? MockStoreClient(configuration: launch) : StoreKitClient()
        _purchaseManager = State(initialValue: PurchaseManager(client: client))
        modelContainer = ModelContainerFactory.make(inMemory: launch.isUITesting)
        if launch.seedDemoData {
            DemoData.seed(into: modelContainer.mainContext, locale: .current)
        }
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(purchaseManager)
                .task { await purchaseManager.start() }
                .transaction { transaction in
                    if LaunchConfiguration.current.isUITesting { transaction.disablesAnimations = true }
                }
        }
        .modelContainer(modelContainer)
    }
}

struct RootView: View {
    var body: some View {
        NavigationStack {
            HomeView()
        }
        .tint(DesignTokens.Palette.accent)
    }
}
