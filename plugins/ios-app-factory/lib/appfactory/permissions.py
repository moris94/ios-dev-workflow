"""Pre-approved permissions for the factory's representative use cases.

Plugins cannot ship permission rules, so `app-factory permissions install` (run by
`app-factory init`) merges them into the app repository's `.claude/settings.json`.
Only these rules are added or removed; anything else in the file is left untouched.

Safety: PreToolUse hooks still run before permission rules and keep blocking
approvals, evidence recording, direct App Store submission, secret access and edits to
machine-owned files. The approval / evidence commands are additionally denied here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .jsonio import read_json, write_json_atomic

NOTION_TOOLS = ("notion-search", "notion-fetch", "notion-create-pages", "notion-update-page")

USE_CASES: Dict[str, List[str]] = {
    "Pipeline engine: status/next/start/gate, codegen, icon/screenshot rendering, support page, "
    "ASC plan/apply, TestFlight verify, release readiness and dry-runs, Xcode build/test/capture/upload "
    "(`app-factory xcode …`)": ["Bash(app-factory *)"],
    "Xcode inspection while debugging": ["Bash(xcodebuild -version)", "Bash(xcodebuild -list *)",
                                         "Bash(xcodebuild -showsdks)", "Bash(xcrun simctl list *)",
                                         "Bash(xcodegen generate *)"],
    "Git: inspect and commit stage results locally (push is not pre-approved)":
        ["Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git add *)", "Bash(git commit *)"],
    "Market, competitor and ASO research": ["WebSearch", "WebFetch"],
    "Edit the app, tests and factory artifacts in this repository":
        ["Edit(/factory/**)", "Edit(/App/**)", "Edit(/AppTests/**)", "Edit(/AppUITests/**)",
         "Edit(/project.yml)", "Edit(/fastlane/**)", "Edit(/Gemfile)", "Edit(/.gitignore)"],
}
DENY = ["Bash(app-factory approve *)", "Bash(app-factory evidence *)"]


def notion_rules(servers: List[str]) -> List[str]:
    return [f"mcp__{srv}__{tool}" for srv in servers for tool in NOTION_TOOLS]


def rules(notion_servers: List[str]) -> Dict[str, List[str]]:
    allow = [r for group in USE_CASES.values() for r in group] + notion_rules(notion_servers)
    return {"allow": allow, "deny": list(DENY)}


def settings_path(root: Path, local: bool = False) -> Path:
    return Path(root) / ".claude" / ("settings.local.json" if local else "settings.json")


def install(root: Path, notion_servers: List[str], local: bool = False) -> dict:
    path = settings_path(root, local)
    settings = read_json(path, {}) or {}
    perms = settings.setdefault("permissions", {})
    added = {}
    for kind, wanted in rules(notion_servers).items():
        current = perms.setdefault(kind, [])
        new = [r for r in wanted if r not in current]
        current.extend(new)
        added[kind] = new
    write_json_atomic(path, settings)
    return {"settings": str(path), "added": added}


def remove(root: Path, notion_servers: List[str], local: bool = False) -> dict:
    path = settings_path(root, local)
    settings = read_json(path, {}) or {}
    perms = settings.get("permissions", {})
    ours = rules(notion_servers)
    removed = {}
    for kind, wanted in ours.items():
        before = perms.get(kind, [])
        perms[kind] = [r for r in before if r not in wanted]
        removed[kind] = [r for r in before if r in wanted]
        if not perms[kind]:
            perms.pop(kind)
    if not perms:
        settings.pop("permissions", None)
    write_json_atomic(path, settings)
    return {"settings": str(path), "removed": removed}


def describe(notion_servers: List[str]) -> dict:
    out = {case: list(r) for case, r in USE_CASES.items()}
    out["Publish the support/privacy page via Notion MCP"] = notion_rules(notion_servers)
    out["Always denied (human only)"] = list(DENY)
    return out
