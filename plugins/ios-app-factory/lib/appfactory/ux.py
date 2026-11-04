"""Representative use cases → wireframe storyboards for human UI/UX approval.

The designer describes each representative use case in factory/artifacts/ux/ux.json as
steps; every step carries a lightweight wireframe (title, nav items, stacked components,
the component the user taps). This module renders one storyboard PNG per use case
(screens left-to-right with the action and expected result under each), using the
design concept's palette so the reviewer sees the intended look, not grey boxes.

Rendering is deterministic, so the gate can re-render and compare. The approval is
bound to `ux_digest` (ux.json + storyboards): any change after approval invalidates it.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, List, Optional

from .color import hex_to_rgb
from .hashing import sha256_bytes, sha256_json
from .jsonio import read_json
from .project import Project

UX_DIR = "factory/artifacts/ux"
UX_JSON = f"{UX_DIR}/ux.json"
BOARD_DIR = f"{UX_DIR}/storyboards"

S = 2                       # pixel scale (points → pixels)
PW, PH = 390, 844           # phone screen in points (iPhone 15/16/17 class)
GAP = 70                    # points between screens (arrow lives here)
CAPTION_H = 230             # points under each screen for step text
HEADER_H = 120


def _font(size: float, config: dict):
    from PIL import ImageFont

    from .screenshots.compose import ComposeError, resolve_font

    try:
        path = resolve_font("ja", config)  # CJK fonts also cover Latin, so one font renders both languages
    except ComposeError:
        path = resolve_font("en-US", config)
    return ImageFont.truetype(path, int(size * S))


def _wrap(draw, text: str, font, width: float) -> List[str]:
    lines: List[str] = []
    for para in str(text).split("\n"):
        cjk = any(ord(ch) > 0x2E80 for ch in para)
        tokens = list(para) if cjk else para.split(" ")
        sep = "" if cjk else " "
        line = ""
        for tok in tokens:
            trial = (line + sep + tok) if line else tok
            if draw.textlength(trial, font=font) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = tok
        lines.append(line)
    return lines


class _Painter:
    def __init__(self, img, palette: dict, config: dict, radius: float):
        from PIL import ImageDraw

        self.img = img
        self.d = ImageDraw.Draw(img)
        self.p = {k: hex_to_rgb(v) for k, v in palette.items()}
        self.cfg = config
        self.r = radius

    def text(self, xy, text, size, color, width=None, bold=False, anchor_center=False):
        font = _font(size, self.cfg)
        lines = _wrap(self.d, text, font, width * S) if width else [text]
        x, y = xy
        for line in lines:
            tx = x * S
            if anchor_center and width:
                tx = x * S + (width * S - self.d.textlength(line, font=font)) / 2
            self.d.text((tx, y * S), line, font=font, fill=color)
            if bold:
                self.d.text((tx + 1, y * S), line, font=font, fill=color)
            y += size * 1.3
        return y

    def rect(self, box, fill=None, outline=None, width=1, radius=None):
        x0, y0, x1, y1 = box
        self.d.rounded_rectangle((x0 * S, y0 * S, x1 * S, y1 * S), radius=(self.r if radius is None else radius) * S,
                                 fill=fill, outline=outline, width=int(width * S))


def _component(pt: _Painter, c: dict, x: float, y: float, w: float) -> float:
    """Draw one component at (x, y) with width w (points). Returns its height."""
    p = pt.p
    t = c["type"]
    if t == "text":
        style = c.get("style", "body")
        size = {"title": 26, "headline": 18, "body": 16, "caption": 13}.get(style, 16)
        color = p["text_secondary"] if style == "caption" else p["text_primary"]
        end = pt.text((x, y), c.get("text", ""), size, color, width=w, bold=style in ("title", "headline"))
        return end - y + 4
    if t == "list":
        rows = c.get("rows", [])
        h = 0
        heights = [64 if r.get("subtitle") else 46 for r in rows]
        pt.rect((x, y, x + w, y + sum(heights)), fill=p["surface"])
        for r, rh in zip(rows, heights):
            pt.text((x + 14, y + h + 10), r["title"], 16, p["text_primary"], width=w - 60)
            if r.get("subtitle"):
                pt.text((x + 14, y + h + 34), r["subtitle"], 13, p["text_secondary"], width=w - 60)
            if r.get("accessory"):
                font = _font(14, pt.cfg)
                aw = pt.d.textlength(r["accessory"], font=font) / S
                pt.text((x + w - 14 - aw, y + h + 12), r["accessory"], 14, p["accent"])
            if h + rh < sum(heights):
                pt.d.line(((x + 14) * S, (y + h + rh) * S, (x + w) * S, (y + h + rh) * S), fill=p["separator"], width=S)
            h += rh
        return h
    if t == "button":
        style = c.get("style", "primary")
        if style == "link":
            pt.text((x, y + 6), c.get("text", ""), 16, p["accent"], width=w, anchor_center=True)
            return 34
        if style == "primary":
            pt.rect((x, y, x + w, y + 50), fill=p["accent"])
            pt.text((x, y + 14), c.get("text", ""), 17, p["accent_text"], width=w, bold=True, anchor_center=True)
        else:
            pt.rect((x, y, x + w, y + 50), outline=p["accent"], width=1.5)
            pt.text((x, y + 14), c.get("text", ""), 17, p["accent"], width=w, anchor_center=True)
        return 50
    if t == "field":
        pt.rect((x, y, x + w, y + 44), fill=p["surface"], outline=p["separator"])
        pt.text((x + 12, y + 12), c.get("text", ""), 16, p["text_secondary"], width=w - 24)
        return 44
    if t == "toggle":
        pt.rect((x, y, x + w, y + 48), fill=p["surface"])
        pt.text((x + 14, y + 14), c.get("text", ""), 16, p["text_primary"], width=w - 90)
        on = c.get("on", False)
        pt.rect((x + w - 66, y + 9, x + w - 14, y + 39), fill=p["accent"] if on else p["separator"], radius=15)
        kx = x + w - 42 if on else x + w - 64
        pt.d.ellipse((kx * S, (y + 11) * S, (kx + 26) * S, (y + 37) * S), fill=(255, 255, 255))
        return 48
    if t == "card":
        lines = c.get("lines", [])
        h = 24 + 24 * len(lines) + (28 if c.get("text") else 0)
        pt.rect((x, y, x + w, y + h), fill=p["surface"])
        yy = y + 12
        if c.get("text"):
            yy = pt.text((x + 14, yy), c["text"], 17, p["text_primary"], width=w - 28, bold=True)
        for line in lines:
            pt.d.ellipse(((x + 16) * S, (yy + 6) * S, (x + 24) * S, (yy + 14) * S), fill=p["accent"])
            yy = pt.text((x + 32, yy), line, 15, p["text_primary"], width=w - 46)
        return max(h, yy - y + 12)
    if t == "empty":
        cx = x + w / 2
        pt.d.ellipse(((cx - 30) * S, (y + 20) * S, (cx + 30) * S, (y + 80) * S), outline=p["text_secondary"], width=2 * S)
        yy = pt.text((x, y + 96), c.get("text", ""), 18, p["text_primary"], width=w, bold=True, anchor_center=True)
        for line in c.get("lines", []):
            yy = pt.text((x, yy + 2), line, 14, p["text_secondary"], width=w, anchor_center=True)
        return yy - y + 10
    if t == "segmented":
        items = c.get("items", []) or ["—"]
        sw = w / len(items)
        pt.rect((x, y, x + w, y + 34), fill=p["surface"], radius=9)
        sel = c.get("selected", 0)
        for i, item in enumerate(items):
            if i == sel:
                pt.rect((x + i * sw + 3, y + 3, x + (i + 1) * sw - 3, y + 31), fill=p["accent"], radius=7)
            pt.text((x + i * sw, y + 8), item, 14, p["accent_text"] if i == sel else p["text_primary"],
                    width=sw, anchor_center=True)
        return 34
    if t == "price":
        pt.text((x, y), c.get("text", ""), 30, p["text_primary"], width=w, bold=True, anchor_center=True)
        return 44
    if t == "image":
        pt.rect((x, y, x + w, y + 150), fill=p["surface"], outline=p["separator"])
        pt.d.line((x * S, y * S, (x + w) * S, (y + 150) * S), fill=p["separator"], width=S)
        pt.d.line(((x + w) * S, y * S, x * S, (y + 150) * S), fill=p["separator"], width=S)
        return 150
    if t == "divider":
        pt.d.line((x * S, (y + 6) * S, (x + w) * S, (y + 6) * S), fill=p["separator"], width=S)
        return 12
    return 0


def _screen(design: dict, wire: dict, config: dict):
    from PIL import Image

    pal = design["color"]["light"]
    radius = float(design.get("shape", {}).get("corner_radius", 12))
    img = Image.new("RGB", (PW * S, PH * S), hex_to_rgb(pal["background"]))
    pt = _Painter(img, pal, config, radius)
    p = pt.p
    top = 0
    if wire.get("presentation") == "sheet":
        pt.d.rectangle((0, 0, PW * S, 60 * S), fill=tuple(int(v * 0.55) for v in p["background"]))
        pt.rect((0, 50, PW, PH + 40), fill=p["background"], radius=14)
        pt.rect((PW / 2 - 20, 58, PW / 2 + 20, 63), fill=p["separator"], radius=3)
        top = 50
    else:
        pt.text((24, 16), "9:41", 15, p["text_primary"], bold=True)
    nav = wire.get("nav") or {}
    tap = wire.get("tap")
    font = _font(16, config)
    for side in ("leading", "trailing"):
        label = nav.get(side)
        if not label:
            continue
        tw = pt.d.textlength(label, font=font) / S
        nx = 16 if side == "leading" else PW - 16 - tw
        pt.text((nx, top + 54), label, 16, p["accent"])
        if tap == side:
            pt.rect((nx - 8, top + 48, nx + tw + 8, top + 78), outline=p["accent"], width=2.5, radius=8)
            cx, cy = (nx + tw + 22, top + 63) if side == "leading" else (nx - 22, top + 63)
            pt.d.ellipse(((cx - 12) * S, (cy - 12) * S, (cx + 12) * S, (cy + 12) * S), outline=p["accent"], width=3 * S)
            pt.d.ellipse(((cx - 4) * S, (cy - 4) * S, (cx + 4) * S, (cy + 4) * S), fill=p["accent"])
    y = top + 90
    if wire.get("title"):
        size = 18 if wire.get("presentation") == "sheet" else 30
        y = pt.text((16, y), wire["title"], size, p["text_primary"], width=PW - 32, bold=True) + 10
    for i, comp in enumerate(wire["components"]):
        h = _component(pt, comp, 16, y, PW - 32)
        if tap == i:
            pt.rect((12, y - 4, PW - 12, y + h + 4), outline=p["accent"], width=2.5)
            cx, cy = PW - 46, y + h / 2
            pt.d.ellipse(((cx - 14) * S, (cy - 14) * S, (cx + 14) * S, (cy + 14) * S), outline=p["accent"], width=3 * S)
            pt.d.ellipse(((cx - 5) * S, (cy - 5) * S, (cx + 5) * S, (cy + 5) * S), fill=p["accent"])
        y += h + 14
        if y > PH - 40:
            break
    return img


def render_storyboard(design: dict, uc: dict, config: dict) -> bytes:
    from PIL import Image, ImageDraw

    steps = uc["steps"]
    width = (PW + GAP) * len(steps) - GAP + 2 * 40
    height = HEADER_H + PH + CAPTION_H + 40
    pal = design["color"]["light"]
    board = Image.new("RGB", (width * S, height * S), (236, 237, 240))
    pt = _Painter(board, pal, config, 12)
    p = pt.p
    pt.text((40, 26), f"{uc['id']}  {uc['title']['en-US']}  /  {uc['title']['ja']}", 26, p["text_primary"], bold=True)
    pt.text((40, 70), f"{uc['kind']} · {uc['persona']} — goal: {uc['goal']}", 15, p["text_secondary"], width=width - 80)
    draw = ImageDraw.Draw(board)
    for i, step in enumerate(steps):
        x = 40 + i * (PW + GAP)
        screen = _screen(design, step["wireframe"], config)
        mask = Image.new("L", screen.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, screen.size[0] - 1, screen.size[1] - 1), radius=44 * S, fill=255)
        draw.rounded_rectangle(((x - 6) * S, (HEADER_H - 6) * S, (x + PW + 6) * S, (HEADER_H + PH + 6) * S),
                               radius=50 * S, fill=(20, 22, 24))
        board.paste(screen, (x * S, HEADER_H * S), mask)
        if i < len(steps) - 1:
            ay = HEADER_H + PH / 2
            draw.line(((x + PW + 14) * S, ay * S, (x + PW + GAP - 18) * S, ay * S), fill=p["accent"], width=3 * S)
            tip = x + PW + GAP - 12
            draw.polygon([(tip * S, ay * S), ((tip - 12) * S, (ay - 8) * S), ((tip - 12) * S, (ay + 8) * S)], fill=p["accent"])
        cy = HEADER_H + PH + 18
        cy = pt.text((x, cy), f"{i + 1}. {step['action']}", 16, p["text_primary"], width=PW, bold=True)
        cy = pt.text((x, cy + 4), f"→ {step['expected']}", 14, p["text_secondary"], width=PW)
        if step.get("copy"):
            pt.text((x, cy + 6), f"EN: {step['copy']['en-US']}\nJA: {step['copy']['ja']}", 13, p["text_secondary"], width=PW)
    out = io.BytesIO()
    board.save(out, format="PNG", optimize=False, compress_level=6)
    return out.getvalue()


def expected_files(project: Project) -> Dict[str, bytes]:
    ux = read_json(project.root / UX_JSON)
    design = read_json(project.artifact("design", "design.json"))
    if not ux or not design:
        return {}
    cfg = project.config()
    return {f"{BOARD_DIR}/{uc['id']}.png": render_storyboard(design, uc, cfg) for uc in ux["use_cases"]}


def render(project: Project) -> Dict[str, str]:
    out = {}
    wanted = expected_files(project)
    board_dir = project.root / BOARD_DIR
    board_dir.mkdir(parents=True, exist_ok=True)
    for stale in board_dir.glob("*.png"):
        if f"{BOARD_DIR}/{stale.name}" not in wanted:
            stale.unlink()
            out[f"{BOARD_DIR}/{stale.name}"] = "removed"
    for rel, data in wanted.items():
        p = project.root / rel
        if p.exists() and p.read_bytes() == data:
            out[rel] = "unchanged"
        else:
            p.write_bytes(data)
            out[rel] = "updated"
    return out


def ux_digest(project: Project) -> Optional[str]:
    """What the human approves: the use-case spec and the storyboards they looked at."""
    ux = read_json(project.root / UX_JSON)
    if not ux:
        return None
    boards = {p.name: sha256_bytes(p.read_bytes()) for p in sorted((project.root / BOARD_DIR).glob("*.png"))}
    return sha256_json({"ux": ux, "storyboards": boards})


def approval_subject(project: Project) -> dict:
    """Shape expected by approval.create (shared with release approvals)."""
    ux = read_json(project.root / UX_JSON) or {"use_cases": []}
    cfg = project.config()
    summary = [f"{uc['id']} [{uc['kind']}] {uc['title']['en-US']} / {uc['title']['ja']} — {len(uc['steps'])} steps"
               for uc in ux["use_cases"]]
    summary += [f"Review: {q}" for q in ux.get("review_focus", [])]
    summary.append(f"Storyboards: {BOARD_DIR}/*.png")
    return {"readiness_digest": ux_digest(project), "app_version": cfg["app"]["version"], "build_number": "ux",
            "summary": summary}


def board_paths(project: Project) -> List[Path]:
    return sorted((project.root / BOARD_DIR).glob("*.png"))
