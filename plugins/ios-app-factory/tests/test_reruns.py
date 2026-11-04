"""Partial re-runs of failed tests (environment / test-defect causes)."""
import json

import pytest

from appfactory import codegen
from appfactory.engine import Engine
from appfactory.gates import run_gate
from appfactory.reports import ReportError, rerun_plan, write_rerun_report, write_test_report
from appfactory.scaffold import scaffold
from conftest import pass_planning, pass_stage
from helpers_sim import fake_build

UNIT = ["testPurchaseSuccessUnlocksPro", "testPurchaseCancelledKeepsFreeTier", "testRestoreReflectsExistingEntitlement",
        "testFreeTierHasLimit", "testProIsUnlimited", "testInsertAndFetchSortedNewestFirst"]
UI = ["testEmptyStateThenAddNote", "testPaywallShowsPriceAndRestore", "testPurchaseUnlocksPro"]


def xcresult(tmp_path, name, unit=UNIT, ui=UI, failed=(), only=None):
    """xcresulttool `test-results tests` JSON. `only` restricts to {(suite, method)}."""
    def case(m):
        return {"nodeType": "Test Case", "name": m + "()", "result": "Failed" if m in failed else "Passed"}

    def bundle(kind, target, suite, methods):
        methods = [m for m in methods if only is None or (suite, m) in only]
        return {"nodeType": kind, "name": target,
                "children": [{"nodeType": "Test Suite", "name": suite, "children": [case(m) for m in methods]}]}

    tree = {"testNodes": [{"nodeType": "Test Plan", "name": "Stillnote", "children": [
        bundle("Unit test bundle", "AppTests", "PurchaseManagerTests", unit),
        bundle("UI test bundle", "AppUITests", "AppUITests", ui)]}]}
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(tree))
    return p


@pytest.fixture
def tested(project, tmp_path):
    scaffold(project)
    pass_planning(project)
    codegen.generate(project)
    fake_build(project)
    pass_stage(project, "implementation")
    pass_stage(project, "localization")
    en = xcresult(tmp_path, "en")
    ja = xcresult(tmp_path, "ja", failed={"testPaywallShowsPriceAndRestore"})
    rep = write_test_report(project, {"en-US": en, "ja": ja})
    assert rep["status"] == "failed"
    return project


def _gate(project):
    eng = Engine(project)
    rep = run_gate(project, eng.pipeline.get("testing"), eng.load_state())
    return rep, {c["id"] for c in rep["checks"] if not c["passed"] and c["severity"] == "error"}


def test_environment_rerun_of_failed_case_only(tested, tmp_path):
    _, failed = _gate(tested)
    assert "tests.status" in failed
    plan = rerun_plan(tested, "environment")
    assert plan == {"ja": ["AppUITests/AppUITests/testPaywallShowsPriceAndRestore"]}
    rerun = xcresult(tmp_path, "ja-rerun", only={("AppUITests", "testPaywallShowsPriceAndRestore")})
    rep = write_rerun_report(tested, {"ja": rerun}, "environment", "simulator boot timed out on first launch")
    assert rep["status"] == "passed" and rep["totals"]["failed"] == 0
    assert rep["totals"]["passed"] == 2 * (len(UNIT) + len(UI))      # merged, nothing lost
    assert rep["flaky"] == ["AppUITests/AppUITests/testPaywallShowsPriceAndRestore [ja]"]
    report, failed = _gate(tested)
    assert not failed, failed
    assert any(c["id"] == "tests.flaky" and not c["passed"] for c in report["checks"])  # warning only
    pass_stage(tested, "testing")


def test_app_code_change_requires_full_run(tested, tmp_path):
    home = tested.root / "App/Sources/Features/Home/HomeView.swift"
    home.write_text(home.read_text() + "\n// fix\n")
    with pytest.raises(ReportError, match="full suite"):
        rerun_plan(tested, "environment")
    with pytest.raises(ReportError, match="App/"):
        rerun_plan(tested, "test-defect")


def test_environment_reason_rejects_changed_tests(tested):
    f = tested.root / "AppUITests/AppUITests.swift"
    f.write_text(f.read_text() + "\n")
    with pytest.raises(ReportError, match="test-defect"):
        rerun_plan(tested, "environment")


def test_test_defect_reruns_whole_changed_class(tested, tmp_path):
    f = tested.root / "AppUITests/AppUITests.swift"
    f.write_text(f.read_text().replace('"paywall.terms"', '"paywall.termsText"'))  # fix the test, not the app
    plan = rerun_plan(tested, "test-defect")
    assert "AppUITests/AppUITests" in plan["en-US"] and "AppUITests/AppUITests" in plan["ja"]
    only_failed = {("AppUITests", "testPaywallShowsPriceAndRestore")}
    with pytest.raises(ReportError, match="changed test class"):
        write_rerun_report(tested, {"ja": xcresult(tmp_path, "partial", only=only_failed)}, "test-defect",
                           "wrong accessibility identifier in the UI test")
    whole = {("AppUITests", m) for m in UI}
    rep = write_rerun_report(tested, {"en-US": xcresult(tmp_path, "en-r", only=whole),
                                      "ja": xcresult(tmp_path, "ja-r", only=whole)},
                             "test-defect", "wrong accessibility identifier in the UI test")
    assert rep["status"] == "passed" and rep["flaky"] == []
    _, failed = _gate(tested)
    assert not failed, failed


def test_note_and_limits(tested, tmp_path):
    rerun = xcresult(tmp_path, "r", only={("AppUITests", "testPaywallShowsPriceAndRestore")},
                     failed={"testPaywallShowsPriceAndRestore"})
    with pytest.raises(ReportError, match="note"):
        write_rerun_report(tested, {"ja": rerun}, "environment", "flaky")
    write_rerun_report(tested, {"ja": rerun}, "environment", "simulator crashed again (1)")
    write_rerun_report(tested, {"ja": rerun}, "environment", "simulator crashed again (2)")
    with pytest.raises(ReportError, match="max 2"):
        rerun_plan(tested, "environment")


def test_missing_failed_case_in_rerun_is_rejected(tested, tmp_path):
    other = xcresult(tmp_path, "wrong", only={("AppUITests", "testEmptyStateThenAddNote")})
    with pytest.raises(ReportError, match="did not cover"):
        write_rerun_report(tested, {"ja": other}, "environment", "simulator boot timed out on first launch")


def test_gate_rejects_app_change_after_rerun(tested, tmp_path):
    rerun = xcresult(tmp_path, "ok", only={("AppUITests", "testPaywallShowsPriceAndRestore")})
    write_rerun_report(tested, {"ja": rerun}, "environment", "simulator boot timed out on first launch")
    home = tested.root / "App/Sources/Features/Home/HomeView.swift"
    home.write_text(home.read_text() + "\n// sneaky fix\n")
    _, failed = _gate(tested)
    assert {"tests.fresh", "tests.partial-reruns.app-unchanged"} <= failed


def test_cli_rerun_plan_for_script(tested, capsys):
    from conftest import run

    capsys.readouterr()
    assert run(tested.root, "report", "rerun-plan", "--reason", "environment", "--locale", "ja") == 0
    assert capsys.readouterr().out.strip() == "-only-testing:AppUITests/AppUITests/testPaywallShowsPriceAndRestore"
