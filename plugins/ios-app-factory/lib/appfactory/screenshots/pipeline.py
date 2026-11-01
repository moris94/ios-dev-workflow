"""Collect raw UI-test captures and render the final store screenshots."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Dict, List

from ..hashing import sha256_file
from ..jsonio import read_json, write_json_atomic
from ..project import Project
from ..timeutil import now_iso
from . import compose

def _scene_for(name: str, scenes: List[str]):
    """Match `scene-<id>` in a capture/attachment name. Xcode exports attachments as
    `<name>_<index>_<UUID>.png`, so the id must be followed by a non-lowercase char or the end."""
    best = None
    for sid in scenes:
        if re.search(r"scene[-_]" + re.escape(sid) + r"(?![a-z])", name) and (best is None or len(sid) > len(best)):
            best = sid
    return best


def collect(project: Project, source_dir: Path, locale: str, device: str, scenes: List[str]) -> Dict[str, str]:
    """Copy captures named ``scene-<id>*.png`` (from TEST_RUNNER_FACTORY_SCREENSHOT_DIR
    or ``xcresulttool export attachments``) into factory/screenshots/raw/<locale>/<device>/."""
    source_dir = Path(source_dir)
    manifest = read_json(source_dir / "manifest.json")
    candidates: List[tuple] = []
    if isinstance(manifest, list):  # xcresulttool export attachments manifest
        for test in manifest:
            for att in test.get("attachments", []):
                name = att.get("suggestedHumanReadableName", "") + " " + att.get("exportedFileName", "")
                sid = _scene_for(name, scenes)
                if sid and att.get("exportedFileName", "").lower().endswith(".png"):
                    candidates.append((sid, source_dir / att["exportedFileName"]))
    for p in sorted(source_dir.glob("*.png")):
        sid = _scene_for(p.name, scenes)
        if sid:
            candidates.append((sid, p))
    dest = project.screenshots_dir / "raw" / locale / device
    dest.mkdir(parents=True, exist_ok=True)
    collected = {}
    for scene, path in candidates:
        if scene in scenes and scene not in collected and path.exists():
            shutil.copyfile(path, dest / f"{scene}.png")
            collected[scene] = project.rel(dest / f"{scene}.png")
    missing = [s for s in scenes if s not in collected]
    if missing:
        raise compose.ComposeError(f"captures missing for {locale}/{device}: {missing} (looked in {source_dir})")
    return collected


def _inputs(project: Project):
    design = read_json(project.artifact("design", "design.json"))
    aso = read_json(project.artifact("aso", "aso.json"))
    mvp = read_json(project.artifact("mvp", "mvp.json"))
    if not (design and aso and mvp):
        raise compose.ComposeError("design.json, aso.json and mvp.json are required before rendering screenshots")
    cfg = project.config()
    locales = cfg["app"]["locales"]
    devices = cfg["screenshots"]["devices"]
    captions = {loc: aso["locales"][loc]["screenshot_captions"] for loc in locales}
    fonts = {loc: compose.resolve_font(loc, cfg) for loc in locales}
    return design["screenshot_style"], captions, mvp, cfg, locales, devices, fonts


def current_recipe_digest(project: Project) -> str:
    style, captions, _, _, _, devices, fonts = _inputs(project)
    return compose.recipe_digest(style, captions, devices, fonts)


def render_all(project: Project) -> dict:
    style, captions, mvp, cfg, locales, devices, fonts = _inputs(project)
    scenes = compose.scene_order(mvp)
    items = []
    for locale in locales:
        for device in devices:
            for order, scene in enumerate(scenes, start=1):
                raw = compose.find_raw(project.root, locale, device, scene)
                if raw is None:
                    raise compose.ComposeError(f"raw capture missing: factory/screenshots/raw/{locale}/{device}/{scene}.png "
                                               "(run scripts/xcode/capture_screenshots.sh)")
                caption = captions[locale][scene]
                data = compose.compose(raw, device, locale, caption, style, cfg)
                final = project.screenshots_dir / "final" / locale / device / f"{order:02d}_{scene}.png"
                final.parent.mkdir(parents=True, exist_ok=True)
                if not final.exists() or final.read_bytes() != data:
                    final.write_bytes(data)
                w, h = compose.DEVICES[device]["size"]
                items.append({
                    "locale": locale, "device": device, "scene": scene, "order": order,
                    "display_type": compose.DEVICES[device]["display_type"],
                    "raw": project.rel(raw), "final": project.rel(final),
                    "raw_sha256": sha256_file(raw), "final_sha256": compose.bytes_digest(data),
                    "width": w, "height": h, "caption": caption,
                })
    manifest = {
        "generated_at": now_iso(),
        "composer_version": compose.COMPOSER_VERSION,
        "recipe_digest": compose.recipe_digest(style, captions, devices, fonts),
        "fonts": {loc: Path(p).name for loc, p in fonts.items()},
        "items": items,
    }
    write_json_atomic(project.screenshots_dir / "manifest.json", manifest)
    return manifest
