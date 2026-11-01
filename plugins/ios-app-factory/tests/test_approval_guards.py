import io
import json
import os
import sys

import pytest

from appfactory import approval, guards
from appfactory.jsonio import read_json, write_json_atomic

READY = {"readiness_digest": "a" * 64, "app_version": "1.0.0", "build_number": "1", "summary": ["ok"]}


def _approve(project, kind="submit", readiness=READY, phrase=None):
    phrase = phrase or approval.phrase_for(kind, "Stillnote", readiness["app_version"], readiness["build_number"])
    return approval.create(project, kind, readiness, approver="human", ask=lambda _: phrase, interactive_check=lambda: True)


def _write_readiness(project, digest="a" * 64):
    write_json_atomic(project.root / "factory/artifacts/release/readiness.json", {**READY, "readiness_digest": digest})


def test_approval_requires_tty(project):
    with pytest.raises(approval.ApprovalError, match="interactive terminal"):
        approval.create(project, "submit", READY, ask=lambda _: "x", interactive_check=lambda: False)


def test_approval_refused_inside_claude_code(project, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(approval.ApprovalError, match="Claude Code"):
        _approve(project)


def test_wrong_phrase_rejected(project):
    with pytest.raises(approval.ApprovalError, match="did not match"):
        _approve(project, phrase="yes")
    assert not (project.approvals_dir / "submit.json").exists()


def test_valid_tampered_and_changed(project):
    _approve(project)
    ok, msg = approval.verify(project, "submit", "a" * 64)
    assert ok, msg
    ok, msg = approval.verify(project, "submit", "b" * 64)
    assert not ok and "changed after approval" in msg
    p = project.approvals_dir / "submit.json"
    rec = read_json(p)
    rec["readiness_digest"] = "b" * 64
    write_json_atomic(p, rec)
    ok, msg = approval.verify(project, "submit", "b" * 64)
    assert not ok and "signature invalid" in msg
    assert not approval.verify(project, "publish", "a" * 64)[0]


def test_expired(project):
    _approve(project)
    p = project.approvals_dir / "submit.json"
    rec = read_json(p)
    rec["expires_at"] = "2000-01-01T00:00:00Z"
    write_json_atomic(p, rec)
    ok, msg = approval.verify(project, "submit", "a" * 64)
    assert not ok  # signature no longer matches either; never accepted


def _bash(cmd, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}


@pytest.mark.parametrize("cmd", [
    "app-factory approve submit",
    "/x/bin/app-factory approve publish --approver me",
    "app-factory evidence purchase-test",
    "curl -X POST https://api.appstoreconnect.apple.com/v1/reviewSubmissions -d @x",
    "curl https://api.appstoreconnect.apple.com/v1/apps",
    "bundle exec fastlane deliver --submit_for_review",
    "fastlane run upload_to_app_store",
    "cat ~/keys/AuthKey_ABC.p8",
    "echo $ASC_PRIVATE_KEY",
    "printenv",
    "env | grep ASC",
    "cat ~/.config/ios-app-factory/approver.key",
    "echo '{}' > factory/approvals/submit.json",
    "rm factory/asc/ledger.json",
    "python3 -c 'open(\"factory/state.json\",\"w\")'",
    "git add -f .factory-tmp/logs/build.log",
    "git add DerivedData",
])
def test_guard_bash_blocks(project, cmd, capsys):
    assert guards.guard_bash(_bash(cmd, project.root)) == 2
    assert "BLOCKED" in capsys.readouterr().err


@pytest.mark.parametrize("cmd", [
    "app-factory status",
    "app-factory asc plan",
    "app-factory release submit --dry-run",
    "cat factory/approvals/submit.json",
    "git add factory App",
    "xcodebuild -version",
    "bundle exec fastlane beta",
])
def test_guard_bash_allows(project, cmd):
    assert guards.guard_bash(_bash(cmd, project.root)) == 0


def test_release_submit_needs_valid_approval(project):
    _write_readiness(project)
    payload = _bash("app-factory release submit", project.root)
    assert guards.guard_bash(payload) == 2
    _approve(project)
    assert guards.guard_bash(payload) == 0
    _write_readiness(project, "c" * 64)  # anything changed since approval
    assert guards.guard_bash(payload) == 2


def test_git_commit_blocks_staged_temp_files(project):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=project.root, check=True)
    tmpf = project.root / "notes.p8"
    tmpf.write_text("secret")
    subprocess.run(["git", "add", "-f", "notes.p8"], cwd=project.root, check=True)
    assert guards.guard_bash(_bash("git commit -m x", project.root)) == 2


@pytest.mark.parametrize("path,blocked", [
    ("factory/state.json", True),
    ("factory/approvals/submit.json", True),
    ("factory/gates/research.json", True),
    ("factory/asc/ledger.json", True),
    ("factory/reports/purchase-test.json", True),
    ("App/Sources/Design/DesignTokens.swift", True),
    ("factory/screenshots/final/ja/iphone_6_9/01_home.png", True),
    ("keys/AuthKey.p8", True),
    ("factory/artifacts/support_page/publication.json", True),
    ("App/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png", True),
    ("factory/artifacts/app_icon/icon.json", False),
    ("factory/artifacts/support_page/page.md", False),
    ("factory/artifacts/mvp/mvp.json", False),
    ("App/Sources/Features/Home/HomeView.swift", False),
])
def test_guard_files(project, path, blocked):
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(project.root / path)}, "cwd": str(project.root)}
    assert (guards.guard_files(payload) == 2) is blocked


def test_session_start_reports_state(project, capsys):
    assert guards.session_start({"cwd": str(project.root)}) == 0
    out = capsys.readouterr().out
    assert "Pipeline state found" in out and "next:" in out and "resume" in out


def test_hook_entrypoint_runs_with_stdlib_python(project):
    import subprocess
    from conftest import PLUGIN

    payload = json.dumps(_bash("app-factory approve submit", project.root))
    r = subprocess.run([sys.executable, "-S", str(PLUGIN / "hooks/run_hook.py"), "guard-bash"], input=payload,
                       capture_output=True, text=True)
    assert r.returncode == 2 and "human-only" in r.stderr


def test_hooks_json_wiring():
    from conftest import PLUGIN

    cfg = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
    assert cfg["PreToolUse"][0]["matcher"] == "Bash"
    assert "Write" in cfg["PreToolUse"][1]["matcher"]
    assert "SessionStart" in cfg
