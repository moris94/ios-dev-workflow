import Foundation
import Observation

/// Owns purchase state for the whole app. Entitlements always come from the store
/// (`Transaction.currentEntitlements` in production), never from local flags.
@MainActor
@Observable
final class PurchaseManager {
    enum Phase: Equatable {
        case idle
        case loading
        case purchasing
        case pending
        case failed(String)
    }

    private(set) var products: [StoreProduct] = []
    private(set) var ownedProductIDs: Set<String> = []
    private(set) var phase: Phase = .idle

    private let client: any StoreClient
    private var updatesTask: Task<Void, Never>?

    init(client: any StoreClient) {
        self.client = client
    }

    var isPro: Bool { !ownedProductIDs.isDisjoint(with: ProductCatalog.proUnlocking) }
    var access: FeatureAccess { FeatureAccess(isPro: isPro) }
    var proProduct: StoreProduct? { products.first { ProductCatalog.proUnlocking.contains($0.id) } }

    /// Call once at launch: listens for transaction updates, then loads entitlements and products.
    func start() async {
        if updatesTask == nil {
            let updates = client.transactionUpdates()
            updatesTask = Task { [weak self] in
                for await _ in updates {
                    await self?.refreshEntitlements()
                }
            }
        }
        await refreshEntitlements()
        await loadProducts()
    }

    func loadProducts() async {
        phase = .loading
        do {
            products = try await client.products(for: ProductCatalog.all)
            phase = .idle
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    func refreshEntitlements() async {
        ownedProductIDs = await client.currentEntitlementIDs()
    }

    @discardableResult
    func purchase(productID: String) async -> PurchaseOutcome? {
        phase = .purchasing
        do {
            let outcome = try await client.purchase(productID: productID)
            switch outcome {
            case .purchased:
                await refreshEntitlements()
                phase = .idle
            case .cancelled:
                phase = .idle
            case .pending:
                phase = .pending
            }
            return outcome
        } catch {
            phase = .failed(error.localizedDescription)
            return nil
        }
    }

    /// "Restore Purchases" (App Review requirement for non-consumables).
    func restore() async {
        phase = .loading
        do {
            try await client.sync()
            await refreshEntitlements()
            phase = .idle
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }
}

/// Free vs Pro rules. Feature ids come from mvp.json via the generated ProductCatalog.
struct FeatureAccess: Equatable {
    static let freeItemLimit = 10

    let isPro: Bool

    func canCreateItem(currentCount: Int) -> Bool {
        isPro || currentCount < Self.freeItemLimit
    }

    func isUnlocked(featureID: String) -> Bool {
        isPro || !ProductCatalog.proFeatureIDs.contains(featureID)
    }
}
