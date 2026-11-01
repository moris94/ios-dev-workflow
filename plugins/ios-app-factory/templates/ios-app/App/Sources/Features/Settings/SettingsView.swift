import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(PurchaseManager.self) private var purchases
    @State private var isShowingPaywall = false

    var body: some View {
        List {
            Section("Pro") {
                if purchases.isPro {
                    Label("Pro unlocked", systemImage: "checkmark.seal.fill")
                        .foregroundStyle(DesignTokens.Palette.accent)
                        .accessibilityIdentifier("settings.proStatus")
                } else {
                    Button("Unlock Pro") { isShowingPaywall = true }
                        .accessibilityIdentifier("settings.unlockPro")
                }
                Button("Restore Purchases") {
                    Task { await purchases.restore() }
                }
                .accessibilityIdentifier("settings.restoreButton")
            }
            Section("About") {
                Link("Support", destination: AppLinks.support)
                Link("Privacy Policy", destination: AppLinks.privacyPolicy)
                Link("Terms of Use", destination: AppLinks.termsOfUse)
                LabeledContent("Version", value: Self.version)
            }
        }
        .scrollContentBackground(.hidden)
        .background(DesignTokens.Palette.background)
        .navigationTitle("Settings")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Done") { dismiss() }
                    .accessibilityIdentifier("settings.done")
            }
        }
        .sheet(isPresented: $isShowingPaywall) { PaywallView() }
    }

    private static var version: String {
        let info = Bundle.main.infoDictionary
        let short = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "\(short) (\(build))"
    }
}
