"""Screenshot gate: completeness, exact dimensions, no alpha, real captures, reproducibility."""
from __future__ import annotations

from ..hashing import sha256_file
from ..schemas_util import validate
from ..screenshots import compose
from ..screenshots.pipeline import current_recipe_digest
from . import gate
from .planning import ASO, DESIGN, MVP

MANIFEST = "factory/screenshots/manifest.json"


@gate("screenshots")
def screenshots_gate(ctx):
    manifest = ctx.load_json(MANIFEST)
    mvp, aso, design = ctx.load_json(MVP), ctx.load_json(ASO), ctx.load_json(DESIGN)
    if not (manifest and mvp and aso and design):
        return
    errors = validate(manifest, "screenshots_manifest")
    ctx.check("manifest.schema", not errors, "manifest valid", details=errors[:20] or None)
    if errors:
        return
    locales = ctx.config["app"]["locales"]
    devices = ctx.config["screenshots"]["devices"]
    scenes = [s["id"] for s in mvp["screenshot_scenes"]]
    index = {(i["locale"], i["device"], i["scene"]): i for i in manifest["items"]}
    expected = [(l, d, s) for l in locales for d in devices for s in scenes]
    missing = ["/".join(k) for k in expected if k not in index]
    ctx.check("coverage", not missing, f"{len(expected)} screenshots expected (locales x devices x scenes)",
              details=missing or None)
    ctx.check("count.per-set", 3 <= len(scenes) <= 10, f"{len(scenes)} screenshots per set (App Store allows 1..10)")

    bad = []
    for key in expected:
        item = index.get(key)
        if not item:
            continue
        final, raw = ctx.path(item["final"]), ctx.path(item["raw"])
        spec = compose.DEVICES[item["device"]]
        if not final.exists() or not raw.exists():
            bad.append(f"{'/'.join(key)}: file missing")
            continue
        info = compose.png_info(final)
        if [info["width"], info["height"]] != spec["size"]:
            bad.append(f"{'/'.join(key)}: {info['width']}x{info['height']} != {spec['size']}")
        if info["has_alpha"] or info["mode"] != "RGB":
            bad.append(f"{'/'.join(key)}: mode {info['mode']} (must be RGB without alpha)")
        if sha256_file(final) != item["final_sha256"] or sha256_file(raw) != item["raw_sha256"]:
            bad.append(f"{'/'.join(key)}: file changed after manifest was written")
        rinfo = compose.png_info(raw)
        if [rinfo["width"], rinfo["height"]] not in spec["raw_sizes"]:
            bad.append(f"{'/'.join(key)}: raw {rinfo['width']}x{rinfo['height']} is not a {item['device']} simulator capture")
        want = aso["locales"][key[0]]["screenshot_captions"].get(key[2])
        if item["caption"] != want:
            bad.append(f"{'/'.join(key)}: caption differs from aso.json")
    ctx.check("images.valid", not bad, "dimensions, colour mode, hashes, raw capture origin and captions", details=bad[:40] or None)

    try:
        recipe = current_recipe_digest(ctx.project)
        ctx.check("recipe.current", recipe == manifest["recipe_digest"],
                  "screenshots rendered from current design/captions/fonts (else run `app-factory screenshots render`)")
    except compose.ComposeError as exc:
        ctx.check("recipe.current", False, str(exc))
        return
    # Reproducibility: re-render one image per locale and compare bytes.
    for locale in locales:
        item = index.get((locale, devices[0], scenes[0]))
        if not item:
            continue
        data = compose.compose(ctx.path(item["raw"]), item["device"], locale, item["caption"],
                               design["screenshot_style"], ctx.config)
        ctx.check(f"reproducible.{locale}", compose.bytes_digest(data) == item["final_sha256"],
                  "re-rendering produces byte-identical output")
