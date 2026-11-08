"""Combined Support + Privacy Policy page (en / ja).

When ``config.app.links.support`` / ``privacy_policy`` are not specified, the factory
generates ONE public page that serves as both the App Store support URL and the
privacy policy URL, publishes it (Notion via MCP, or manually), and writes the
published URL back into both links.

The support e-mail address comes only from the environment (``FACTORY_SUPPORT_EMAIL``).
The committed draft keeps the ``{{SUPPORT_EMAIL}}`` placeholder; the rendered page
with the real address is written to ``.factory-tmp/`` (gitignored) for publishing.
"""
from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from typing import Optional

from .codegen import PLACEHOLDER_HOST
from .hashing import sha256_bytes
from .jsonio import read_json, write_json_atomic, write_text_atomic
from .project import Project
from .timeutil import now_iso

EMAIL_ENV = "FACTORY_SUPPORT_EMAIL"
PLACEHOLDER = "{{SUPPORT_EMAIL}}"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PAGE = "page.md"
PUBLICATION = "publication.json"


class SupportPageError(RuntimeError):
    pass


def links_user_specified(project: Project) -> bool:
    """True when the human configured their own support/privacy URLs (so nothing is generated)."""
    links = project.config().get("app", {}).get("links") or {}
    urls = [links.get("support"), links.get("privacy_policy")]
    if not all(urls) or any(PLACEHOLDER_HOST in u for u in urls):
        return False
    pub = read_json(project.artifact("support_page", PUBLICATION)) or {}
    return pub.get("provider") in (None, "user")


def support_email() -> str:
    value = os.environ.get(EMAIL_ENV, "").strip()
    if not value:
        raise SupportPageError(f"set {EMAIL_ENV} to the public support e-mail address (it is embedded in the page)")
    if not EMAIL_RE.fullmatch(value):
        raise SupportPageError(f"{EMAIL_ENV} is not a valid e-mail address")
    return value


def email_fingerprint(email: str) -> str:
    return sha256_bytes(email.lower().encode("utf-8"))


def _data_lines(mvp: dict, ja: bool) -> str:
    priv = mvp.get("privacy", {})
    if not priv.get("collects_data") and not priv.get("data_types"):
        return ("- 本アプリは個人情報を収集しません。作成したデータはお使いの端末内にのみ保存されます。"
                if ja else "- The app does not collect personal data. Everything you create is stored only on your device.")
    types = ", ".join(priv.get("data_types", []))
    return (f"- 本アプリが扱うデータ: {types}。目的はアプリの機能提供のみです。"
            if ja else f"- Data the app handles: {types}. It is used only to provide the app's features.")


def draft(project: Project) -> str:
    cfg = project.config()
    mvp = read_json(project.artifact("mvp", "mvp.json")) or {}
    name = cfg["app"]["name"]
    priv = mvp.get("privacy", {})
    has_iap = bool(mvp.get("monetization", {}).get("products"))
    tracking = priv.get("tracking", False)
    today = now_iso()[:10]
    iap_en = ("\n### In-App Purchases\nPurchases are processed by Apple. We never receive your payment details. "
              "To restore a purchase, open Settings in the app and tap **Restore Purchases**. "
              "Refunds are handled by Apple at https://reportaproblem.apple.com.\n") if has_iap else ""
    iap_ja = ("\n### アプリ内課金\n購入の決済は Apple が行い、開発者が支払い情報を受け取ることはありません。"
              "購入の復元は、アプリの「設定」から「購入を復元」をタップしてください。"
              "返金は Apple（https://reportaproblem.apple.com）で受け付けています。\n") if has_iap else ""
    track_en = "We do not track you across apps or websites, and the app contains no third-party advertising or analytics SDKs." \
        if not tracking else "See the App Store privacy label for tracking details."
    track_ja = "他社のアプリやウェブサイトをまたいだトラッキングは行わず、第三者の広告・解析 SDK も含みません。" \
        if not tracking else "トラッキングの詳細は App Store のプライバシー表示をご覧ください。"
    text = f"""# {name} — Support & Privacy Policy / サポート・プライバシーポリシー

[English](#english) · [日本語](#japanese)

<a id="english"></a>
## Support

Questions, bug reports and feature requests: **{PLACEHOLDER}**
We usually reply within a few business days. Please include your iOS version and the app version (Settings → Version).
{iap_en}
## Privacy Policy

_Last updated: {today}_

{_data_lines(mvp, ja=False)}
- {track_en}
- If you contact us by e-mail, we use your address and message only to reply, and delete them when no longer needed.
- Deleting the app removes all of its data from your device.
- The app is not directed at children under 13 and does not knowingly collect their data.
- We will update this page if this policy changes. Contact: **{PLACEHOLDER}**

<a id="japanese"></a>
## サポート

ご質問・不具合のご報告・ご要望は **{PLACEHOLDER}** までお寄せください。
通常、数営業日以内にお返事します。iOS のバージョンとアプリのバージョン（設定 → バージョン）を添えてください。
{iap_ja}
## プライバシーポリシー

_最終更新日: {today}_

{_data_lines(mvp, ja=True)}
- {track_ja}
- メールでお問い合わせいただいた場合、メールアドレスと内容は返信のためにのみ使用し、不要になった時点で削除します。
- アプリを削除すると、端末内のアプリのデータはすべて削除されます。
- 本アプリは 13 歳未満のお子様を対象としておらず、その情報を意図的に収集することはありません。
- 本ポリシーを変更する場合はこのページでお知らせします。連絡先: **{PLACEHOLDER}**
"""
    write_text_atomic(project.artifact("support_page", PAGE), text)
    return text


def render(project: Project) -> dict:
    """Substitute the e-mail from the environment; output stays in .factory-tmp (not committed)."""
    path = project.artifact("support_page", PAGE)
    if not path.exists():
        raise SupportPageError("run `app-factory support-page draft` first")
    email = support_email()
    text = path.read_text(encoding="utf-8").replace(PLACEHOLDER, email)
    out = project.tmp / "support-page" / "page.rendered.md"
    write_text_atomic(out, text)
    title = text.splitlines()[0].lstrip("# ").strip()
    return {"title": title, "rendered": project.rel(out), "content_digest": content_digest(project)}


def content_digest(project: Project) -> str:
    return sha256_bytes(project.artifact("support_page", PAGE).read_bytes())


def check_url(url: str, timeout: int = 15) -> Optional[int]:
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ios-app-factory/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only (validated)
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


def record(project: Project, url: str, provider: str, verify: bool = True, notion_page_id: Optional[str] = None) -> dict:
    if not url.startswith("https://") or PLACEHOLDER_HOST in url:
        raise SupportPageError("the published URL must be a public https:// URL")
    if provider not in ("notion", "manual"):
        raise SupportPageError("provider must be notion or manual")
    email = support_email()
    status = check_url(url) if verify else None
    pub = {"provider": provider, "url": url, "published_at": now_iso(), "content_digest": content_digest(project),
           "email_fingerprint": email_fingerprint(email), "http_status": status, "verified": verify}
    if notion_page_id:
        pub["notion_page_id"] = notion_page_id
    write_json_atomic(project.artifact("support_page", PUBLICATION), pub)
    cfg = project.config()
    links = cfg["app"].setdefault("links", {})
    links["support"] = url
    links["privacy_policy"] = url
    write_json_atomic(project.config_path, cfg)
    return pub


def use_existing(project: Project) -> dict:
    """The human supplied their own support/privacy URLs: record that, generate nothing."""
    links = project.config().get("app", {}).get("links") or {}
    sup, priv = links.get("support"), links.get("privacy_policy")
    if not sup or not priv or PLACEHOLDER_HOST in sup + priv:
        raise SupportPageError("config app.links.support and privacy_policy must both be set to use existing pages")
    pub = {"provider": "user", "url": sup, "privacy_url": priv, "published_at": now_iso(), "content_digest": None,
           "email_fingerprint": None, "http_status": None, "verified": False}
    write_json_atomic(project.artifact("support_page", PUBLICATION), pub)
    return pub
