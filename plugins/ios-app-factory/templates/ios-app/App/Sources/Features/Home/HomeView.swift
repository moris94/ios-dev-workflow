import SwiftData
import SwiftUI

struct HomeView: View {
    @Environment(\.modelContext) private var context
    @Environment(PurchaseManager.self) private var purchases
    @Query(sort: [SortDescriptor(\Item.isPinned, order: .reverse), SortDescriptor(\Item.createdAt, order: .reverse)])
    private var items: [Item]

    @State private var editing: Item?
    @State private var isCreating = false
    @State private var isShowingPaywall = false
    @State private var isShowingSettings = false

    var body: some View {
        Group {
            if items.isEmpty {
                ContentUnavailableView {
                    Label("No notes yet", systemImage: "square.and.pencil")
                } description: {
                    Text("Tap + to capture your first note.")
                }
                .accessibilityIdentifier("home.emptyState")
            } else {
                List {
                    ForEach(items) { item in
                        Button { editing = item } label: { ItemRow(item: item) }
                            .accessibilityIdentifier("home.row")
                    }
                    .onDelete(perform: delete)
                    if !purchases.isPro {
                        Text("\(items.count) of \(FeatureAccess.freeItemLimit) free notes used")
                            .font(DesignTokens.Typography.caption)
                            .foregroundStyle(DesignTokens.Palette.textSecondary)
                            .accessibilityIdentifier("home.freeUsage")
                    }
                }
                .scrollContentBackground(.hidden)
            }
        }
        .background(DesignTokens.Palette.background)
        .navigationTitle("Notes")
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button { isShowingSettings = true } label: {
                    Label("Settings", systemImage: "gearshape")
                }
                .accessibilityIdentifier("home.settingsButton")
            }
            ToolbarItem(placement: .primaryAction) {
                Button(action: add) {
                    Label("Add Note", systemImage: "plus")
                }
                .accessibilityIdentifier("home.addButton")
            }
        }
        .sheet(isPresented: $isCreating) { EditorView(item: nil) }
        .sheet(item: $editing) { item in EditorView(item: item) }
        .sheet(isPresented: $isShowingPaywall) { PaywallView() }
        .sheet(isPresented: $isShowingSettings) { NavigationStack { SettingsView() } }
    }

    private func add() {
        if purchases.access.canCreateItem(currentCount: items.count) {
            isCreating = true
        } else {
            isShowingPaywall = true
        }
    }

    private func delete(at offsets: IndexSet) {
        for index in offsets { context.delete(items[index]) }
        try? context.save()
    }
}

private struct ItemRow: View {
    let item: Item

    var body: some View {
        VStack(alignment: .leading, spacing: DesignTokens.Metrics.spacing / 2) {
            HStack {
                if item.isPinned {
                    Image(systemName: "pin.fill")
                        .foregroundStyle(DesignTokens.Palette.accent)
                        .accessibilityLabel("Pinned")
                }
                Text(verbatim: item.title)
                    .font(DesignTokens.Typography.headline)
                    .foregroundStyle(DesignTokens.Palette.textPrimary)
            }
            if !item.note.isEmpty {
                Text(verbatim: item.note)
                    .font(DesignTokens.Typography.body)
                    .foregroundStyle(DesignTokens.Palette.textSecondary)
                    .lineLimit(2)
            }
            Text(item.createdAt, format: .relative(presentation: .named))
                .font(DesignTokens.Typography.caption)
                .foregroundStyle(DesignTokens.Palette.textSecondary)
        }
        .padding(.vertical, DesignTokens.Metrics.spacing / 2)
    }
}
