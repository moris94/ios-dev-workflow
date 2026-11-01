import Foundation
import StoreKit

struct StoreProduct: Identifiable, Sendable, Equatable {
    let id: String
    let displayName: String
    let description: String
    let displayPrice: String
}

enum PurchaseOutcome: Sendable, Equatable {
    case purchased
    case cancelled
    case pending
}

enum StoreError: LocalizedError, Equatable {
    case productNotFound
    case failedVerification
    case purchaseFailed

    var errorDescription: String? {
        switch self {
        case .productNotFound: String(localized: "The product is not available right now.")
        case .failedVerification: String(localized: "The purchase could not be verified.")
        case .purchaseFailed: String(localized: "The purchase could not be completed.")
        }
    }
}

/// Abstraction over StoreKit 2 so purchase logic is unit-testable.
protocol StoreClient: Sendable {
    func products(for ids: [String]) async throws -> [StoreProduct]
    func purchase(productID: String) async throws -> PurchaseOutcome
    func currentEntitlementIDs() async -> Set<String>
    func sync() async throws
    /// Emits whenever a transaction update arrives (renewal, refund, Ask to Buy approval, other device).
    func transactionUpdates() -> AsyncStream<Void>
}

/// Production StoreKit 2 implementation.
final class StoreKitClient: StoreClient {
    private let cache = ProductCache()

    func products(for ids: [String]) async throws -> [StoreProduct] {
        let products = try await Product.products(for: ids)
        await cache.store(products)
        return products
            .sorted { $0.price < $1.price }
            .map { StoreProduct(id: $0.id, displayName: $0.displayName, description: $0.description, displayPrice: $0.displayPrice) }
    }

    func purchase(productID: String) async throws -> PurchaseOutcome {
        let product: Product
        if let cached = await cache.product(id: productID) {
            product = cached
        } else if let fetched = try await Product.products(for: [productID]).first {
            product = fetched
        } else {
            throw StoreError.productNotFound
        }
        switch try await product.purchase() {
        case .success(let verification):
            let transaction = try Self.verified(verification)
            await transaction.finish()
            return .purchased
        case .userCancelled:
            return .cancelled
        case .pending:
            return .pending
        @unknown default:
            throw StoreError.purchaseFailed
        }
    }

    func currentEntitlementIDs() async -> Set<String> {
        var owned = Set<String>()
        for await result in Transaction.currentEntitlements {
            if case .verified(let transaction) = result, transaction.revocationDate == nil {
                owned.insert(transaction.productID)
            }
        }
        return owned
    }

    func sync() async throws {
        try await AppStore.sync()
    }

    func transactionUpdates() -> AsyncStream<Void> {
        AsyncStream { continuation in
            let task = Task.detached {
                for await result in Transaction.updates {
                    if case .verified(let transaction) = result {
                        await transaction.finish()
                    }
                    continuation.yield(())
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    static func verified<T>(_ result: VerificationResult<T>) throws -> T {
        switch result {
        case .verified(let value): return value
        case .unverified: throw StoreError.failedVerification
        }
    }
}

private actor ProductCache {
    private var products: [String: Product] = [:]

    func store(_ items: [Product]) {
        for item in items { products[item.id] = item }
    }

    func product(id: String) -> Product? { products[id] }
}

/// Deterministic store used by UI tests and screenshots (`-uiTesting`). Never used in release builds' normal launch.
final class MockStoreClient: StoreClient, @unchecked Sendable {
    private let lock = NSLock()
    private var owned: Set<String>
    private let result: MockPurchaseResult

    init(owned: Set<String> = [], result: MockPurchaseResult = .success) {
        self.owned = owned
        self.result = result
    }

    convenience init(configuration: LaunchConfiguration) {
        self.init(owned: configuration.proUnlocked ? ProductCatalog.proUnlocking : [], result: configuration.mockPurchaseResult)
    }

    func products(for ids: [String]) async throws -> [StoreProduct] {
        ids.map { id in
            let price = ProductCatalog.referencePriceUSD[id] ?? 0
            return StoreProduct(id: id,
                                displayName: String(localized: "Pro"),
                                description: String(localized: "Unlock everything, forever."),
                                displayPrice: price.formatted(.currency(code: "USD")))
        }
    }

    func purchase(productID: String) async throws -> PurchaseOutcome {
        switch result {
        case .success:
            lock.withLock { _ = owned.insert(productID) }
            return .purchased
        case .cancel: return .cancelled
        case .pending: return .pending
        case .failure: throw StoreError.purchaseFailed
        }
    }

    func currentEntitlementIDs() async -> Set<String> {
        lock.withLock { owned }
    }

    func sync() async throws {}

    func transactionUpdates() -> AsyncStream<Void> {
        AsyncStream { _ in }
    }
}
