"""Representative use cases: storyboards and human UI/UX pre-approval."""
import pytest
from PIL import Image

from appfactory import approval, guards, ux
from appfactory.engine import Engine
from appfactory.gates import run_gate
from appfactory.jsonio import read_json, write_json_atomic
from conftest import copy_artifacts, human_approves_ux, pass_planning, pass_stage, run, run_json, set_profile


@pytest.fixture
def designed(project):
    pass_planning(project, until="design")
    copy_artifacts(project, "ux")
    return project


def _failed(project, stage="ux_review"):
    eng = Engine(project)
    rep = run_gate(project, eng.pipeline.get(stage), eng.load_state())
    return {c["id"] for c in rep["checks"] if not c["passed"] and c["severity"] == "error"}


def test_render_storyboards(designed, capsys):
    rc, out = run_json(designed.root, capsys, "ux", "render")
    assert sorted(out) == [f"factory/artifacts/ux/storyboards/UC{i}.png" for i in (1, 2, 3)]
    with Image.open(designed.root / "factory/artifacts/ux/storyboards/UC3.png") as im:
        assert im.mode == "RGB" and im.width > im.height
    rc, again = run_json(designed.root, capsys, "ux", "render")
    assert set(again.values()) == {"unchanged"}  # deterministic


def test_gate_requires_human_approval(designed):
    ux.render(designed)
    assert _failed(designed) == {"approval.human"}
    human_approves_ux(designed)
    pass_stage(designed, "ux_review")


def test_implementation_blocked_until_ux_approved(designed):
    ux.render(designed)
    nxt = Engine(designed).next_stage()
    assert nxt["id"] == "ux_review" and nxt["human_approval"] == "ux"
    impl = Engine(designed).pipeline.get("implementation")
    assert "ux_review" in impl.depends_on


def test_change_after_approval_invalidates_it(designed):
    ux.render(designed)
    human_approves_ux(designed)
    pass_stage(designed, "ux_review")
    p = designed.root / ux.UX_JSON
    d = read_json(p)
    d["use_cases"][2]["steps"][1]["copy"]["ja"] = "今だけ半額！"   # changed paywall copy
    write_json_atomic(p, d)
    ux.render(designed)
    assert Engine(designed).refresh()[0]["stage"] == "ux_review"
    assert "approval.human" in _failed(designed)


def test_structure_checks(designed):
    set_profile(designed, "strict")
    p = designed.root / ux.UX_JSON
    d = read_json(p)
    d["use_cases"] = [u for u in d["use_cases"] if u["kind"] != "monetization"]   # drop purchase flow
    d["use_cases"].append({**d["use_cases"][0], "id": "UC9", "kind": "recovery"})
    d["use_cases"][0]["steps"][0]["screen"] = "nowhere"
    d["use_cases"][0]["steps"][0]["wireframe"].pop("tap")
    write_json_atomic(p, d)
    ux.render(designed)
    assert {"coverage.monetization", "coverage.must-features", "trace.screens", "steps.tap-targets"} <= _failed(designed)


def test_stale_storyboards_detected(designed):
    ux.render(designed)
    human_approves_ux(designed)
    p = designed.root / ux.UX_JSON
    d = read_json(p)
    d["use_cases"][0]["title"]["en-US"] = "Capture a first thought"
    write_json_atomic(p, d)
    assert "storyboards.current" in _failed(designed)


def test_approve_ux_is_human_only(designed, monkeypatch):
    ux.render(designed)
    payload = {"tool_name": "Bash", "tool_input": {"command": "app-factory approve ux"}, "cwd": str(designed.root)}
    assert guards.guard_bash(payload) == 2
    with pytest.raises(approval.ApprovalError, match="interactive terminal"):
        approval.create(designed, "ux", ux.approval_subject(designed), ask=lambda _: "x", interactive_check=lambda: False)
    write = {"tool_name": "Write", "tool_input": {"file_path": str(designed.root / ux.BOARD_DIR / "UC1.png")},
             "cwd": str(designed.root)}
    assert guards.guard_files(write) == 2   # storyboards are generated, not hand-edited


def test_ux_status(designed, capsys):
    ux.render(designed)
    rc, st = run_json(designed.root, capsys, "ux", "status")
    assert st["approved"] is False and len(st["storyboards"]) == 3
    human_approves_ux(designed)
    rc, st = run_json(designed.root, capsys, "ux", "status")
    assert st["approved"] is True


def test_testing_gate_requires_use_case_coverage(project):
    from appfactory import codegen
    from appfactory.scaffold import scaffold
    from helpers_sim import fake_build

    scaffold(project)
    pass_planning(project)
    codegen.generate(project)
    fake_build(project)
    pass_stage(project, "implementation")
    pass_stage(project, "localization")
    set_profile(project, "strict")
    assert "uitests.use-cases" not in _failed(project, "testing")       # template marks UC1-UC3
    f = project.root / "AppUITests/AppUITests.swift"
    f.write_text(f.read_text().replace("// UC3", "//"))
    assert "uitests.use-cases" in _failed(project, "testing")
