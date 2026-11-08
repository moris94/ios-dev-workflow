"""Default release backend: fastlane lanes (deliver / Spaceship) driven by app-factory."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from appfactory import approval, fastlane_release as fl, guards, release
from appfactory.asc.client import Client
from appfactory.asc.fake import FakeASC
from appfactory.jsonio import read_json, write_json_atomic
from conftest import PLUGIN, run, run_json
from test_e2e import OWNER, gate, human_approve, start

HERE = os.path.dirname(__file__)


@pytest.fixture
def fl_project(project, tmp_path, monkeypatch):
    """Project wired to the fake fastlane and an App Store Connect simulator acting as the live service."""
    state = tmp_path / "asc-live.json"
    log = tmp_path / "fastlane.log"
    monkeypatch.setenv("FAKE_ASC_STATE", str(state))
    monkeypatch.setenv("FAKE_FASTLANE_LOG", str(log))
    monkeypatch.setenv("FAKE_FASTLANE_LIB", str(PLUGIN / "lib"))
    monkeypatch.setattr(fl, "_command", lambda project, lane: [sys.executable, os.path.join(HERE, "fake_fastlane.py"), "ios", lane])
    live = lambda project, simulate: (Client(FakeASC(state, bundle_id="com.example.stillnote", shared=True), sleep=lambda s: None), "live")  # noqa: E731
    monkeypatch.setattr(release, "make_client", live)
    project.lanes = lambda: log.read_text().split() if log.exists() else []  # type: ignore[attr-defined]
    project.asc_state = state  # type: ignore[attr-defined]
    return project


def _ready_for_asc(project, capsys, tmp_path):
    from conftest import copy_artifacts, pass_planning, pass_stage
    from helpers_sim import fake_build, fake_raw_captures, fake_tests
    from appfactory import codegen
    from appfactory.scaffold import scaffold

    scaffold(project)
    pass_planning(project)
    codegen.generate(project)
    fake_build(project)
    for st in ("implementation", "localization"):
        pass_stage(project, st)
    fake_tests(project, tmp_path)
    pass_stage(project, "testing")
    fake_raw_captures(project)
    assert run(project.root, "screenshots", "render") == 0
    pass_stage(project, "screenshots")
    cfg = project.config()
    cfg["asc"]["mode"] = "apply"
    write_json_atomic(project.config_path, cfg)


def test_default_backend_is_fastlane(project):
    assert project.config()["release"]["backend"] == "fastlane"
    assert fl.backend(project) == "fastlane"


def test_dry_run_plan_splits_deliver_and_api(fl_project, capsys, tmp_path):
    _ready_for_asc(fl_project, capsys, tmp_path)
    rc, rep = run_json(fl_project.root, capsys, "asc", "plan")
    plan = read_json(fl_project.asc_dir / "plan.json")
    assert plan["backend"] == "fastlane"
    assert {o["kind"].split(".")[0] for o in plan["operations"]} <= {"iap", "iap_localization", "app"}
    files = plan["fastlane"]["files"]
    assert "metadata/ja/keywords.txt" in files and "metadata/en-US/privacy_url.txt" in files
    assert "metadata/primary_category.txt" in files
    assert sum(f.startswith("screenshots/ja/") for f in files) == 3
    assert any("Upload" in d for d in plan["fastlane"]["delegated"])
    assert fl_project.lanes() == []                        # dry-run never runs fastlane


def test_full_release_through_fastlane(fl_project, capsys, tmp_path):
    root = fl_project.root
    _ready_for_asc(fl_project, capsys, tmp_path)
    start(fl_project, capsys, "asc_sync")
    rc, rep = run_json(root, capsys, "asc", "apply")
    assert rc == 0 and rep["backend"] == "fastlane" and rep["fastlane"]["status"] == "applied"
    assert rep["verify_noop"] is True and not rep["simulated"]
    assert fl_project.lanes() == ["sync_metadata"]
    # Re-running sends nothing: ledger + unchanged remote
    rc, again = run_json(root, capsys, "asc", "apply")
    assert again["fastlane"]["status"] == "skipped_ledger" and fl_project.lanes() == ["sync_metadata"]
    gate(fl_project, capsys, "asc_sync")

    start(fl_project, capsys, "testflight")
    rc, tf = run_json(root, capsys, "testflight", "verify")
    assert tf["backend"] == "fastlane" and tf["processing_state"] == "VALID"
    gate(fl_project, capsys, "testflight")

    write_json_atomic(fl_project.reports / "purchase-test.json", {
        "tester": "QA human", "tested_at": "2026-11-05T09:00:00Z", "build_number": "1", "environment": "testflight",
        "cases": [{"id": c, "result": "pass"} for c in ("purchase", "restore", "en_paywall", "ja_paywall")],
        "recorded_interactively": True})
    start(fl_project, capsys, "release_readiness")
    rc, ready = run_json(root, capsys, "release", "readiness")
    assert ready["ready"], ready["summary"]
    gate(fl_project, capsys, "release_readiness")

    start(fl_project, capsys, "submit")
    assert run(root, "release", "submit") == 1          # no approval → app-factory refuses before fastlane
    assert "submit_review" not in fl_project.lanes()
    human_approve(fl_project, "submit")
    rc, sub = run_json(root, capsys, "release", "submit")
    assert rc == 0 and sub["backend"] == "fastlane" and sub["submitted"] and sub["review_submission_id"]
    assert fl_project.lanes().count("submit_review") == 1
    rc, again = run_json(root, capsys, "release", "submit")   # not re-sent
    assert fl_project.lanes().count("submit_review") == 1
    gate(fl_project, capsys, "submit")

    start(fl_project, capsys, "publish")
    human_approve(fl_project, "publish")
    assert run(root, "release", "publish") == 1          # Apple has not approved yet → lane fails
    FakeASC(fl_project.asc_state, bundle_id="com.example.stillnote").set_version_state("PENDING_DEVELOPER_RELEASE")
    rc, rel = run_json(root, capsys, "release", "publish")
    assert rc == 0 and rel["released"] and rel["backend"] == "fastlane"
    gate(fl_project, capsys, "publish")
    assert run_json(root, capsys, "next")[1] is None


def test_lane_itself_refuses_without_approval(fl_project, capsys, tmp_path):
    """Even if someone ran the submit lane directly, the Fastfile's own approval check stops it."""
    _ready_for_asc(fl_project, capsys, tmp_path)
    with pytest.raises(fl.FastlaneError, match="submit_review failed"):
        fl.run_lane(fl_project, "submit_review", {})


def test_drift_after_delivery_is_redelivered(fl_project, capsys, tmp_path):
    _ready_for_asc(fl_project, capsys, tmp_path)
    run(fl_project.root, "asc", "apply")
    fake = FakeASC(fl_project.asc_state, bundle_id="com.example.stillnote")
    for loc in fake.db["appStoreVersionLocalizations"].values():
        loc["attributes"]["promotionalText"] = "edited by hand in App Store Connect"
    fake.save()
    rc, rep = run_json(fl_project.root, capsys, "asc", "apply")
    assert rep["fastlane"]["status"] == "applied" and rep["verify_noop"] is True
    assert fl_project.lanes() == ["sync_metadata", "sync_metadata"]


def test_explicit_api_backend_does_not_use_fastlane(fl_project, capsys, tmp_path):
    _ready_for_asc(fl_project, capsys, tmp_path)
    cfg = fl_project.config()
    cfg["release"]["backend"] = "api"
    write_json_atomic(fl_project.config_path, cfg)
    rc, rep = run_json(fl_project.root, capsys, "asc", "apply")
    assert rc == 0 and rep["backend"] == "api" and rep["verify_noop"] is True
    assert fl_project.lanes() == []
    assert read_json(fl_project.asc_dir / "plan.json")["backend"] == "api"


@pytest.mark.parametrize("cmd", ["bundle exec fastlane submit_review", "fastlane ios release_version",
                                 "bundle exec fastlane sync_metadata", "fastlane deliver"])
def test_hooks_block_direct_release_lanes(project, cmd):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(project.root)}
    assert guards.guard_bash(payload) == 2


@pytest.mark.skipif(not (shutil.which("fastlane") or os.path.exists("/opt/rbenv/versions/3.3.6/bin/fastlane")),
                    reason="fastlane not installed")
def test_template_fastfile_loads_in_real_fastlane(project):
    """The rendered Fastfile parses and defines the lanes app-factory calls (real fastlane, no network)."""
    from appfactory.scaffold import scaffold

    scaffold(project)
    exe = shutil.which("fastlane") or "/opt/rbenv/versions/3.3.6/bin/fastlane"
    env = dict(os.environ, FASTLANE_SKIP_UPDATE_CHECK="1", FASTLANE_OPT_OUT_USAGE="1", CI="1")
    out = subprocess.run([exe, "lanes", "--json"], cwd=project.root, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    text = out.stdout
    for lane in ("beta", "build_status", "sync_metadata", "submit_review", "release_version"):
        assert lane in text, lane
