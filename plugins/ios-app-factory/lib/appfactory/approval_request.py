"""Chat approvals: pending request (written by Claude via the CLI) + the human's reply
(read by the UserPromptSubmit hook, i.e. text the human really typed).

The reply must name what is being approved (e.g. "承認 提出", "approve submit",
"UX を承認"), so a short "OK" meant for something else can never approve a release.
The approved content is re-hashed when the reply arrives; if anything changed since the
request, nothing is recorded.
"""
from __future__ import annotations

import getpass
import re
from typing import Optional

from . import approval
from .hashing import sha256_json
from .jsonio import read_json, write_json_atomic
from .project import Project
from .timeutil import now_iso

KINDS = ("ux", "submit", "publish", "purchase_test")
LABELS = {
    "ux": ("ux", "ui/ux", "uiux", "ux案", "画面"),
    "submit": ("submit", "提出", "審査提出", "申請", "審査"),
    "publish": ("publish", "release", "公開", "リリース"),
    "purchase_test": ("purchase test", "purchase-test", "purchase_test", "課金テスト", "購入テスト"),
}
APPROVE = r"(?:承認(?:します|する)?|ok|okay|approve[sd]?|lgtm|go)"
REJECT = r"(?:却下|差し戻し|reject(?:ed)?|no)"
DISPLAY = {"ux": "UX", "submit": "提出", "publish": "公開", "purchase_test": "課金テスト"}


class RequestError(RuntimeError):
    pass


def _pending_path(project: Project):
    return project.tmp / "approval-request.json"


def mode(project: Project) -> str:
    return (project.config().get("approval") or {}).get("mode", "chat")


def single_release_approval(project: Project) -> bool:
    from .profiles import profile_of

    cfg = project.config()
    default = profile_of(cfg) == "mvp"
    return bool((cfg.get("approval") or {}).get("single_release_approval", default))


def subject(project: Project, kind: str) -> dict:
    if kind == "ux":
        from . import ux

        s = ux.approval_subject(project)
        if not s["readiness_digest"] or not ux.board_paths(project):
            raise RequestError("no UX storyboards yet (ux.json + `app-factory ux render`)")
        return s
    from .release import compute_readiness

    r = compute_readiness(project)
    if kind == "purchase_test":
        tf = read_json(project.reports / "testflight.json") or {}
        if not tf.get("build_id"):
            raise RequestError("no TestFlight build recorded yet (`app-factory testflight verify`)")
        cfg = project.config()
        return {"readiness_digest": sha256_json({"build_id": tf["build_id"], "build": str(cfg["app"]["build_number"])}),
                "app_version": cfg["app"]["version"], "build_number": str(cfg["app"]["build_number"]),
                "summary": [f"TestFlight build {cfg['app']['build_number']} ({tf['build_id']}): "
                            "purchase, restore after reinstall, paywall in English and Japanese"]}
    failing = [c for c in r["checks"] if not c["passed"] and not c["id"].startswith("purchase-test")]
    if failing:
        raise RequestError("release is not ready: " + "; ".join(c["message"] for c in failing))
    return r


def request(project: Project, kind: str) -> dict:
    if kind not in KINDS:
        raise RequestError(f"kind must be one of {KINDS}")
    if kind == "publish" and single_release_approval(project):
        raise RequestError("this project uses one approval for submit + release (approval.single_release_approval); "
                           "the submit approval already covers publishing")
    s = subject(project, kind)
    if kind in ("submit", "publish"):
        from .release import write_readiness

        write_readiness(project)
    reply = f"承認 {DISPLAY[kind]}"
    pending = {"kind": kind, "digest": s["readiness_digest"], "requested_at": now_iso(), "reply": reply,
               "summary": s.get("summary", [])}
    write_json_atomic(_pending_path(project), pending)
    covers = " (and the release after Apple approves)" if kind == "submit" and single_release_approval(project) else ""
    return {"kind": kind, "digest": s["readiness_digest"][:12], "summary": s.get("summary", []),
            "ask_human": f"To approve {kind}{covers}, reply in this chat: 「{reply}」 (or 'approve {kind}'). "
                         f"To decline, reply 「却下 {DISPLAY[kind]}」 with what should change.",
            "mode": mode(project)}


def _normalise(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[。．.!！?？、,，「」『』\"'`]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _match(text: str, words: str, kind: str) -> bool:
    labels = "|".join(re.escape(lbl) for lbl in LABELS[kind])
    return bool(re.fullmatch(rf"{words} ?(?:{labels})|(?:{labels}) ?(?:を|の)? ?{words}", text))


def handle_reply(project: Project, prompt: str) -> Optional[str]:
    """Called by the UserPromptSubmit hook with the human's own message. Returns context for Claude."""
    pending = read_json(_pending_path(project))
    if not pending:
        return None
    text = _normalise(prompt)
    if len(text) > 40:
        return None
    kind = pending["kind"]
    approved = _match(text, APPROVE, kind)
    rejected = _match(text, REJECT, kind)
    if not approved and not rejected:
        others = [k for k in KINDS if k != kind and (_match(text, APPROVE, k) or _match(text, REJECT, k))]
        if others:
            return (f"[ios-app-factory] The pending approval request is for '{kind}', not '{others[0]}'. "
                    f"Nothing was recorded.")
        return None
    if mode(project) != "chat":
        return ("[ios-app-factory] This project requires terminal approvals (approval.mode = terminal); the chat reply "
                f"was not recorded. The human must run `app-factory approve {kind}` in their own terminal.")
    if rejected:
        _pending_path(project).unlink(missing_ok=True)
        return (f"[ios-app-factory] The human DECLINED the {kind} request. Ask what should change, revise, "
                f"and request approval again.")
    try:
        current = subject(project, kind)
    except RequestError as exc:
        return f"[ios-app-factory] Approval NOT recorded: {exc}"
    if current["readiness_digest"] != pending["digest"]:
        _pending_path(project).unlink(missing_ok=True)
        return ("[ios-app-factory] Approval NOT recorded: the content changed after the request was shown. "
                f"Run `app-factory approval request {kind}` again and show the new version.")
    note = f"chat reply: {prompt.strip()[:200]}"
    if kind == "purchase_test":
        cfg = project.config()
        write_json_atomic(project.reports / "purchase-test.json", {
            "tester": getpass.getuser(), "tested_at": now_iso(), "build_number": str(cfg["app"]["build_number"]),
            "environment": "testflight", "recorded_interactively": True, "channel": "chat", "note": note,
            "cases": [{"id": c, "result": "pass"} for c in ("purchase", "restore", "en_paywall", "ja_paywall")]})
    else:
        approval.write_record(project, kind, current, channel="chat", note=note)
    _pending_path(project).unlink(missing_ok=True)
    extra = ""
    if kind == "submit" and single_release_approval(project):
        extra = " This approval also covers releasing the version once Apple approves it."
    return f"[ios-app-factory] The human APPROVED '{kind}' in the chat; approval recorded.{extra} Continue the pipeline."


def status(project: Project) -> dict:
    pending = read_json(_pending_path(project))
    out = {"mode": mode(project), "single_release_approval": single_release_approval(project), "pending": pending}
    for kind in ("ux", "submit", "publish"):
        rec = read_json(approval.approval_path(project, kind))
        out[kind] = {"recorded": bool(rec), "channel": (rec or {}).get("channel"), "approved_at": (rec or {}).get("approved_at")}
    return out
