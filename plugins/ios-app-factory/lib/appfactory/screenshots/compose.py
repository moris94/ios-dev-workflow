"""Reproducible App Store screenshot composition.

Input:  raw simulator captures (from XCUITest) + design.json screenshot_style
        + aso.json captions.
Output: exact-size RGB PNGs (no alpha – App Store Connect rejects alpha),
        byte-for-byte deterministic for identical inputs and fonts.
"""
from __future__ import annotations

import io
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..color import hex_to_rgb
from ..hashing import sha256_bytes, sha256_file, sha256_json
from ..jsonio import read_json

COMPOSER_VERSION = "1.0.0"
DEVICES = read_json(Path(__file__).with_name("devices.json"))

FONT_CANDIDATES = {
    "latin": [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ],
    "ja": [
        "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    ],
}


class ComposeError(RuntimeError):
    pass


def resolve_font(locale: str, config: dict) -> str:
    fonts = (config.get("screenshots") or {}).get("fonts") or {}
    explicit = fonts.get(locale) or os.environ.get(f"FACTORY_FONT_{locale.replace('-', '_').upper()}")
    if explicit:
        if not Path(explicit).exists():
            raise ComposeError(f"configured font for {locale} not found: {explicit}")
        return explicit
    for cand in FONT_CANDIDATES["ja" if locale.startswith("ja") else "latin"]:
        if Path(cand).exists():
            return cand
    raise ComposeError(f"no font found for {locale}; set screenshots.fonts.{locale} in factory/config.json")


@lru_cache(maxsize=64)
def _font(path: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(path, size)


def missing_glyphs(font_path: str, text: str) -> List[str]:
    """Characters the font cannot render (would show as tofu boxes)."""
    from PIL import Image, ImageDraw

    font = _font(font_path, 48)

    def render(ch: str) -> bytes:
        img = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(img).text((8, 8), ch, font=font, fill=255)
        return img.tobytes()

    notdef = render("\U0010FFFD")
    missing = []
    for ch in sorted(set(text)):
        if ch.isspace():
            continue
        if render(ch) == notdef:
            missing.append(ch)
    return missing


def _wrap(draw, text: str, font, max_width: int, cjk: bool) -> List[str]:
    lines: List[str] = []
    for paragraph in text.split("\n"):
        tokens = list(paragraph) if cjk else paragraph.split(" ")
        sep = "" if cjk else " "
        line = ""
        for tok in tokens:
            trial = (line + sep + tok) if line else tok
            if draw.textlength(trial, font=font) <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = tok
        if line:
            lines.append(line)
    # Kinsoku: never start a line with closing punctuation in Japanese.
    if cjk:
        for i in range(1, len(lines)):
            while lines[i] and lines[i][0] in "、。，．・ー！？）」』】":
                lines[i - 1] += lines[i][0]
                lines[i] = lines[i][1:]
        lines = [line for line in lines if line]
    return lines


def _fit(draw, text: str, font_path: str, start: int, max_width: int, max_lines: int, cjk: bool):
    size = start
    while size > 12:
        font = _font(font_path, size)
        lines = _wrap(draw, text, font, max_width, cjk)
        if len(lines) <= max_lines and all(draw.textlength(line, font=font) <= max_width for line in lines):
            return font, lines, size
        size -= 2
    raise ComposeError(f"caption does not fit: {text!r}")


def _background(size: Tuple[int, int], style: dict):
    from PIL import Image, ImageDraw

    w, h = size
    bg = style["background"]
    colors = [hex_to_rgb(c) for c in bg["colors"]]
    if bg["type"] == "solid" or len(colors) == 1:
        img = Image.new("RGB", size, colors[0])
    else:
        angle = math.radians(bg.get("angle", 160))
        dx, dy = math.sin(angle), -math.cos(angle)
        # Evaluate the linear gradient on a coarse grid, then upsample (smooth, fast, deterministic).
        sw, sh = max(2, w // 8), max(2, h // 8)
        proj = [(x / (sw - 1) - 0.5) * dx * w + (y / (sh - 1) - 0.5) * dy * h for y in range(sh) for x in range(sw)]
        lo, hi = min(proj), max(proj)
        stops = len(colors) - 1
        small = Image.new("RGB", (sw, sh))
        pixels = []
        for v in proj:
            t = (v - lo) / (hi - lo) if hi > lo else 0.0
            seg = min(int(t * stops), stops - 1)
            local = t * stops - seg
            a, b = colors[seg], colors[seg + 1]
            pixels.append(tuple(int(round(a[k] + (b[k] - a[k]) * local)) for k in range(3)))
        small.putdata(pixels)
        img = small.resize((w, h), Image.BILINEAR)
    pattern = bg.get("pattern", "none")
    if pattern and pattern != "none":
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        ink = (255, 255, 255, 22)
        step = max(24, w // 22)
        if pattern == "dots":
            r = max(2, step // 10)
            for y in range(step // 2, h, step):
                for x in range(step // 2, w, step):
                    d.ellipse((x - r, y - r, x + r, y + r), fill=ink)
        elif pattern == "grid":
            for x in range(0, w, step):
                d.line((x, 0, x, h), fill=ink, width=2)
            for y in range(0, h, step):
                d.line((0, y, w, y), fill=ink, width=2)
        elif pattern == "diagonal":
            for x in range(-h, w, step):
                d.line((x, 0, x + h, h), fill=ink, width=3)
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img


def _rounded_mask(size: Tuple[int, int], radius: int):
    from PIL import Image, ImageDraw

    scale = 3  # supersample for smooth, deterministic edges
    big = Image.new("L", (size[0] * scale, size[1] * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, big.size[0] - 1, big.size[1] - 1), radius=radius * scale, fill=255)
    return big.resize(size, Image.LANCZOS)


def compose(raw_path: Path, device: str, locale: str, caption: dict, style: dict, config: dict) -> bytes:
    from PIL import Image, ImageDraw, ImageFilter

    spec = DEVICES[device]
    W, H = spec["size"]
    font_path = resolve_font(locale, config)
    text = caption["headline"] + caption.get("subline", "")
    missing = missing_glyphs(font_path, text)
    if missing:
        raise ComposeError(f"font {font_path} lacks glyphs for {locale}: {''.join(missing)!r}")
    cjk = locale.startswith("ja")
    canvas = _background((W, H), style)
    draw = ImageDraw.Draw(canvas)

    margin = int(W * 0.08)
    caption_top = int(H * 0.055)
    head_font, head_lines, head_size = _fit(draw, caption["headline"], font_path, int(W * (0.085 if cjk else 0.088)),
                                            W - 2 * margin, 2, cjk)
    color = hex_to_rgb(style["caption_color"])
    sub_color = hex_to_rgb(style.get("subcaption_color", style["caption_color"]))
    line_h = int(head_size * 1.22)
    text_block: List[Tuple[str, object, Tuple[int, int, int], int]] = [(l, head_font, color, line_h) for l in head_lines]
    if caption.get("subline"):
        sub_font, sub_lines, sub_size = _fit(draw, caption["subline"], font_path, int(W * 0.045), W - 2 * margin, 2, cjk)
        text_block += [(l, sub_font, sub_color, int(sub_size * 1.35)) for l in sub_lines]
    block_h = sum(t[3] for t in text_block) + (int(head_size * 0.35) if caption.get("subline") else 0)

    raw = Image.open(raw_path).convert("RGB")
    device_top = caption_top + block_h + int(H * 0.04)
    if style.get("layout") == "caption_bottom":
        device_top = int(H * 0.05)
    avail_h = (H - device_top - int(H * 0.0)) if style.get("layout") != "caption_bottom" else (H - block_h - int(H * 0.16))
    scale = min((W * 0.84) / raw.width, avail_h / raw.height)
    sw, sh = int(raw.width * scale), int(raw.height * scale)
    shot = raw.resize((sw, sh), Image.LANCZOS)
    radius = int(sw * spec.get("screen_corner_ratio", 0.08))
    x0 = (W - sw) // 2
    y0 = device_top

    if style.get("device_frame", True):
        bezel = max(10, int(sw * 0.028))
        fw, fh = sw + 2 * bezel, sh + 2 * bezel
        q = 4  # blur at quarter resolution, then upsample
        shadow = Image.new("L", (W // q, H // q), 0)
        ImageDraw.Draw(shadow).rounded_rectangle(((x0 - bezel) // q, (y0 - bezel + 24) // q,
                                                  (x0 - bezel + fw) // q, (y0 - bezel + fh + 24) // q),
                                                 radius=(radius + bezel) // q, fill=110)
        shadow = shadow.filter(ImageFilter.GaussianBlur(36 // q)).resize((W, H), Image.BILINEAR)
        canvas.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), shadow)
        frame_col = hex_to_rgb(style.get("frame_color", "#111111"))
        canvas.paste(Image.new("RGB", (fw, fh), frame_col), (x0 - bezel, y0 - bezel), _rounded_mask((fw, fh), radius + bezel))
    canvas.paste(shot, (x0, y0), _rounded_mask((sw, sh), radius))

    draw = ImageDraw.Draw(canvas)
    y = caption_top if style.get("layout") != "caption_bottom" else H - block_h - int(H * 0.06)
    for i, (line, font, col, lh) in enumerate(text_block):
        if i == len(head_lines) and caption.get("subline"):
            y += int(head_size * 0.35)
        tw = draw.textlength(line, font=font)
        draw.text(((W - tw) / 2, y), line, font=font, fill=col)
        y += lh

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=False, compress_level=6)
    return out.getvalue()


def recipe_digest(style: dict, captions: Dict[str, dict], devices: List[str], fonts: Dict[str, str]) -> str:
    return sha256_json({
        "composer": COMPOSER_VERSION,
        "style": style,
        "captions": captions,
        "devices": {d: DEVICES[d] for d in devices},
        "fonts": {loc: sha256_file(Path(p)) for loc, p in sorted(fonts.items())},
    })


def png_info(path: Path) -> dict:
    from PIL import Image

    with Image.open(path) as im:
        return {"width": im.width, "height": im.height, "mode": im.mode,
                "has_alpha": im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info}


def bytes_digest(data: bytes) -> str:
    return sha256_bytes(data)


def scene_order(mvp: dict) -> List[str]:
    return [s["id"] for s in mvp["screenshot_scenes"]]


def find_raw(project_root: Path, locale: str, device: str, scene: str) -> Optional[Path]:
    p = project_root / "factory/screenshots/raw" / locale / device / f"{scene}.png"
    return p if p.exists() else None
