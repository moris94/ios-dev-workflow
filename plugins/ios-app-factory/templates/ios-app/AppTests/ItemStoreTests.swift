import SwiftData
import XCTest
@testable import __PROJECT_NAME__

@MainActor
final class ItemStoreTests: XCTestCase {
    private func makeContext() -> ModelContext {
        ModelContext(ModelContainerFactory.make(inMemory: true))
    }

    func testInsertAndFetchSortedNewestFirst() throws {
        let context = makeContext()
        context.insert(Item(title: "Old", createdAt: .now.addingTimeInterval(-60)))
        context.insert(Item(title: "New"))
        try context.save()
        let items = try context.fetch(FetchDescriptor<Item>(sortBy: [SortDescriptor(\.createdAt, order: .reverse)]))
        XCTAssertEqual(items.map(\.title), ["New", "Old"])
    }

    func testDelete() throws {
        let context = makeContext()
        let item = Item(title: "Temp")
        context.insert(item)
        try context.save()
        context.delete(item)
        try context.save()
        XCTAssertEqual(try context.fetchCount(FetchDescriptor<Item>()), 0)
    }

    func testDemoDataIsLocalized() throws {
        let ja = makeContext()
        DemoData.seed(into: ja, locale: Locale(identifier: "ja_JP"))
        let titles = try ja.fetch(FetchDescriptor<Item>()).map(\.title)
        XCTAssertTrue(titles.contains { $0.unicodeScalars.contains { (0x3040...0x30FF).contains($0.value) || (0x4E00...0x9FFF).contains($0.value) } })

        let en = makeContext()
        DemoData.seed(into: en, locale: Locale(identifier: "en_US"))
        XCTAssertFalse(try en.fetch(FetchDescriptor<Item>()).isEmpty)
    }
}
