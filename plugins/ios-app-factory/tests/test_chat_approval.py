"""Approvals completed inside the Claude conversation (UserPromptSubmit hook) and the mvp profile."""
import json
import subprocess
import sys

import pytest

from appfactory import approval, guards, ux
from appfactory.engine import Engine
from appfactory.gates import run_gate
from appfactory.jsonio import read_json, write_json_atomic
from conftest import PLUGIN, copy_artifacts, pass_planning, pass_stage, run_json, set_profile


@pytest.fixture
def ux_ready(project):
    pass_planning(project, until="design")
    copy_artifacts(project, "ux")
    ux.render(project)
    return project


def say(project, text):
    """What the UserPromptSubmit hook receives when the human sends a chat message."""
    return guards.handle_prompt_for_tests(project.root, text)


def test_request_then_human_reply_records_chat_approval(ux_ready, capsys):
    rc, req = run_json(ux_ready.root, capsys, "approval", "request", "ux")
    assert rc == 0 and "承認 UX" in req["ask_human"]
    out = say(ux_ready, "承認 UX")
    assert "APPROVED 'ux'" in out
    rec = read_json(ux_ready.approvals_dir / "ux.json")
    assert rec["channel"] == "chat" and "承認 UX" in rec["note"]
    ok, _ = approval.verify(ux_ready, "ux", ux.ux_digest(ux_ready))
    assert ok
    pass_stage(ux_ready, "ux_review")


@pytest.mark.parametrize("text", ["UXを承認", "approve ux", "LGTM UX", "UX OK!", "承認します UX。"])
def test_accepted_reply_forms(ux_ready, capsys, text):
    run_json(ux_ready.root, capsys, "approval", "request", "ux")
    assert "APPROVED" in say(ux_ready, text)


@pytest.mark.parametrize("text", ["OK", "はい", "承認", "いいですね、UXは承認でお願いします。ただしボタンの色は後で相談させてください"])
def test_ambiguous_or_long_replies_do_not_approve(ux_ready, capsys, text):
    run_json(ux_ready.root, capsys, "approval", "request", "ux")
    assert say(ux_ready, text) is None
    assert not (ux_ready.approvals_dir / "ux.json").exists()


def test_reply_for_other_kind_is_not_misapplied(ux_ready, capsys):
    run_json(ux_ready.root, capsys, "approval", "request", "ux")
    out = say(ux_ready, "承認 提出")
    assert "not 'submit'" in out and not (ux_ready.approvals_dir / "ux.json").exists()


def test_decline_clears_request(ux_ready, capsys):
    run_json(ux_ready.root, capsys, "approval", "request", "ux")
    assert "DECLINED" in say(ux_ready, "却下 UX")
    assert say(ux_ready, "承認 UX") is None                 # nothing pending any more


def test_change_after_request_is_not_approved(ux_ready, capsys):
    run_json(ux_ready.root, capsys, "approval", "request", "ux")
    p = ux_ready.root / ux.UX_JSON
    d = read_json(p)
    d["use_cases"][0]["title"]["en-US"] = "Something else"
    write_json_atomic(p, d)
    ux.render(ux_ready)
    assert "content changed" in say(ux_ready, "承認 UX")
    assert not (ux_ready.approvals_dir / "ux.json").exists()


def test_terminal_mode_ignores_chat(ux_ready, capsys):
    cfg = ux_ready.config()
    cfg["approval"]["mode"] = "terminal"
    write_json_atomic(ux_ready.config_path, cfg)
    run_json(ux_ready.root, capsys, "approval", "request", "ux")
    assert "terminal approvals" in say(ux_ready, "承認 UX")
    assert not (ux_ready.approvals_dir / "ux.json").exists()


def test_claude_cannot_forge_the_request_or_record(ux_ready):
    for path in (".factory-tmp/approval-request.json", "factory/approvals/ux.json"):
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(ux_ready.root / path)}, "cwd": str(ux_ready.root)}
        assert guards.guard_files(payload) == 2
    bash = {"tool_name": "Bash", "tool_input": {"command": "echo '{}' > .factory-tmp/approval-request.json"},
            "cwd": str(ux_ready.root)}
    assert guards.guard_bash(bash) == 2


def test_real_hook_entrypoint(ux_ready, capsys):
    run_json(ux_ready.root, capsys, "approval", "request", "ux")
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "承認 UX", "cwd": str(ux_ready.root)})
    r = subprocess.run([sys.executable, str(PLUGIN / "hooks/run_hook.py"), "user-prompt"], input=payload,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "APPROVED 'ux'" in r.stdout
    assert read_json(ux_ready.approvals_dir / "ux.json")["channel"] == "chat"
    hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
    assert "UserPromptSubmit" in hooks


# ------------------------------------------------------------------ profiles
def _gate(project, stage):
    eng = Engine(project)
    return run_gate(project, eng.pipeline.get(stage), eng.load_state())


def test_mvp_profile_turns_polish_into_warnings(project):
    pass_planning(project, until="mvp")
    copy_artifacts(project, "design")
    p = project.artifact("design", "design.json")
    d = read_json(p)
    d["color"]["light"]["accent"] = "#4F46E5"            # Tailwind indigo-600: readable, but a template default
    d["references"] = [r for r in d["references"] if r["type"] != "skill"]
    write_json_atomic(p, d)
    rep = _gate(project, "design")
    assert rep["profile"] == "mvp" and rep["passed"] is True, [c for c in rep["checks"] if not c["passed"] and c["severity"] == "error"]
    relaxed = {c["id"] for c in rep["checks"] if c.get("relaxed_by_profile")}
    assert {"anti-generic.accent", "references.skill"} <= relaxed
    set_profile(project, "strict")
    assert _gate(project, "design")["passed"] is False


def test_mvp_profile_keeps_hard_limits(project):
    pass_planning(project, until="support_page")
    copy_artifacts(project, "aso")
    p = project.artifact("aso", "aso.json")
    d = read_json(p)
    d["locales"]["en-US"]["description"] = "x" * 4100      # App Store hard limit
    write_json_atomic(p, d)
    rep = _gate(project, "aso")
    failing = {c["id"] for c in rep["checks"] if not c["passed"] and c["severity"] == "error"}
    assert "en-US.description.max" in failing or any(i.startswith("schema") for i in failing)


def test_new_projects_default_to_delivery_first(project):
    cfg = project.config()
    assert cfg["quality"]["profile"] == "mvp"
    assert cfg["approval"] == {"mode": "chat", "single_release_approval": True}
    assert cfg["release"]["require_manual_purchase_test"] is False


def test_hook_allows_publish_under_single_release_approval(project):
    from conftest import human_approves_ux  # noqa: F401  (keeps imports aligned with other tests)

    write_json_atomic(project.root / "factory/artifacts/release/readiness.json",
                      {"readiness_digest": "d" * 64, "app_version": "1.0.0", "build_number": "1", "summary": []})
    approval.write_record(project, "submit", {"readiness_digest": "d" * 64, "app_version": "1.0.0", "build_number": "1"})
    payload = {"tool_name": "Bash", "tool_input": {"command": "app-factory release publish"}, "cwd": str(project.root)}
    assert guards.guard_bash(payload) == 0
    cfg = project.config()
    cfg["approval"]["single_release_approval"] = False
    write_json_atomic(project.config_path, cfg)
    assert guards.guard_bash(payload) == 2


def test_readiness_not_rewritten_when_unchanged(project, monkeypatch):
    """Regression: re-writing readiness.json with a new timestamp made release_readiness stale
    (CI failure on main when `approval request submit` ran a second later than the gate)."""
    from appfactory import release

    times = iter(["2026-11-09T01:00:00Z", "2026-11-09T01:00:05Z"])
    monkeypatch.setattr(release, "now_iso", lambda: next(times))
    first = release.write_readiness(project)
    path = project.root / release.READINESS
    before = path.read_bytes()
    second = release.write_readiness(project)
    assert second["readiness_digest"] == first["readiness_digest"]
    assert path.read_bytes() == before
