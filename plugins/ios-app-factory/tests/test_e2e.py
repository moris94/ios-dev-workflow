"""End-to-end rehearsal of the whole pipeline through the CLI.

macOS-only steps (xcodebuild, simulator capture) are replaced by helpers that write the same
reports the scripts would; App Store Connect is the built-in simulator (FACTORY_REHEARSAL=1).
Human-only steps (purchase test, approvals) are performed the way a human would: through the
approval API with an interactive terminal stand-in."""
import json

import pytest

from appfactory import approval
from appfactory.engine import Engine
from appfactory.jsonio import read_json, write_json_atomic
from appfactory.release import compute_readiness
from conftest import copy_artifacts, run, run_json
from helpers_sim import fake_build, fake_raw_captures, fake_tests

OWNER = "session-e2e"


def gate(project, capsys, stage):
    rc, out = run_json(project.root, capsys, "gate", stage, "--owner", OWNER)
    assert rc == 0, json.dumps(read_json(project.gates_dir / f"{stage}.json")["checks"], ensure_ascii=False)[:4000]
    return out


def start(project, capsys, stage):
    rc, out = run_json(project.root, capsys, "start", stage, "--owner", OWNER)
    assert rc == 0
    return out


def human_approve(project, kind):
    r = compute_readiness(project)
    assert r["ready"], r["checks"]
    phrase = approval.phrase_for(kind, "Stillnote", r["app_version"], r["build_number"])
    approval.create(project, kind, r, approver="release-owner", ask=lambda _: phrase, interactive_check=lambda: True)


def test_full_pipeline_rehearsal(project, capsys, tmp_path, monkeypatch):
    root = project.root
    assert run(root, "scaffold") == 0

    # Phase B: planning stages (agents' artifacts = sample fixtures)
    for stage in ("research", "proposal", "charter", "mvp", "design"):
        rc, nxt = run_json(root, capsys, "next")
        assert nxt["id"] == stage and nxt["action"] == "run"
        start(project, capsys, stage)
        copy_artifacts(project, stage)
        gate(project, capsys, stage)

    # Phase C: implementation, localization, testing
    start(project, capsys, "implementation")
    assert run(root, "codegen") == 0
    fake_build(project)
    gate(project, capsys, "implementation")
    start(project, capsys, "localization")
    gate(project, capsys, "localization")
    start(project, capsys, "testing")
    fake_tests(project, tmp_path)
    gate(project, capsys, "testing")

    # Phase D: ASO, screenshots, App Store Connect (dry-run first)
    start(project, capsys, "aso")
    copy_artifacts(project, "aso")
    gate(project, capsys, "aso")
    start(project, capsys, "screenshots")
    fake_raw_captures(project)
    assert run(root, "screenshots", "render") == 0
    gate(project, capsys, "screenshots")

    start(project, capsys, "asc_sync")
    rc, plan_report = run_json(root, capsys, "asc", "plan")
    assert rc == 0 and plan_report["mode"] == "dry-run" and plan_report["operations"] > 20
    gate(project, capsys, "asc_sync")  # passes in dry-run mode (with warning)
    # apply is refused while config says dry-run
    with pytest.raises(SystemExit):
        run(root, "asc", "apply")

    # Phase E: switch to apply (rehearsal against the simulator); only asc_sync becomes stale
    monkeypatch.setenv("FACTORY_REHEARSAL", "1")
    cfg = project.config()
    cfg["asc"]["mode"] = "apply"
    write_json_atomic(project.config_path, cfg)
    rc, changes = run_json(root, capsys, "check")
    assert [c["stage"] for c in changes["changes"]] == ["asc_sync"]
    start(project, capsys, "asc_sync")
    rc, applied = run_json(root, capsys, "asc", "apply", "--simulate")
    assert rc == 0 and applied["verify_noop"] is True and applied["stats"]["applied"] > 20
    rc, again = run_json(root, capsys, "asc", "apply", "--simulate")
    assert again["stats"]["applied"] == 0 and again["operations"] == 0  # idempotent: nothing re-sent
    gate(project, capsys, "asc_sync")

    start(project, capsys, "testflight")
    rc, tf = run_json(root, capsys, "testflight", "verify", "--simulate")
    assert tf["processing_state"] == "VALID"
    gate(project, capsys, "testflight")

    # Human: manual purchase test on the TestFlight build
    write_json_atomic(project.reports / "purchase-test.json", {
        "tester": "QA human", "tested_at": "2026-11-01T09:00:00Z", "build_number": "1", "environment": "testflight",
        "cases": [{"id": c, "result": "pass"} for c in ("purchase", "restore", "en_paywall", "ja_paywall")],
        "recorded_interactively": True})
    start(project, capsys, "release_readiness")
    rc, ready = run_json(root, capsys, "release", "readiness")
    assert rc == 0 and ready["ready"] is True
    gate(project, capsys, "release_readiness")

    # Submission is impossible without human approval (script layer) ...
    start(project, capsys, "submit")
    assert run(root, "release", "submit", "--simulate") == 1
    assert "HUMAN APPROVAL REQUIRED" in capsys.readouterr().err
    rc, dry = run_json(root, capsys, "release", "submit", "--dry-run")
    assert dry["dry_run"] is True and any("Submit for App Review" in o for o in dry["operations"])
    # ... and the gate fails too
    rc, _ = run_json(root, capsys, "gate", "submit", "--owner", OWNER)
    assert rc == 2

    human_approve(project, "submit")
    start(project, capsys, "submit")
    rc, sub = run_json(root, capsys, "release", "submit", "--simulate")
    assert rc == 0 and sub["submitted"] and sub["review_submission_id"]
    gate(project, capsys, "submit")

    # Publishing needs Apple's approval state and a separate human approval
    start(project, capsys, "publish")
    assert run(root, "release", "publish", "--simulate") == 1  # no publish approval yet
    human_approve(project, "publish")
    assert run(root, "release", "publish", "--simulate") == 1  # Apple has not approved yet
    assert "PENDING_DEVELOPER_RELEASE" in capsys.readouterr().err
    assert run(root, "release", "simulate-apple-approval") == 0
    rc, rel = run_json(root, capsys, "release", "publish", "--simulate")
    assert rc == 0 and rel["released"]
    gate(project, capsys, "publish")

    rc, nxt = run_json(root, capsys, "next")
    assert nxt is None
    statuses = {s["id"]: s["status"] for s in Engine(project).status()["stages"]}
    assert set(statuses.values()) == {"passed"}
    # Every stage left a persisted gate report.
    assert {p.stem for p in project.gates_dir.glob("*.json")} == set(statuses)


def test_resume_after_session_loss(project, capsys):
    copy_artifacts(project, "research")
    start(project, capsys, "research")
    # Session dies: the lock goes stale.
    lock = project.locks_dir / "research.lock"
    info = json.loads(lock.read_text())
    info["heartbeat_at"] = "2001-01-01T00:00:00Z"
    lock.write_text(json.dumps(info))
    rc, nxt = run_json(project.root, capsys, "next")
    assert nxt["action"] == "resume" and nxt["status"] == "interrupted"
    rc, res = run_json(project.root, capsys, "start", "research", "--owner", "new-session")
    assert res["action"] == "started" and res["attempt"] == 2
    rc, _ = run_json(project.root, capsys, "gate", "research", "--owner", "new-session")
    assert rc == 0


def test_concurrent_session_cannot_run_same_stage(project, capsys):
    start(project, capsys, "research")
    rc = run(project.root, "start", "research", "--owner", "someone-else")
    assert rc == 1 and "Refusing duplicate execution" in capsys.readouterr().err
