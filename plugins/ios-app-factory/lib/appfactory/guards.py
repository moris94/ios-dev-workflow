"""Claude Code hook logic (stdlib only, fast, fail-closed for release actions).

* guard-bash   (PreToolUse: Bash)        – approvals, submission/release, secrets, git hygiene
* guard-files  (PreToolUse: Write|Edit…) – machine-owned files cannot be hand edited
* session-start (SessionStart)           – inject resume status into the new session

Blocking is done with exit code 2; stderr is shown to Claude as the reason.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

RELEASE_WORDS = re.compile(r"\b(approve|submit|publish|reviewSubmission|ReleaseRequest|deliver|upload_to_app_store)\b")

HUMAN_ONLY = [
    (re.compile(r"\b(app-factory|appfactory)\b.*\bapprove\b"), "Approvals are human-only: the human must run `app-factory approve <submit|publish>` in their own terminal."),
    (re.compile(r"\b(app-factory|appfactory)\b.*\bevidence\b"), "Purchase-test evidence must be recorded by the human tester in their own terminal."),
]
ALWAYS_DENY = [
    (re.compile(r"api\.appstoreconnect\.apple\.com.*(reviewSubmission|appStoreVersionReleaseRequests|appStoreVersionSubmissions|inAppPurchaseSubmissions)", re.I),
     "Direct App Store Connect submission/release calls are forbidden; use `app-factory release submit|publish` after human approval."),
    (re.compile(r"(curl|http|wget|python\d?\s+-c).*api\.appstoreconnect\.apple\.com", re.I),
     "Direct App Store Connect API calls are not allowed; use `app-factory asc ...` (ledger-protected, redacted)."),
    (re.compile(r"\bfastlane\b.*\b(deliver|upload_to_app_store|appstore|release|submit_for_review|precheck_and_submit)\b"),
     "fastlane deliver/submit lanes are disabled; metadata goes through `app-factory asc`, submission through `app-factory release submit` after human approval."),
    (re.compile(r"submit_for_review\s*[:=]\s*true|automatic_release\s*[:=]\s*true|distribute_external\s*[:=]\s*true", re.I),
     "Automatic submission/release/external distribution flags are forbidden."),
    (re.compile(r"approver\.key"), "The approver key is private to the human approver."),
    (re.compile(r"(\bcat|\bless|\bmore|\bhead|\btail|\bbase64|\bxxd|\bod|\bstrings|\bcp|\bscp|\bcurl)\b[^|;&]*\.p8\b"),
     "Reading or copying App Store Connect private keys is not allowed."),
    (re.compile(r"(echo|printf|print)[^|;&]*\$\{?(ASC_PRIVATE_KEY|ASC_PRIVATE_KEY_BASE64|FASTLANE_PASSWORD|MATCH_PASSWORD|APP_STORE_CONNECT_API_KEY_CONTENT)\b"),
     "Printing secrets is not allowed."),
    (re.compile(r"^\s*(printenv|env|set|export\s+-p|declare\s+-x)\s*($|\|)"), "Dumping the environment would expose secrets."),
]
PROTECTED_PATHS = re.compile(
    r"(factory/approvals/|factory/state\.json|factory/history\.jsonl|factory/gates/|factory/asc/ledger[\w.]*\.json|"
    r"factory/asc/sync-report\.json|factory/reports/(purchase-test|submission|release|testflight)\.json|"
    r"factory/artifacts/release/readiness\.json|\.factory-tmp/locks)"
)
MUTATING = re.compile(r"(>|\btee\b|\bcp\b|\bmv\b|\brm\b|\bsed\s+-i|\btouch\b|\bpython\d?\b|\bperl\b|\bchmod\b|\bln\b|\btruncate\b|\bdd\b|\bjq\b.*>)")
GIT_TMP = re.compile(r"(\.factory-tmp|\.xcresult|DerivedData|\.p8$|(^|/)\.env|xcuserdata|\.ipa$)")

MACHINE_OWNED = PROTECTED_PATHS
GENERATED = re.compile(r"(App/Sources/Design/DesignTokens\.swift|App/Sources/Store/ProductCatalog\.swift|App/Resources/Products\.storekit|"
                       r"factory/screenshots/(manifest\.json|final/.*)|factory/asc/plan\.json|factory/reports/(build|tests)\.json)$")


def _deny(reason: str) -> int:
    print(f"[ios-app-factory] BLOCKED: {reason}", file=sys.stderr)
    return 2


def _read_input() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}


def _project_root(cwd: Optional[str]) -> Optional[Path]:
    start = Path(cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    for c in [start, *start.parents]:
        if (c / "factory" / "config.json").exists():
            return c
    return None


def _approval_ok(root: Optional[Path], kind: str):
    if root is None:
        return False, "no factory project found"
    from . import approval
    from .jsonio import read_json
    from .project import Project

    readiness = read_json(root / "factory/artifacts/release/readiness.json")
    if not readiness:
        return False, "release readiness has not been computed"
    return approval.verify(Project(root), kind, readiness.get("readiness_digest"))


def guard_bash(payload: dict) -> int:
    cmd = (payload.get("tool_input") or {}).get("command", "") or ""
    flat = " ".join(cmd.split())
    for pattern, reason in HUMAN_ONLY + ALWAYS_DENY:
        if pattern.search(flat):
            return _deny(reason)
    m = re.search(r"\b(app-factory|appfactory)\b.*\brelease\s+(submit|publish)\b", flat)
    if m:
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = flat.split()
        if "--dry-run" not in tokens:
            ok, msg = _approval_ok(_project_root(payload.get("cwd")), m.group(2))
            if not ok:
                return _deny(f"`release {m.group(2)}` requires a valid human approval: {msg}")
    if PROTECTED_PATHS.search(flat) and MUTATING.search(flat) and not re.search(r"\b(app-factory|appfactory)\b", flat):
        return _deny("factory state, gate results, approvals, ledgers and evidence are machine-owned; use `app-factory` commands.")
    if re.search(r"\bgit\s+add\b", flat):
        if re.search(r"\s(-f|--force)\b", flat):
            return _deny("`git add --force` would commit ignored temporary/secret files.")
        if GIT_TMP.search(flat):
            return _deny("temporary logs, build products and secrets must not be committed.")
    if re.search(r"\bgit\s+commit\b", flat):
        root = _project_root(payload.get("cwd"))
        if root is not None:
            staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=root, capture_output=True, text=True).stdout.split()
            bad = [s for s in staged if GIT_TMP.search(s)]
            if bad:
                return _deny(f"staged temporary/secret files: {bad[:10]} — unstage them (they are gitignored by app-factory init).")
    return 0


def guard_files(payload: dict) -> int:
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path:
        return 0
    p = Path(path)
    root = _project_root(payload.get("cwd"))
    rel = p.as_posix()
    if root is not None:
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    if p.suffix == ".p8" or p.name == "approver.key":
        return _deny("credential files must not be written by the agent.")
    if MACHINE_OWNED.search(rel):
        return _deny(f"{rel} is machine-owned (state, gates, approvals, ledger, evidence). Use `app-factory` commands.")
    if GENERATED.search(rel):
        return _deny(f"{rel} is generated. Edit the source artifact and run the generator "
                     "(`app-factory codegen`, `screenshots render`, `asc plan`, or scripts/xcode/*.sh).")
    return 0


def session_start(payload: dict) -> int:
    root = _project_root(payload.get("cwd"))
    if root is None:
        return 0
    try:
        from .engine import Engine
        from .project import Project

        st = Engine(Project(root)).status()
        done = [r["id"] for r in st["stages"] if r["status"] == "passed"]
        attention = [f"{r['id']}={r['status']}" + (f" ({r['reason']})" if r.get("reason") else "")
                     for r in st["stages"] if r["status"] in ("failed", "stale", "interrupted", "running")]
        lines = ["[ios-app-factory] Pipeline state found in this repository.",
                 f"passed: {', '.join(done) or 'none'}"]
        if attention:
            lines.append("needs attention: " + "; ".join(attention))
        nxt = st.get("next")
        lines.append("next: " + (json.dumps(nxt, ensure_ascii=False) if nxt else "pipeline complete"))
        lines.append("To resume, invoke the /ios-app-factory:factory skill with `resume`.")
        print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001 – never break session start
        print(f"[ios-app-factory] could not read pipeline state: {type(exc).__name__}", file=sys.stderr)
    return 0


def main(which: str) -> int:
    payload = _read_input()
    try:
        if which == "guard-bash":
            return guard_bash(payload)
        if which == "guard-files":
            return guard_files(payload)
        if which == "session-start":
            return session_start(payload)
    except Exception as exc:  # noqa: BLE001
        cmd = json.dumps(payload.get("tool_input") or {})
        if which != "session-start" and RELEASE_WORDS.search(cmd):
            return _deny(f"guard error ({type(exc).__name__}); failing closed for a release-related action")
        print(f"[ios-app-factory] guard error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    return 0
