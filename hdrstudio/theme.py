"""Visual language for HDR Studio: palette, fonts, ttk styles and helpers."""

from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path
from tkinter import ttk

# ---------------------------------------------------------------------------
# Palette

BG = "#0A0D12"
SURFACE = "#11161E"
SURFACE_2 = "#171E28"
SURFACE_3 = "#1D2632"
CARD = "#141B24"
CARD_SELECTED = "#1A2330"
BORDER = "#252F3C"
BORDER_SOFT = "#1B2430"
VIEW_BG = "#080A0E"

TEXT = "#EEF2F7"
TEXT_DIM = "#A9B4C2"
MUTED = "#748092"
FAINT = "#4F5B6B"

ACCENT = "#FFB15C"
ACCENT_HOVER = "#FFC47F"
ACCENT_PRESS = "#E89A42"
ACCENT_INK = "#1D1307"
ACCENT_SOFT = "#2B2318"
TEAL = "#5BD6C8"
TEAL_SOFT = "#132A2A"
SUCCESS = "#69D69A"
DANGER = "#F27D7D"
DANGER_SOFT = "#2C181B"
WARNING = "#E9BE6A"

# ---------------------------------------------------------------------------
# Typography

FONT_FAMILY = "Microsoft YaHei UI"
LATIN_FAMILY = "Segoe UI"
BRAND_FAMILY = "Bahnschrift"
MONO_FAMILY = "Cascadia Code"

FONT_BRAND = (BRAND_FAMILY, 20, "bold")
FONT_TITLE = (FONT_FAMILY, 14, "bold")
FONT_SECTION = (FONT_FAMILY, 10, "bold")
FONT_BODY = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_TINY = (FONT_FAMILY, 8)
FONT_MONO = (MONO_FAMILY, 8)
FONT_NUMBER = (BRAND_FAMILY, 12, "bold")
FONT_BUTTON = (FONT_FAMILY, 10, "bold")
FONT_BUTTON_SMALL = (FONT_FAMILY, 9)
FONT_DISPLAY = (BRAND_FAMILY, 26, "bold")

# ---------------------------------------------------------------------------
# Geometry


def rounded_points(
    x0: float, y0: float, x1: float, y1: float, radius: float, steps: int = 8
) -> list[float]:
    radius = max(0.0, min(radius, abs(x1 - x0) / 2, abs(y1 - y0) / 2))
    points: list[float] = []
    corners = [
        (x1 - radius, y0 + radius, -math.pi / 2, 0.0),
        (x1 - radius, y1 - radius, 0.0, math.pi / 2),
        (x0 + radius, y1 - radius, math.pi / 2, math.pi),
        (x0 + radius, y0 + radius, math.pi, 3 * math.pi / 2),
    ]
    for cx, cy, start, end in corners:
        for i in range(steps + 1):
            angle = start + (end - start) * i / steps
            points.extend((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def create_round_rect(
    canvas: tk.Canvas,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    radius: float = 12,
    **kwargs,
) -> int:
    return canvas.create_polygon(
        rounded_points(x0, y0, x1, y1, radius),
        smooth=False,
        splinesteps=1,
        **kwargs,
    )


def mix(color_a: str, color_b: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    a = tuple(int(color_a[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(color_b[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(
        f"{int(a[i] * (1 - amount) + b[i] * amount):02X}" for i in range(3)
    )


def truncate_name(name: str, limit: int = 22) -> str:
    if len(name) <= limit:
        return name
    suffix = Path(name).suffix
    stem = Path(name).stem
    room = max(4, limit - len(suffix) - 1)
    return f"{stem[:room]}…{suffix}"


def apply_ttk_styles(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        "Dark.TCombobox",
        fieldbackground=SURFACE_2,
        background=SURFACE_2,
        foreground=TEXT,
        arrowcolor=MUTED,
        bordercolor=BORDER,
        lightcolor=SURFACE_2,
        darkcolor=SURFACE_2,
        insertcolor=TEXT,
        padding=(10, 7),
        font=FONT_SMALL,
    )
    style.map(
        "Dark.TCombobox",
        fieldbackground=[("readonly", SURFACE_2), ("disabled", SURFACE)],
        foreground=[("readonly", TEXT), ("disabled", FAINT)],
        bordercolor=[("focus", ACCENT), ("hover", BORDER)],
        arrowcolor=[("hover", ACCENT), ("disabled", FAINT)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE_3)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_INK)
    root.option_add("*TCombobox*Listbox.font", FONT_SMALL)

    style.configure(
        "HDR.Horizontal.TProgressbar",
        troughcolor=SURFACE_2,
        background=ACCENT,
        bordercolor=SURFACE_2,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        thickness=4,
    )
    style.configure(
        "Slim.Vertical.TScrollbar",
        background=SURFACE_3,
        troughcolor=SURFACE,
        bordercolor=SURFACE,
        arrowcolor=SURFACE,
        lightcolor=SURFACE_3,
        darkcolor=SURFACE_3,
        width=6,
    )
    style.map(
        "Slim.Vertical.TScrollbar",
        background=[("active", MUTED), ("pressed", ACCENT)],
    )
    return style
