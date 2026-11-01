import SwiftData
import SwiftUI

struct EditorView: View {
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @Environment(PurchaseManager.self) private var purchases

    let item: Item?
    @State private var title = ""
    @State private var note = ""
    @State private var isPinned = false
    @FocusState private var titleFocused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Title", text: $title)
                        .focused($titleFocused)
                        .accessibilityIdentifier("editor.title")
                    TextField("Note", text: $note, axis: .vertical)
                        .lineLimit(3...8)
                        .accessibilityIdentifier("editor.note")
                }
                Section {
                    Toggle("Pin to top", isOn: $isPinned)
                        .accessibilityIdentifier("editor.pin")
                }
            }
            .scrollContentBackground(.hidden)
            .background(DesignTokens.Palette.background)
            .navigationTitle(item == nil ? "New Note" : "Edit Note")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .accessibilityIdentifier("editor.cancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save", action: save)
                        .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        .accessibilityIdentifier("editor.save")
                }
            }
            .onAppear {
                if let item {
                    title = item.title
                    note = item.note
                    isPinned = item.isPinned
                } else {
                    titleFocused = true
                }
            }
        }
    }

    private func save() {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if let item {
            item.title = trimmed
            item.note = note
            item.isPinned = isPinned
        } else {
            context.insert(Item(title: trimmed, note: note, isPinned: isPinned))
        }
        try? context.save()
        dismiss()
    }
}
