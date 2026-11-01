"""Implementation & testing gates (consume reports produced by scripts/xcode/*.sh)."""
from __future__ import annotations

import re

from .. import codegen
from ..hashing import expand_globs, source_digest
from ..schemas_util import validate
from . import gate
from .planning import MVP

REQUIRED_FILES = [
    "project.yml",
    "App/Sources/App/AppMain.swift",
    "App/Sources/Store/PurchaseManager.swift",
    "App/Sources/Store/ProductCatalog.swift",
    "App/Sources/Design/DesignTokens.swift",
    "App/Resources/Products.storekit",
    "App/Resources/PrivacyInfo.xcprivacy",
    "fastlane/Fastfile",
]
PLACEHOLDER_RE = re.compile(r"\b(TODO|FIXME|XXX)\b|__APP_[A-Z_]+__|fatalError\(\"(unimplemented|TODO)")


def _swift_sources(ctx, globs):
    return {p: p.read_text(encoding="utf-8", errors="replace") for p in expand_globs(ctx.project.root, globs)}


def _camel_upper(screen_id: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_-]", screen_id))


@gate("implementation")
def implementation_gate(ctx):
    root = ctx.project.root
    missing = [f for f in REQUIRED_FILES if not (root / f).exists()]
    ctx.check("files.required", not missing, "required project files present", details=missing or None)

    for rel, expected in codegen.expected_files(ctx.project).items():
        p = root / rel
        ok = p.exists() and p.read_text(encoding="utf-8") == expected
        ctx.check(f"codegen:{rel}", ok, "generated file up to date (run `app-factory codegen`)")

    app_src = _swift_sources(ctx, ["App/Sources/**/*.swift"])
    all_src = "\n".join(app_src.values())
    placeholders = sorted({ctx.project.rel(p) for p, s in app_src.items() if PLACEHOLDER_RE.search(s)})
    ctx.check("code.no-placeholders", not placeholders, "no TODO/FIXME/template placeholders in app sources",
              details=placeholders or None)
    ctx.check("swiftdata.model", "@Model" in all_src, "SwiftData @Model present")
    ctx.check("swiftdata.container", ".modelContainer(" in all_src or "ModelContainer(" in all_src, "SwiftData container configured")
    for needle, label in [("Transaction.updates", "listens to Transaction.updates"),
                          ("Transaction.currentEntitlements", "derives entitlements from Transaction.currentEntitlements"),
                          ("AppStore.sync", "restore purchases via AppStore.sync"),
                          (".finish()", "finishes transactions")]:
        ctx.check(f"storekit2.{needle}", needle in all_src, label)
    icon = root / codegen.APP_ICON
    if icon.exists():
        from ..screenshots.compose import png_info

        info = png_info(icon)
        ctx.check("icon.format", (info["width"], info["height"]) == (1024, 1024) and not info["has_alpha"],
                  "App icon 1024x1024 without alpha")
    else:
        ctx.check("icon.format", False, f"missing {codegen.APP_ICON} (run `app-factory codegen` or add a designed icon)")
    ctx.check("swiftui.no-uikit-lifecycle", "UIApplicationMain" not in all_src and "@main" in all_src, "SwiftUI App lifecycle")

    mvp = ctx.load_json(MVP)
    if mvp:
        missing_views = [s["id"] for s in mvp["screens"] if f"struct {_camel_upper(s['id'])}View" not in all_src]
        ctx.check("trace.screens", not missing_views, "every MVP screen has a `<Screen>View` SwiftUI view",
                  details=missing_views or None)

    yml = (root / "project.yml").read_text(encoding="utf-8") if (root / "project.yml").exists() else ""
    m = re.search(r"iOS:\s*\"?(\d+)(?:\.\d+)?", yml)
    ctx.check("project.deployment-target", bool(m) and int(m.group(1)) >= 17, "deployment target iOS 17+ (SwiftData)")

    app_cfg = ctx.config.get("app", {})
    mv = re.search(r'MARKETING_VERSION:\s*"?([0-9.]+)"?', yml)
    bn = re.search(r'CURRENT_PROJECT_VERSION:\s*"?([0-9]+)"?', yml)
    ctx.check("project.version-matches-config",
              bool(mv and bn) and mv.group(1) == app_cfg.get("version") and bn.group(1) == str(app_cfg.get("build_number")),
              f"project.yml MARKETING_VERSION/CURRENT_PROJECT_VERSION == config ({app_cfg.get('version')} / {app_cfg.get('build_number')})")

    unit = _swift_sources(ctx, ["AppTests/**/*.swift"])
    n_tests = sum(len(re.findall(r"func test\w+\(", s)) + len(re.findall(r"@Test\b", s)) for s in unit.values())
    ctx.check("tests.unit-present", n_tests >= 5, f"{n_tests} unit tests written (>= 5)")

    report = ctx.load_json("factory/reports/build.json")
    if report is not None:
        errors = validate(report, "build_report")
        ctx.check("build.report-schema", not errors, "build report valid", details=errors or None)
        ctx.check("build.success", report.get("status") == "success", f"xcodebuild status: {report.get('status')}")
        current = source_digest(root)
        ctx.check("build.fresh", report.get("source_digest") == current,
                  "build report matches current sources (re-run scripts/xcode/build.sh after changes)")


@gate("testing")
def testing_gate(ctx):
    root = ctx.project.root
    report = ctx.load_json("factory/reports/tests.json")
    ui = _swift_sources(ctx, ["AppUITests/**/*.swift"])
    ctx.check("uitests.present", bool(ui), "UI test sources present")
    shots = "\n".join(s for p, s in ui.items() if "Screenshot" in p.name)
    mvp = ctx.load_json(MVP)
    if mvp:
        missing = [s["id"] for s in mvp["screenshot_scenes"] if f"\"{s['id']}\"" not in shots]
        ctx.check("uitests.screenshot-scenes", not missing, "ScreenshotTests capture every MVP scene", details=missing or None)
    if report is None:
        return
    errors = validate(report, "test_report")
    ctx.check("tests.report-schema", not errors, "test report valid", details=errors[:20] or None)
    if errors:
        return
    ctx.check("tests.status", report["status"] == "passed" and report["totals"]["failed"] == 0,
              f"{report['totals']['passed']} passed / {report['totals']['failed']} failed")
    ctx.check("tests.unit", report["suites"]["unit"]["passed"] >= 5 and report["suites"]["unit"]["failed"] == 0,
              f"unit: {report['suites']['unit']}")
    ctx.check("tests.ui", report["suites"]["ui"]["passed"] >= 2 and report["suites"]["ui"]["failed"] == 0,
              f"ui: {report['suites']['ui']}")
    purchase = [t for t in report["tests"] if re.search(r"purchase|entitle|restore|paywall", t["name"], re.I)]
    ctx.check("tests.purchase-covered", any(t["result"] == "passed" for t in purchase) and
              all(t["result"] != "failed" for t in purchase), f"{len(purchase)} purchase/entitlement tests passed")
    locales = set(report["locales_tested"])
    ctx.check("tests.locales", {"en-US", "ja"} <= locales or {"en", "ja"} <= locales, f"tests ran in locales {sorted(locales)}")
    ctx.check("tests.fresh", report["source_digest"] == source_digest(root),
              "test report matches current sources (re-run scripts/xcode/test.sh)")
