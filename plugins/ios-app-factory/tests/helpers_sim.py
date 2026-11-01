"""Stand-ins for the macOS-only steps (xcodebuild / simulator), used by tests only.

They write exactly what scripts/xcode/*.sh would produce on a Mac — clearly marked
as simulated — so the gate logic downstream can be exercised on any OS."""
import json
from pathlib import Path

from PIL import Image, ImageDraw

from appfactory.jsonio import read_json
from appfactory.reports import write_build_report, write_test_report


def fake_build(project):
    return write_build_report(project, "success", "Stillnote", "Debug", "generic/platform=iOS Simulator",
                              "2026-11-01T00:00:00Z", xcode_version="SIMULATED")


def fake_tests(project, tmp_path: Path):
    def node(name, result="Passed"):
        return {"nodeType": "Test Case", "name": name, "result": result}

    unit = ["testPurchaseSuccessUnlocksPro()", "testPurchaseCancelledKeepsFreeTier()", "testRestoreReflectsExistingEntitlement()",
            "testFreeTierHasLimit()", "testProIsUnlimited()", "testInsertAndFetchSortedNewestFirst()"]
    ui = ["testEmptyStateThenAddNote()", "testPaywallShowsPriceAndRestore()", "testPurchaseUnlocksPro()"]
    tree = {"testNodes": [{"nodeType": "Test Plan", "name": "Stillnote", "children": [
        {"nodeType": "Unit test bundle", "name": "AppTests", "children": [node(n) for n in unit]},
        {"nodeType": "UI test bundle", "name": "AppUITests", "children": [node(n) for n in ui]}]}]}
    f = tmp_path / "xcresult-tests.json"
    f.write_text(json.dumps(tree))
    return write_test_report(project, {"en-US": f, "ja": f}, destination="SIMULATED")


def fake_raw_captures(project, size=(1320, 2868)):
    mvp = read_json(project.artifact("mvp", "mvp.json"))
    cfg = project.config()
    for locale in cfg["app"]["locales"]:
        for device in cfg["screenshots"]["devices"]:
            for i, scene in enumerate(s["id"] for s in mvp["screenshot_scenes"]):
                img = Image.new("RGB", size, (247, 248, 245))
                d = ImageDraw.Draw(img)
                d.rectangle((0, 0, size[0], 300), fill=(32, 106, 83))
                for row in range(6):
                    y = 380 + row * 260 + i * 10
                    d.rounded_rectangle((60, y, size[0] - 60, y + 200), radius=28, fill=(255, 255, 255))
                p = project.screenshots_dir / "raw" / locale / device / f"{scene}.png"
                p.parent.mkdir(parents=True, exist_ok=True)
                img.save(p)
