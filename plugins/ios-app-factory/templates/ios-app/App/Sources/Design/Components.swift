import SwiftUI

/// Shared building blocks; every colour/font/metric comes from the generated DesignTokens.
struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(DesignTokens.Typography.headline)
            .foregroundStyle(DesignTokens.Palette.accentText)
            .frame(maxWidth: .infinity, minHeight: 50)
            .background(DesignTokens.Palette.accent.opacity(isEnabled ? 1 : 0.4),
                        in: RoundedRectangle(cornerRadius: DesignTokens.Metrics.cornerRadius, style: .continuous))
            .opacity(configuration.isPressed ? 0.85 : 1)
    }
}

struct CardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(DesignTokens.Metrics.spacing * 2)
            .background(DesignTokens.Palette.surface,
                        in: RoundedRectangle(cornerRadius: DesignTokens.Metrics.cornerRadius, style: .continuous))
    }
}

extension View {
    func card() -> some View { modifier(CardModifier()) }
}
