"""Human approval for review submission and release.

Enforced at three independent layers:

1. ``app-factory approve`` only runs on an interactive terminal (stdin and
   stdout are TTYs) and requires the human to type a confirmation phrase that
   names the exact app, version and build. Claude Code's Bash tool is not a
   TTY, so Claude cannot produce an approval.
2. The approval is bound to the *readiness digest* (build, metadata,
   screenshots, IAP, ASC plan). Any change after approval invalidates it.
   It is HMAC-signed with a key stored outside the repository
   (``~/.config/ios-app-factory/approver.key``, mode 0600) and expires.
3. Plugin hooks (PreToolUse) block Claude from running ``approve``, from
   running ``release submit/publish`` without a valid approval, from writing
   into ``factory/approvals/`` and from reading the approver key.
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from typing import Callable, Optional, Tuple

from .hashing import canonical_json
from .jsonio import read_json, write_json_atomic
from .project import Project
from .timeutil import now, parse_iso

SIGNED_FIELDS = ("kind", "readiness_digest", "app_version", "build_number", "approver", "approved_at", "expires_at", "interactive")


class ApprovalError(RuntimeError):
    pass


def key_path() -> Path:
    return Path(os.environ.get("FACTORY_APPROVER_KEY_PATH", "~/.config/ios-app-factory/approver.key")).expanduser()


def _load_key(create: bool) -> bytes:
    p = key_path()
    if not p.exists():
        if not create:
            raise ApprovalError(f"approver key missing ({p}); an approval must be created with `app-factory approve` by a human")
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    if p.stat().st_mode & 0o077:
        raise ApprovalError(f"approver key {p} must not be group/world accessible (chmod 600)")
    return bytes.fromhex(p.read_text().strip())


def _sign(record: dict, key: bytes) -> str:
    payload = canonical_json({k: record[k] for k in SIGNED_FIELDS})
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def approval_path(project: Project, kind: str) -> Path:
    return project.approvals_dir / f"{kind}.json"


def phrase_for(kind: str, app_name: str, version: str, build: str) -> str:
    return f"{kind.upper()} {app_name} {version} ({build})"


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def create(project: Project, kind: str, readiness: dict, approver: Optional[str] = None, note: str = "",
           ask: Callable[[str], str] = input, interactive_check: Callable[[], bool] = is_interactive) -> dict:
    if kind not in ("submit", "publish"):
        raise ApprovalError("kind must be submit or publish")
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        raise ApprovalError("approvals cannot be created from inside a Claude Code session; run this in your own terminal")
    if not interactive_check():
        raise ApprovalError("approval requires an interactive terminal (TTY); it cannot be scripted or run by an agent")
    cfg = project.config()
    app = cfg["app"]["name"]
    version, build = readiness["app_version"], str(readiness["build_number"])
    expected = phrase_for(kind, app, version, build)
    print(f"\nYou are approving: {kind.upper()} of {app} {version} (build {build})")
    print(f"Readiness digest: {readiness['readiness_digest']}")
    for line in readiness.get("summary", []):
        print(f"  - {line}")
    typed = ask(f"\nType exactly '{expected}' to approve: ").strip()
    if typed != expected:
        raise ApprovalError("confirmation phrase did not match; nothing approved")
    ttl = float(cfg.get("release", {}).get("approval_ttl_hours", 72))
    t = now()
    record = {
        "kind": kind,
        "readiness_digest": readiness["readiness_digest"],
        "app_version": version,
        "build_number": build,
        "approver": approver or getpass.getuser(),
        "approved_at": t.isoformat().replace("+00:00", "Z"),
        "expires_at": (t + timedelta(hours=ttl)).isoformat().replace("+00:00", "Z"),
        "interactive": True,
    }
    record["signature"] = _sign(record, _load_key(create=True))
    if note:
        record["note"] = note
    write_json_atomic(approval_path(project, kind), record)
    return record


def verify(project: Project, kind: str, readiness_digest: Optional[str]) -> Tuple[bool, str]:
    rec = read_json(approval_path(project, kind))
    if not rec:
        return False, f"no {kind} approval recorded (human must run `app-factory approve {kind}` in a terminal)"
    try:
        key = _load_key(create=False)
    except ApprovalError as exc:
        return False, str(exc)
    if not all(k in rec for k in SIGNED_FIELDS + ("signature",)):
        return False, "approval record incomplete"
    if not hmac.compare_digest(_sign(rec, key), rec["signature"]):
        return False, "approval signature invalid (record was modified or not created by `app-factory approve`)"
    if rec["kind"] != kind or rec.get("interactive") is not True:
        return False, "approval kind mismatch or non-interactive"
    if parse_iso(rec["expires_at"]) < now():
        return False, f"approval expired at {rec['expires_at']}"
    if readiness_digest is None or rec["readiness_digest"] != readiness_digest:
        return False, "approval does not match the current release readiness (something changed after approval)"
    return True, f"approved by {rec['approver']} at {rec['approved_at']}"
