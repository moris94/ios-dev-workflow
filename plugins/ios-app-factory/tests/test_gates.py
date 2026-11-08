import json

import pytest

from appfactory.engine import Engine
from appfactory.gates import run_gate
from appfactory.jsonio import read_json, write_json_atomic
from conftest import copy_artifacts, pass_planning, pass_stage


def _gate(project, stage):
    eng = Engine(project)
    return run_gate(project, eng.pipeline.get(stage), eng.load_state())


def _failed_ids(report):
    return {c["id"] for c in report["checks"] if not c["passed"] and c["severity"] == "error"}


@pytest.fixture
def planned(project):
    pass_planning(project, until="support_page")
    copy_artifacts(project, "aso")
    return project


def test_sample_planning_artifacts_pass(planned):
    assert Engine(planned).load_state()["stages"]["design"]["status"] == "passed"


def test_research_dangling_citation_fails(project):
    copy_artifacts(project, "research")
    p = project.artifact("research", "research.json")
    d = read_json(p)
    d["competitors"][0]["source_ids"] = ["S99"]
    write_json_atomic(p, d)
    assert "citations.resolve" in _failed_ids(_gate(project, "research"))


def test_research_no_go_stops(project):
    copy_artifacts(project, "research")
    p = project.artifact("research", "research.json")
    d = read_json(p)
    d["verdict"]["go"] = False
    write_json_atomic(p, d)
    assert "verdict.go" in _failed_ids(_gate(project, "research"))


def test_mvp_requires_monetization_or_human_waiver(planned):
    p = planned.artifact("mvp", "mvp.json")
    d = read_json(p)
    d["monetization"]["model"] = "none"
    d["monetization"]["products"] = []
    for f in d["features"]:
        f.pop("requires_pro", None)
    write_json_atomic(p, d)
    assert "monetization.required" in _failed_ids(_gate(planned, "mvp"))


def test_mvp_subscription_needs_justification_and_prefix(planned):
    p = planned.artifact("mvp", "mvp.json")
    d = read_json(p)
    d["monetization"]["model"] = "subscription"
    d["monetization"]["products"][0]["product_id"] = "com.other.pro"
    write_json_atomic(p, d)
    failed = _failed_ids(_gate(planned, "mvp"))
    assert "monetization.prefer-non-consumable" in failed
    assert "product.com.other.pro.prefix" in failed


def test_design_contrast_and_cliche_detected(planned):
    p = planned.artifact("design", "design.json")
    d = read_json(p)
    d["color"]["light"]["accent"] = "#6366F1"           # Tailwind indigo-500
    d["color"]["light"]["text_secondary"] = "#BBBBBB"   # too light on paper background
    write_json_atomic(p, d)
    failed = _failed_ids(_gate(planned, "design"))
    assert "anti-generic.accent" in failed
    assert "contrast.light.text_secondary/background" in failed


def test_aso_limits_and_links(planned):
    p = planned.artifact("aso", "aso.json")
    d = read_json(p)
    d["locales"]["en-US"]["keywords"] = "memo, jot,memo"
    d["locales"]["ja"]["screenshot_captions"]["home"]["headline"] = "とても長すぎるキャプションの見出しテキストです"
    d["locales"]["ja"]["support_url"] = "https://elsewhere.example.org/support"
    write_json_atomic(p, d)
    failed = _failed_ids(_gate(planned, "aso"))
    assert {"en-US.keywords.format", "en-US.keywords.unique", "ja.captions.length", "ja.links.match-app"} <= failed


def test_aso_passes_for_sample(planned):
    pass_stage(planned, "aso")


def test_gate_report_is_saved_with_digests(planned):
    rep = read_json(planned.gates_dir / "mvp.json")
    assert rep["passed"] and len(rep["output_digest"]) == 64 and "factory/artifacts/mvp/mvp.json" in rep["output_files"]
