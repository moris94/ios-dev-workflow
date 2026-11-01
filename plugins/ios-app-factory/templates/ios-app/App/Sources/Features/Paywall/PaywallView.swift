import SwiftUI

/// One-time (non-consumable) Pro unlock. Complies with App Review 3.1.1/3.1.2:
/// localized StoreKit price, clear terms, Restore Purchases, easy dismissal.
struct PaywallView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(PurchaseManager.self) private var purchases

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: DesignTokens.Metrics.spacing * 3) {
                    Text("Unlock Pro")
                        .font(DesignTokens.Typography.title)
                        .foregroundStyle(DesignTokens.Palette.textPrimary)
                        .accessibilityIdentifier("paywall.title")
                    Text("Pay once. Keep it forever.")
                        .font(DesignTokens.Typography.body)
                        .foregroundStyle(DesignTokens.Palette.textSecondary)

                    VStack(alignment: .leading, spacing: DesignTokens.Metrics.spacing * 2) {
                        benefit("infinity", "Unlimited notes")
                        benefit("pin", "Pin what matters")
                        benefit("heart", "Support an independent developer")
                    }
                    .card()

                    purchaseSection
                }
                .padding(DesignTokens.Metrics.spacing * 3)
            }
            .background(DesignTokens.Palette.background)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button { dismiss() } label: { Label("Close", systemImage: "xmark") }
                        .accessibilityIdentifier("paywall.close")
                }
            }
            .onChange(of: purchases.isPro) { _, isPro in
                if isPro { dismiss() }
            }
        }
    }

    @ViewBuilder
    private var purchaseSection: some View {
        VStack(spacing: DesignTokens.Metrics.spacing * 2) {
            if let product = purchases.proProduct {
                Button {
                    Task { await purchases.purchase(productID: product.id) }
                } label: {
                    Text("Unlock Pro for \(product.displayPrice)")
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(purchases.phase == .purchasing)
                .accessibilityIdentifier("paywall.buyButton")

                Text("One-time purchase. No subscription.")
                    .font(DesignTokens.Typography.caption)
                    .foregroundStyle(DesignTokens.Palette.textSecondary)
                    .accessibilityIdentifier("paywall.terms")
            } else {
                ProgressView()
                    .accessibilityIdentifier("paywall.loading")
            }

            switch purchases.phase {
            case .pending:
                Text("Your purchase is pending approval.")
                    .font(DesignTokens.Typography.caption)
                    .accessibilityIdentifier("paywall.pending")
            case .failed(let message):
                Text(verbatim: message)
                    .font(DesignTokens.Typography.caption)
                    .foregroundStyle(.red)
                    .accessibilityIdentifier("paywall.error")
            default:
                EmptyView()
            }

            Button("Restore Purchases") {
                Task { await purchases.restore() }
            }
            .accessibilityIdentifier("paywall.restoreButton")

            HStack(spacing: DesignTokens.Metrics.spacing * 2) {
                Link("Terms of Use", destination: AppLinks.termsOfUse)
                Link("Privacy Policy", destination: AppLinks.privacyPolicy)
            }
            .font(DesignTokens.Typography.caption)
        }
    }

    private func benefit(_ symbol: String, _ title: LocalizedStringKey) -> some View {
        Label {
            Text(title)
                .font(DesignTokens.Typography.body)
                .foregroundStyle(DesignTokens.Palette.textPrimary)
        } icon: {
            Image(systemName: symbol)
                .foregroundStyle(DesignTokens.Palette.accent)
        }
    }
}
