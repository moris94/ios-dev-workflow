"""Human approvals: ``ux`` (UI/UX before implementation), ``submit`` and ``publish``.

Two channels, chosen by ``approval.mode`` in factory/config.json:

* ``chat`` (default): Claude runs ``app-factory approval request <kind>`` and shows what is
  being approved; the human replies in the Claude conversation (e.g. "承認 提出"). A
  ``UserPromptSubmit`` hook — which only fires for text the human actually typed — records
  the approval. Claude cannot produce that event, and hooks stop it from writing approval
  files or running the terminal command.
* ``terminal``: ``app-factory approve <kind>`` in the human's own interactive terminal,
  with a typed confirmation phrase (stricter, less convenient).

Either way the record is bound to a digest of what was approved (UX storyboards or the
release readiness), HMAC-signed with a key outside the repository, and expires; any change
after approval invalidates it.
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

SIGNED_FIELDS = ("kind", "readiness_digest", "app_version", "build_number", "approver", "approved_at", "expires_at",
                 "interactive", "channel")
CHANNELS = ("chat", "terminal")


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
    if kind not in ("submit", "publish", "ux"):
        raise ApprovalError("kind must be submit, publish or ux")
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
    return write_record(project, kind, readiness, approver=approver, channel="terminal", note=note)


def write_record(project: Project, kind: str, subject: dict, approver: Optional[str] = None,
                 channel: str = "chat", note: str = "") -> dict:
    """Persist a signed approval. Only reached from a human action: the terminal prompt or the
    UserPromptSubmit hook handling the human's own chat message."""
    if kind not in ("submit", "publish", "ux"):
        raise ApprovalError("kind must be submit, publish or ux")
    if channel not in CHANNELS:
        raise ApprovalError(f"channel must be one of {CHANNELS}")
    cfg = project.config()
    ttl = float(cfg.get("release", {}).get("approval_ttl_hours", 72))
    t = now()
    record = {
        "kind": kind,
        "readiness_digest": subject["readiness_digest"],
        "app_version": subject["app_version"],
        "build_number": str(subject["build_number"]),
        "approver": approver or getpass.getuser(),
        "approved_at": t.isoformat().replace("+00:00", "Z"),
        "expires_at": (t + timedelta(hours=ttl)).isoformat().replace("+00:00", "Z"),
        "interactive": True,
        "channel": channel,
    }
    record["signature"] = _sign(record, _load_key(create=True))
    if note:
        record["note"] = note[:500]
    write_json_atomic(approval_path(project, kind), record)
    return record


def verify(project: Project, kind: str, readiness_digest: Optional[str]) -> Tuple[bool, str]:
    rec = read_json(approval_path(project, kind))
    if not rec:
        return False, (f"no {kind} approval recorded — run `app-factory approval request {kind}`, show it to the human "
                       f"and let them reply in the chat (or `app-factory approve {kind}` in a terminal)")
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
