"""Colour maths: WCAG 2.x contrast and CIE76 ΔE for 'generic palette' detection."""
from __future__ import annotations

from typing import Tuple

RGB = Tuple[int, int, int]


def hex_to_rgb(value: str) -> RGB:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    r, g, b = hex_to_rgb(hex_color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def _to_lab(hex_color: str):
    r, g, b = (_lin(c) for c in hex_to_rgb(hex_color))
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 1.0
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    la, lb = _to_lab(a), _to_lab(b)
    return round(sum((p - q) ** 2 for p, q in zip(la, lb)) ** 0.5, 2)


# Accent colours that dominate template / AI-generated UIs (Tailwind indigo &
# violet defaults, "AI purple" gradients, stock iOS system blue used as-is).
CLICHE_ACCENTS = {
    "tailwind-indigo-500": "#6366F1",
    "tailwind-indigo-600": "#4F46E5",
    "tailwind-violet-500": "#8B5CF6",
    "tailwind-purple-500": "#A855F7",
    "ai-gradient-purple": "#7C3AED",
    "ios-system-blue": "#007AFF",
    "material-deep-purple": "#673AB7",
    "bootstrap-primary": "#0D6EFD",
    # Calibration list from Anthropic's frontend-design skill ("AI-generated design clusters around..."):
    "claude-terracotta": "#D97757",
    "acid-green": "#B6FF3B",
    "vermilion": "#FF4F1F",
}

CLICHE_BACKGROUNDS = {
    "warm-cream": "#F4F1EA",
    "tinted-near-black": "#0B0B0B",
}


def nearest_cliche(hex_color: str):
    name, ref = min(CLICHE_ACCENTS.items(), key=lambda kv: delta_e(hex_color, kv[1]))
    return name, ref, delta_e(hex_color, ref)


def nearest_cliche_background(hex_color: str):
    name, ref = min(CLICHE_BACKGROUNDS.items(), key=lambda kv: delta_e(hex_color, kv[1]))
    return name, ref, delta_e(hex_color, ref)
