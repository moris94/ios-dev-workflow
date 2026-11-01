import Foundation
import SwiftData

/// A captured note. Replace/extend with the entities from mvp.json `data_model`.
@Model
final class Item {
    var title: String
    var note: String
    var createdAt: Date
    var isPinned: Bool

    init(title: String, note: String = "", createdAt: Date = .now, isPinned: Bool = false) {
        self.title = title
        self.note = note
        self.createdAt = createdAt
        self.isPinned = isPinned
    }
}

enum ModelContainerFactory {
    static let schema = Schema([Item.self])

    static func make(inMemory: Bool) -> ModelContainer {
        let configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: inMemory)
        do {
            return try ModelContainer(for: schema, configurations: [configuration])
        } catch {
            fatalError("Could not create the SwiftData container: \(error)")
        }
    }
}

/// Locale-aware sample content used for screenshots (`-seedDemoData`).
enum DemoData {
    @MainActor
    static func seed(into context: ModelContext, locale: Locale) {
        let japanese = locale.language.languageCode == .japanese
        let samples: [(String, String)] = japanese
            ? [("週末の山歩きルート", "高尾山から陣馬山へ。朝7時集合"),
               ("新しいアプリのアイデア", "通知なしで続けられる習慣化"),
               ("読みたい本", "『デザインの骨格』『考える技術』"),
               ("母の誕生日プレゼント", "手書きのカードと花束")]
            : [("Weekend trail route", "Ridge loop, meet at 7am"),
               ("New app idea", "Habits without notifications"),
               ("Books to read", "The Design of Everyday Things"),
               ("Mom's birthday gift", "Handwritten card and tulips")]
        for (offset, sample) in samples.enumerated() {
            let created = Date.now.addingTimeInterval(TimeInterval(-3_600 * (offset * 7 + 1)))
            context.insert(Item(title: sample.0, note: sample.1, createdAt: created, isPinned: offset == 0))
        }
        try? context.save()
    }
}
