from appfactory import codegen
from appfactory.engine import Engine
from appfactory.gates import run_gate
from appfactory.hashing import source_digest
from appfactory.jsonio import read_json
from appfactory.reports import write_build_report
from appfactory.scaffold import scaffold
from conftest import copy_artifacts, pass_stage, run


def _prepare(project):
    copy_artifacts(project, "research", "proposal", "charter", "mvp", "design")
    for st in ("research", "proposal", "charter", "mvp", "design"):
        pass_stage(project, st)
    scaffold(project)
    codegen.generate(project)


def _gate(project, stage):
    eng = Engine(project)
    return run_gate(project, eng.pipeline.get(stage), eng.load_state())


def test_scaffold_renders_placeholders(project):
    written = scaffold(project)
    assert "project.yml" in written and "AppUITests/ScreenshotTests.swift" in written
    yml = (project.root / "project.yml").read_text()
    assert "__" not in yml and "com.example.stillnote" in yml and "developmentLanguage: en" in yml
    assert "@testable import Stillnote" in (project.root / "AppTests/PurchaseManagerTests.swift").read_text()


def test_codegen_outputs(project):
    _prepare(project)
    tokens = (project.root / codegen.DESIGN_TOKENS).read_text()
    assert "static let accent = dynamic(RGB(0.1255, 0.4157, 0.3255)" in tokens
    catalog = (project.root / codegen.PRODUCT_CATALOG).read_text()
    assert '"com.example.stillnote.pro"' in catalog and 'proFeatureIDs: Set<String> = ["F3"]' in catalog
    assert "fixtures.example.org/stillnote/privacy" in (project.root / codegen.APP_LINKS).read_text()
    sk = read_json(project.root / codegen.STOREKIT_CONFIG)
    assert sk["products"][0]["type"] == "NonConsumable" and sk["products"][0]["displayPrice"] == "4.99"
    assert codegen.generate(project)[codegen.DESIGN_TOKENS] == "unchanged"  # idempotent


def test_implementation_gate_requires_fresh_successful_build(project):
    _prepare(project)
    write_build_report(project, "success", "Stillnote", "Debug", "generic/platform=iOS Simulator", "2026-11-01T00:00:00Z")
    report = _gate(project, "implementation")
    failed = [c["id"] for c in report["checks"] if not c["passed"] and c["severity"] == "error"]
    assert failed == [], failed
    # Source changes after the build make the build report stale.
    (project.root / "App/Sources/Features/Home/HomeView.swift").write_text(
        (project.root / "App/Sources/Features/Home/HomeView.swift").read_text() + "\n// TODO: later\n")
    report = _gate(project, "implementation")
    failed = {c["id"] for c in report["checks"] if not c["passed"]}
    assert {"build.fresh", "code.no-placeholders"} <= failed


def test_generated_file_drift_detected(project):
    _prepare(project)
    p = project.root / codegen.PRODUCT_CATALOG
    p.write_text(p.read_text().replace("F3", "F9"))
    failed = {c["id"] for c in _gate(project, "implementation")["checks"] if not c["passed"]}
    assert f"codegen:{codegen.PRODUCT_CATALOG}" in failed


def test_localization_gate_on_template(project):
    _prepare(project)
    write_build_report(project, "success", "Stillnote", "Debug", "sim", "2026-11-01T00:00:00Z")
    pass_stage(project, "implementation")
    pass_stage(project, "localization")


def test_test_report_parsing(project, tmp_path):
    from appfactory.reports import write_test_report
    import json

    def node(name, result):
        return {"nodeType": "Test Case", "name": name, "result": result}

    tree = {"testNodes": [{"nodeType": "Test Plan", "name": "Stillnote", "children": [
        {"nodeType": "Unit test bundle", "name": "AppTests", "children": [{"nodeType": "Test Suite", "name": "S", "children": [
            node("testPurchaseSuccessUnlocksPro()", "Passed"), node("testA()", "Passed"), node("testB()", "Passed"),
            node("testC()", "Passed"), node("testD()", "Passed")]}]},
        {"nodeType": "UI test bundle", "name": "AppUITests", "children": [{"nodeType": "Test Suite", "name": "U", "children": [
            node("testPaywallShowsPriceAndRestore()", "Passed"), node("testEmptyState()", "Failed")]}]}]}]}
    f = tmp_path / "t.json"
    f.write_text(json.dumps(tree))
    rep = write_test_report(project, {"en-US": f, "ja": f})
    assert rep["status"] == "failed" and rep["suites"]["unit"]["passed"] == 10 and rep["suites"]["ui"]["failed"] == 2
    assert rep["source_digest"] == source_digest(project.root)
