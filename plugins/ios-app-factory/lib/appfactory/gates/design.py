"""Design concept gate: accessibility contrast, anti-generic heuristics, provenance."""
from __future__ import annotations

from ..color import contrast, nearest_cliche, nearest_cliche_background
from . import gate
from .planning import CHARTER, DESIGN


@gate("design")
def design_gate(ctx):
    data = ctx.load_artifact(DESIGN, "design")
    ctx.require_text("factory/artifacts/design/design.md", 300)
    charter = ctx.load_json(CHARTER)
    if not data or not charter:
        return
    pids = {p["id"] for p in charter["principles"]}
    unknown = [p for p in data["concept"]["derived_from_principles"] if p not in pids]
    ctx.check("concept.traces-to-charter", not unknown, "concept derives from charter principles", details=unknown or None)

    refs = data["references"]
    ctx.check("references.skill", any(r["type"] == "skill" for r in refs),
              "at least one design Skill consulted (e.g. frontend-design / installed design skills)")
    ctx.check("references.hig", any(r["type"] == "guideline" and "apple.com" in r["source"] for r in refs),
              "Apple Human Interface Guidelines consulted (developer.apple.com/design)")

    for mode in ("light", "dark"):
        pal = data["color"][mode]
        pairs = {
            "text_primary/background": (pal["text_primary"], pal["background"], 4.5),
            "text_primary/surface": (pal["text_primary"], pal["surface"], 4.5),
            "text_secondary/background": (pal["text_secondary"], pal["background"], 4.5),
            "accent_text/accent": (pal["accent_text"], pal["accent"], 4.5),
            "accent/background (UI component)": (pal["accent"], pal["background"], 3.0),
        }
        for name, (fg, bg, minimum) in pairs.items():
            ratio = contrast(fg, bg)
            ctx.check(f"contrast.{mode}.{name}", ratio >= minimum, f"{ratio}:1 (WCAG >= {minimum}:1)")
    light_bg = data["color"]["light"]["background"].upper()
    dark_bg = data["color"]["dark"]["background"].upper()
    ctx.check("dark-mode.distinct", light_bg != dark_bg, "dark mode has its own palette")

    accent = data["color"]["light"]["accent"]
    name, ref, de = nearest_cliche(accent)
    ctx.check("anti-generic.accent", de >= 12,
              f"accent {accent} vs cliché '{name}' {ref}: ΔE={de} (needs >= 12 to avoid template look)")
    bname, bref, bde = nearest_cliche_background(data["color"]["light"]["background"])
    ctx.warn("anti-generic.background", bde >= 5,
             f"light background vs cliché '{bname}' {bref}: ΔE={bde} — justify it in anti_generic.rationale if intentional")
    ctx.check("anti-generic.signature", len(data["anti_generic"]["signature_elements"]) >= 2,
              "at least two signature visual elements")
    shot = data["screenshot_style"]
    bg0 = shot["background"]["colors"][0]
    ratio = contrast(shot["caption_color"], bg0)
    ctx.check("screenshot.caption-contrast", ratio >= 3.0, f"caption on screenshot background {ratio}:1 (>= 3:1 large text)")
    if shot["background"]["type"] == "gradient":
        ctx.check("screenshot.gradient-colors", len(shot["background"]["colors"]) >= 2, "gradient has >= 2 colours")
        worst = min(contrast(shot["caption_color"], c) for c in shot["background"]["colors"])
        ctx.check("screenshot.caption-contrast-all-stops", worst >= 3.0, f"caption contrast on every gradient stop (min {worst}:1)")
