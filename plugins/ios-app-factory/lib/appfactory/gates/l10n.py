"""Localization gate: English default + complete Japanese."""
from __future__ import annotations

from ..hashing import expand_globs
from ..l10n import analyse_catalog, literal_keys_in_code
from . import gate

CATALOG = "App/Resources/Localizable.xcstrings"
INFOPLIST = "App/Resources/InfoPlist.xcstrings"


@gate("localization")
def localization_gate(ctx):
    root = ctx.project.root
    locales = ctx.config.get("app", {}).get("locales", [])
    ctx.check("config.locales", set(locales) >= {"en-US", "ja"} and ctx.config["app"].get("primary_locale") == "en-US",
              "config declares en-US (primary) and ja")
    main = analyse_catalog(root / CATALOG)
    ctx.check("catalog.complete", not main["errors"], f"{len(main['keys'])} keys fully translated (en, ja)",
              details=main["errors"][:40] or None)
    ctx.warn("catalog.hygiene", not main["warnings"], "no stale/untranslated-looking entries", details=main["warnings"][:40] or None)
    ctx.check("catalog.non-trivial", len(main["keys"]) >= 10, f"{len(main['keys'])} localized strings (>= 10)")

    info = analyse_catalog(root / INFOPLIST)
    ctx.check("infoplist.complete", not info["errors"], "InfoPlist.xcstrings translated", details=info["errors"] or None)
    ctx.check("infoplist.display-name", "CFBundleDisplayName" in info["keys"], "CFBundleDisplayName localized")

    sources = {p: p.read_text(encoding="utf-8", errors="replace") for p in expand_globs(root, ["App/Sources/**/*.swift"])}
    used = literal_keys_in_code(sources)
    missing = sorted(k for k in used if k not in set(main["keys"]))
    ctx.check("code.keys-in-catalog", not missing, f"{len(used)} literal UI strings in code all present in catalog",
              details=missing[:40] or None)

    yml = (root / "project.yml").read_text(encoding="utf-8") if (root / "project.yml").exists() else ""
    ctx.check("project.development-language", "developmentLanguage: en" in yml, "project.yml: developmentLanguage en")
    import plistlib

    plist_path = root / "App/Info.plist"
    info_plist = plistlib.loads(plist_path.read_bytes()) if plist_path.exists() else {}
    ctx.check("infoplist.localizations", info_plist.get("CFBundleDevelopmentRegion") == "en" and
              {"en", "ja"} <= set(info_plist.get("CFBundleLocalizations", [])),
              "Info.plist: development region en, CFBundleLocalizations includes en and ja")
