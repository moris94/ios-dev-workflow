"""App icon rendering from a declarative, text-free vector spec (factory/artifacts/app_icon/icon.json).

The designer agent expresses the icon as layers of simple geometry in unit coordinates
(0..1 of the 1024px canvas). Rendering is deterministic (2x supersampled, then LANCZOS),
so the gate can re-render and compare bytes. Outputs the iOS 18+ appearance set:

* AppIcon-1024.png         – default (light), opaque RGB, no alpha (App Store requirement)
* AppIcon-1024-dark.png    – dark appearance
* AppIcon-1024-tinted.png  – tinted appearance (grayscale luminance on black)

A human-designed PNG can be supplied instead via ``source_png`` in icon.json.
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Dict, List, Optional

from .color import hex_to_rgb
from .jsonio import read_json, write_text_atomic
from .project import Project

ICON_DIR = "App/Resources/Assets.xcassets/AppIcon.appiconset"
APP_ICON = f"{ICON_DIR}/AppIcon-1024.png"
VARIANTS = {"light": "AppIcon-1024.png", "dark": "AppIcon-1024-dark.png", "tinted": "AppIcon-1024-tinted.png"}
SIZE = 1024
SS = 2  # supersampling factor


def contents_json() -> str:
    images = [{"filename": VARIANTS["light"], "idiom": "universal", "platform": "ios", "size": "1024x1024"}]
    for appearance in ("dark", "tinted"):
        images.append({"appearances": [{"appearance": "luminosity", "value": appearance}],
                       "filename": VARIANTS[appearance], "idiom": "universal", "platform": "ios", "size": "1024x1024"})
    return json.dumps({"images": images, "info": {"author": "xcode", "version": 1}}, indent=2) + "\n"


def _background(spec: dict, size: int):
    from PIL import Image

    colors = [hex_to_rgb(c) for c in spec["colors"]]
    if spec.get("type", "solid") == "solid" or len(colors) == 1:
        return Image.new("RGB", (size, size), colors[0])
    angle = math.radians(spec.get("angle", 180))
    dx, dy = math.sin(angle), -math.cos(angle)
    n = 64
    proj = [(x / (n - 1) - 0.5) * dx + (y / (n - 1) - 0.5) * dy for y in range(n) for x in range(n)]
    lo, hi = min(proj), max(proj)
    stops = len(colors) - 1
    px = []
    for v in proj:
        t = (v - lo) / (hi - lo) if hi > lo else 0.0
        seg = min(int(t * stops), stops - 1)
        local = t * stops - seg
        a, b = colors[seg], colors[seg + 1]
        px.append(tuple(int(round(a[k] + (b[k] - a[k]) * local)) for k in range(3)))
    small = Image.new("RGB", (n, n))
    small.putdata(px)
    return small.resize((size, size), Image.BILINEAR)


def _xy(p, s):
    return (p[0] * s, p[1] * s)


def _draw_layer(img, layer: dict, fill_hex: str, s: int):
    from PIL import Image, ImageDraw

    overlay = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(overlay)
    shape = layer["shape"]
    width = max(1, int(layer.get("width", 0.04) * s))
    if shape in ("circle", "ring"):
        cx, cy = _xy(layer["center"], s)
        r = layer["radius"] * s
        box = (cx - r, cy - r, cx + r, cy + r)
        if shape == "circle":
            d.ellipse(box, fill=255)
        else:
            d.ellipse(box, outline=255, width=width)
    elif shape == "ellipse":
        x0, y0, x1, y1 = layer["box"]
        d.ellipse((x0 * s, y0 * s, x1 * s, y1 * s), fill=255)
    elif shape in ("rect", "rounded_rect"):
        x0, y0, x1, y1 = layer["box"]
        d.rounded_rectangle((x0 * s, y0 * s, x1 * s, y1 * s), radius=layer.get("corner", 0 if shape == "rect" else 0.08) * s, fill=255)
    elif shape == "polygon":
        d.polygon([_xy(p, s) for p in layer["points"]], fill=255)
    elif shape == "line":
        d.line([_xy(p, s) for p in layer["points"]], fill=255, width=width, joint="curve")
        for p in (layer["points"][0], layer["points"][-1]):  # round caps
            x, y = _xy(p, s)
            d.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=255)
    elif shape == "arc":
        cx, cy = _xy(layer["center"], s)
        r = layer["radius"] * s
        d.arc((cx - r, cy - r, cx + r, cy + r), layer.get("start", 0), layer.get("end", 180), fill=255, width=width)
    else:
        raise ValueError(f"unsupported icon shape {shape}")
    alpha = overlay.point(lambda v: int(v * float(layer.get("opacity", 1.0))))
    img.paste(Image.new("RGB", img.size, hex_to_rgb(fill_hex)), (0, 0), alpha)


def render_variant(spec: dict, variant: str, project_root: Optional[Path] = None, size: int = SIZE) -> "Image.Image":
    from PIL import Image, ImageOps

    if spec.get("source_png"):
        src = Image.open(Path(project_root or ".") / spec["source_png"]).convert("RGB").resize((size, size), Image.LANCZOS)
        if variant == "light":
            return src
        if variant == "dark":
            return src if not spec.get("source_png_dark") else Image.open(Path(project_root or ".") / spec["source_png_dark"]).convert("RGB").resize((size, size), Image.LANCZOS)
        return ImageOps.grayscale(src).convert("RGB")
    s = size * SS
    dark = variant in ("dark", "tinted")
    bg_spec = spec.get("dark_background") if dark and spec.get("dark_background") else spec["background"]
    img = _background(bg_spec, s)
    if variant == "tinted":
        img = Image.new("RGB", (s, s), (0, 0, 0))
    for layer in spec.get("layers", []):
        fill = layer.get("dark_fill") if dark and layer.get("dark_fill") else layer["fill"]
        if variant == "tinted":
            r, g, b = hex_to_rgb(fill)
            lum = int(0.2126 * r + 0.7152 * g + 0.0722 * b)
            fill = "#{0:02X}{0:02X}{0:02X}".format(max(lum, 90))
        _draw_layer(img, layer, fill, s)
    return img.resize((size, size), Image.LANCZOS)


def png_bytes(img) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False, compress_level=6)
    return out.getvalue()


def expected_files(project: Project) -> Dict[str, bytes]:
    spec = read_json(project.artifact("app_icon", "icon.json"))
    if not spec:
        return {}
    files = {f"{ICON_DIR}/{name}": png_bytes(render_variant(spec, variant, project.root)) for variant, name in VARIANTS.items()}
    files[f"{ICON_DIR}/Contents.json"] = contents_json().encode("utf-8")
    return files


def render(project: Project) -> Dict[str, str]:
    out = {}
    for rel, data in expected_files(project).items():
        p = project.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.read_bytes() == data:
            out[rel] = "unchanged"
            continue
        if rel.endswith(".json"):
            write_text_atomic(p, data.decode("utf-8"))
        else:
            p.write_bytes(data)
        out[rel] = "updated"
    return out


def foreground_coverage(spec: dict, project_root: Path, size: int = 64) -> float:
    """Share of pixels the artwork changes vs. the bare background, at home-screen size."""
    if spec.get("source_png"):
        return 0.5
    from PIL import ImageChops

    full = render_variant(spec, "light", project_root, size)
    bare = render_variant({**spec, "layers": []}, "light", project_root, size)
    diff = ImageChops.difference(full, bare).convert("L").point(lambda v: 255 if v > 24 else 0)
    return round(sum(diff.histogram()[1:]) / (size * size), 3)


def used_colors(spec: dict) -> List[str]:
    colors = list(spec["background"]["colors"]) + list((spec.get("dark_background") or {}).get("colors", []))
    for layer in spec.get("layers", []):
        colors.append(layer["fill"])
        if layer.get("dark_fill"):
            colors.append(layer["dark_fill"])
    return [c.upper() for c in colors]


def preview_sheet(project: Project) -> Path:
    """Home-screen-size preview (60/120/180px, light & dark wallpaper) for visual review."""
    from PIL import Image, ImageDraw

    spec = read_json(project.artifact("app_icon", "icon.json"))
    sheet = Image.new("RGB", (900, 420), (242, 242, 247))
    ImageDraw.Draw(sheet).rectangle((0, 210, 900, 420), fill=(28, 28, 30))
    x = 30
    for size in (60, 120, 180):
        for row, variant in ((0, "light"), (1, "dark")):
            icon = render_variant(spec, variant, project.root, size)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.225), fill=255)
            sheet.paste(icon, (x, 15 + row * 210), mask)
        x += size + 60
    out = project.tmp / "icon-preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
