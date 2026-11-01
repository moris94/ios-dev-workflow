import json

import pytest

from appfactory import locking
from appfactory.engine import Engine, EngineError
from appfactory.jsonio import read_json, write_json_atomic
from conftest import copy_artifacts, pass_stage


def test_duplicate_start_is_refused_and_reentrant_for_owner(project):
    eng = Engine(project)
    first = eng.start("research", "session-A")
    assert first["action"] == "started"
    again = eng.start("research", "session-A")
    assert again["action"] == "resumed" and again["run_id"] == first["run_id"]
    with pytest.raises(locking.LockHeld):
        eng.start("research", "session-B")
    assert eng.load_state()["stages"]["research"]["attempts"] == 1


def test_cannot_start_before_dependencies(project):
    with pytest.raises(EngineError):
        Engine(project).start("proposal", "s")


def test_interrupted_session_detected_and_taken_over(project):
    eng = Engine(project)
    eng.start("research", "dead-session")
    lock = project.locks_dir / "research.lock"
    info = json.loads(lock.read_text())
    info["heartbeat_at"] = "2000-01-01T00:00:00Z"
    lock.write_text(json.dumps(info))
    eng.refresh()
    assert eng.load_state()["stages"]["research"]["status"] == "interrupted"
    nxt = eng.next_stage()
    assert nxt["id"] == "research" and nxt["action"] == "resume"
    res = eng.start("research", "new-session")
    assert res["action"] == "started"
    assert locking.read_lock(project.locks_dir, "research")["owner"] == "new-session"


def test_explicit_takeover_of_live_lock(project):
    eng = Engine(project)
    eng.start("research", "A")
    res = eng.start("research", "B", takeover=True)
    assert res["action"] == "started"


def test_pass_skip_and_history(project):
    copy_artifacts(project, "research")
    pass_stage(project, "research")
    eng = Engine(project)
    assert eng.start("research", "other")["action"] == "skip"
    assert eng.start("research", "other", force=True)["action"] == "started"
    events = [json.loads(l)["event"] for l in project.history_path.read_text().splitlines()]
    assert "gate_passed" in events and "stage_started" in events


def test_failed_gate_records_reason_and_releases_lock(project):
    eng = Engine(project)
    eng.start("research", "s")
    from appfactory.gates import run_gate

    report = run_gate(project, eng.pipeline.get("research"), eng.load_state())
    out = eng.record_gate("research", "s", report)
    assert out["status"] == "failed" and "exists:" in out["reason"]
    assert locking.read_lock(project.locks_dir, "research") is None
    saved = read_json(project.gates_dir / "research.json")
    assert saved["passed"] is False and saved["checks"]


def test_spec_change_cascades_staleness(project):
    copy_artifacts(project, "research", "proposal", "charter")
    for st in ("research", "proposal", "charter"):
        pass_stage(project, st)
    eng = Engine(project)
    # Edit the proposal by hand (spec change) -> proposal and charter become stale, research untouched.
    p = project.artifact("proposal", "proposal.json")
    data = read_json(p)
    data["one_liner"] = "A changed positioning statement"
    write_json_atomic(p, data)
    changes = eng.refresh()
    assert {c["stage"] for c in changes} == {"proposal", "charter"}
    st = eng.load_state()["stages"]
    assert st["research"]["status"] == "passed"
    assert st["proposal"]["status"] == "stale" and st["charter"]["status"] == "stale"
    assert eng.next_stage()["action"] == "revalidate"
    # Re-validate in order: proposal passes again, which changes its output digest -> charter re-gated too.
    pass_stage(project, "proposal")
    pass_stage(project, "charter")
    assert all(eng.load_state()["stages"][s]["status"] == "passed" for s in ("research", "proposal", "charter"))


def test_invalidate_marks_downstream(project):
    copy_artifacts(project, "research", "proposal")
    pass_stage(project, "research")
    pass_stage(project, "proposal")
    stale = Engine(project).invalidate("research", "new competitor launched")
    assert stale == ["research", "proposal"]


def test_state_writes_are_atomic(project):
    eng = Engine(project)
    state = eng.load_state()
    eng.save_state(state)
    assert not list(project.factory.glob(".state.json.*.tmp"))
    assert read_json(project.state_path)["schema_version"] == 1
