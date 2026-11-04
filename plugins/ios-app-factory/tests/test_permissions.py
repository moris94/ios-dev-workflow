import json

from appfactory import permissions
from appfactory.jsonio import read_json, write_json_atomic
from conftest import run, run_json


def test_init_preapproves_representative_use_cases(project):
    s = read_json(project.root / ".claude/settings.json")
    allow, deny = s["permissions"]["allow"], s["permissions"]["deny"]
    for rule in ("Bash(app-factory *)", "Bash(git commit *)", "WebSearch", "WebFetch", "Edit(/App/**)",
                 "Edit(/factory/**)", "mcp__Notion__notion-create-pages", "mcp__Notion__notion-update-page"):
        assert rule in allow, rule
    assert "Bash(git push *)" not in allow                      # push stays a conscious decision
    assert not any("notion-delete" in r for r in allow)
    assert {"Bash(app-factory approve *)", "Bash(app-factory evidence *)"} <= set(deny)


def test_install_is_idempotent_and_preserves_user_rules(project, capsys):
    path = project.root / ".claude/settings.json"
    s = read_json(path)
    s["permissions"]["allow"].append("Bash(make lint)")
    s["model"] = "opus"
    write_json_atomic(path, s)
    rc, out = run_json(project.root, capsys, "permissions", "install")
    assert out["added"] == {"allow": [], "deny": []}
    rc, out = run_json(project.root, capsys, "permissions", "remove")
    s = read_json(path)
    assert s["permissions"]["allow"] == ["Bash(make lint)"] and s["model"] == "opus"


def test_custom_notion_server_and_local(project, capsys):
    rc, out = run_json(project.root, capsys, "permissions", "install", "--local", "--notion-server", "claude_ai_Notion")
    local = read_json(project.root / ".claude/settings.local.json")
    assert "mcp__claude_ai_Notion__notion-create-pages" in local["permissions"]["allow"]


def test_hooks_still_block_preapproved_prefix(project):
    from appfactory import guards

    payload = {"tool_name": "Bash", "tool_input": {"command": "app-factory approve submit"}, "cwd": str(project.root)}
    assert guards.guard_bash(payload) == 2     # allowed by Bash(app-factory *) but blocked by the hook


def test_no_permissions_flag(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    assert run(root, "init", "--idea", "x", "--name", "X", "--bundle-id", "com.example.x", "--no-permissions") == 0
    assert not (root / ".claude/settings.json").exists()


def test_xcode_subcommand_refuses_off_macos(project):
    import platform

    rc = run(project.root, "xcode", "build")
    assert rc == (3 if platform.system() != "Darwin" else rc)


def test_skills_use_rule_matching_cli_form():
    from conftest import PLUGIN

    for p in list((PLUGIN / "skills").glob("*/SKILL.md")) + list((PLUGIN / "agents").glob("*.md")):
        text = p.read_text()
        assert "bin/app-factory" not in text, p          # absolute paths would not match Bash(app-factory *)
        assert "scripts/xcode/" not in text, p
