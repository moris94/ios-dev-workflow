"""Gates for the app icon and the combined support / privacy-policy page."""
from __future__ import annotations

import os
import re

from .. import icon as icon_mod
from .. import support_page as sp
from ..codegen import PLACEHOLDER_HOST, app_links
from ..color import contrast, delta_e
from ..schemas_util import validate
from . import gate
from .planning import ASO, CHARTER, DESIGN, MVP

ICON = "factory/artifacts/app_icon/icon.json"


def _design_colors(design: dict) -> list:
    cols = []
    for mode in ("light", "dark"):
        cols += list(design["color"][mode].values())
    shot = design.get("screenshot_style", {})
    cols += shot.get("background", {}).get("colors", [])
    cols += [shot.get(k) for k in ("caption_color", "frame_color", "subcaption_color") if shot.get(k)]
    return [c.upper() for c in cols]


@gate("app_icon")
def app_icon_gate(ctx):
    spec = ctx.load_artifact(ICON, "app_icon")
    ctx.require_text("factory/artifacts/app_icon/icon.md", 200)
    design, charter, aso = ctx.load_json(DESIGN), ctx.load_json(CHARTER), ctx.load_json(ASO)
    if not (spec and design and charter and aso):
        return
    # --- traceability: charter, design concept, ASO ---------------------------------
    pids = {p["id"] for p in charter["principles"]}
    bad = [p for p in spec["concept"]["derived_from_principles"] if p not in pids]
    ctx.check("concept.charter", not bad, "icon concept traces to charter principles", details=bad or None)
    ctx.check("concept.design", spec["concept"]["design_concept"] == design["concept"]["name"],
              f"icon follows the design concept '{design['concept']['name']}'")
    names = [aso["locales"][loc]["name"] for loc in aso["locales"]]
    ctx.check("aso.name", any(spec["app_name"].lower() in n.lower() for n in names),
              "icon app_name matches the App Store name (aso.json)")
    vocab = set()
    for loc in aso["locales"].values():
        vocab |= {k.strip().lower() for k in loc["keywords"].split(",")}
        vocab |= {w.lower() for w in re.split(r"[\s:\-–—]+", loc["name"] + " " + loc["subtitle"]) if w}
    reflected = [k for k in spec["aso"]["keywords_reflected"] if k.lower() not in vocab]
    ctx.check("aso.keywords", not reflected, "reflected keywords come from the ASO name/subtitle/keywords",
              details=reflected or None)
    ctx.check("references.hig", any(r["type"] == "guideline" and "apple.com" in r["source"] for r in spec["references"]),
              "Apple HIG (App icons) consulted")

    if not spec.get("source_png"):
        # --- palette discipline ------------------------------------------------------
        palette = _design_colors(design) + [e["hex"].upper() for e in spec.get("extra_colors", [])]
        off = sorted({c for c in icon_mod.used_colors(spec) if min(delta_e(c, p) for p in palette) > 8})
        ctx.check("palette.from-design", not off, "icon colours come from the design palette (or extra_colors with a reason)",
                  details=off or None)
        # --- legibility at home-screen size -----------------------------------------
        glyphs = [l for l in spec["layers"] if l["role"] == "glyph"]
        ctx.check("glyph.present", bool(glyphs), "at least one 'glyph' layer (the recognisable motif)")
        if glyphs:
            g = glyphs[0]
            light_ratio = contrast(g["fill"], spec["background"]["colors"][0])
            dark_bg = (spec.get("dark_background") or spec["background"])["colors"][0]
            dark_ratio = contrast(g.get("dark_fill", g["fill"]), dark_bg)
            ctx.check("glyph.contrast", light_ratio >= 3.0 and dark_ratio >= 3.0,
                      f"glyph contrast light {light_ratio}:1 / dark {dark_ratio}:1 (>= 3:1)")
        ctx.check("layers.simple", len(spec["layers"]) <= 12, f"{len(spec['layers'])} layers (<= 12 keeps it legible small)")
        cov = icon_mod.foreground_coverage(spec, ctx.project.root)
        ctx.check("legibility.coverage", 0.12 <= cov <= 0.75, f"artwork covers {cov:.0%} of the icon at 64px (12–75%)")

    # --- rendered asset set ------------------------------------------------------------
    expected = icon_mod.expected_files(ctx.project)
    stale = [rel for rel, data in expected.items() if not ctx.path(rel).exists() or ctx.path(rel).read_bytes() != data]
    ctx.check("assets.current", not stale, "AppIcon.appiconset matches icon.json (run `app-factory icon render`)",
              details=stale or None)
    main = ctx.path(icon_mod.APP_ICON)
    if main.exists():
        from ..screenshots.compose import png_info

        info = png_info(main)
        ctx.check("assets.app-store-format", (info["width"], info["height"]) == (1024, 1024) and not info["has_alpha"]
                  and info["mode"] == "RGB", "1024x1024 RGB without alpha")


@gate("support_page")
def support_page_gate(ctx):
    pub = ctx.load_json("factory/artifacts/support_page/publication.json")
    if not pub:
        return
    errors = validate(pub, "support_publication")
    ctx.check("publication.schema", not errors, "publication record valid", details=errors or None)
    links = app_links(ctx.config)
    if pub["provider"] == "user":
        ok = PLACEHOLDER_HOST not in links["support"] + links["privacyPolicy"]
        ctx.check("links.user-provided", ok and pub["url"] == links["support"],
                  "human-provided support/privacy URLs are configured")
        return

    page = ctx.path("factory/artifacts/support_page/page.md")
    if not page.exists():
        ctx.check("page.exists", False, "factory/artifacts/support_page/page.md missing (app-factory support-page draft)")
        return
    text = page.read_text(encoding="utf-8")
    for heading in ("## Support", "## Privacy Policy", "## サポート", "## プライバシーポリシー"):
        ctx.check(f"page.section:{heading[3:]}", heading in text, f"section '{heading}' present")
    ctx.check("page.email-placeholder", text.count(sp.PLACEHOLDER) >= 2,
              f"support e-mail is a {sp.PLACEHOLDER} placeholder (filled from ${sp.EMAIL_ENV} at publish time)")
    ctx.check("page.no-literal-email", not sp.EMAIL_RE.search(text.replace(sp.PLACEHOLDER, "")),
              "no e-mail address hard-coded in the committed page")
    mvp = ctx.load_json(MVP) or {}
    if mvp.get("monetization", {}).get("products"):
        ctx.check("page.iap", "Restore Purchases" in text and "購入を復元" in text,
                  "explains purchases and Restore Purchases in both languages")
    for t in mvp.get("privacy", {}).get("data_types", []):
        ctx.check(f"page.data-type:{t}", t in text, f"privacy policy names collected data type '{t}'")
    ctx.check("page.ja", bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text)), "Japanese section written in Japanese")

    ctx.check("publication.url", pub["url"].startswith("https://") and PLACEHOLDER_HOST not in pub["url"], "public https URL")
    ctx.check("publication.current", pub.get("content_digest") == sp.content_digest(ctx.project),
              "published content == current page.md (re-publish after editing)")
    ctx.check("links.point-to-page", links["support"] == pub["url"] and links["privacyPolicy"] == pub["url"],
              "config app.links.support and privacy_policy both point to the published page")
    if pub.get("verified"):
        ctx.check("publication.reachable", pub.get("http_status") == 200, f"page answered HTTP {pub.get('http_status')}")
    else:
        ctx.warn("publication.reachable", False, "URL reachability not verified")
    if os.environ.get(sp.EMAIL_ENV):
        ctx.warn("publication.email-current", sp.email_fingerprint(os.environ[sp.EMAIL_ENV].strip()) == pub.get("email_fingerprint"),
                 f"${sp.EMAIL_ENV} differs from the published address — re-publish the page")
