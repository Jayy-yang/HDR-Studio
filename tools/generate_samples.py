"""Generate three synthetic exposure-bracket samples for HDR Studio.

This is intentionally procedural (no third-party photos) and produces a wide
dynamic-range still life: a bright window, deep interior shadows and a warm lamp.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from PIL.TiffImagePlugin import IFDRational

WIDTH, HEIGHT = 1800, 1200
OUT = Path(__file__).resolve().parent.parent / "samples"


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def band(x: np.ndarray, lo: float, hi: float, soft: float = 0.0025) -> np.ndarray:
    return smoothstep(lo - soft, lo + soft, x) * (
        1.0 - smoothstep(hi - soft, hi + soft, x)
    )


def rect_mask(xx, yy, x0, x1, y0, y1, soft=0.0025):
    return band(xx, x0, x1, soft) * band(yy, y0, y1, soft)


def ellipse_mask(xx, yy, cx, cy, rx, ry, soft=0.003):
    d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    return 1.0 - smoothstep(1.0 - soft, 1.0 + soft, d)


def over(base, color, mask):
    for channel in range(3):
        base[..., channel] = base[..., channel] * (1 - mask) + color[channel] * mask
    return base


def gaussian(xx, yy, cx, cy, sigma, strength):
    return strength * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma**2)))


def poly_mask(points, feather=1.2):
    canvas = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(canvas)
    draw.polygon(points, fill=255)
    if feather:
        from PIL import ImageFilter

        canvas = canvas.filter(ImageFilter.GaussianBlur(feather))
    return np.asarray(canvas, dtype=np.float32) / 255.0


def build_scene() -> np.ndarray:
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    xx /= WIDTH - 1
    yy /= HEIGHT - 1

    # --- interior wall: warm plaster, darker towards the left -----------------
    wall = np.stack(
        [
            0.85 + 1.65 * xx - 0.70 * yy,
            0.68 + 1.25 * xx - 0.45 * yy,
            0.48 + 0.85 * xx - 0.30 * yy,
        ],
        axis=-1,
    ).astype(np.float32)
    # soft vignette
    vignette = 1.0 - 0.55 * np.clip(
        ((xx - 0.5) ** 2 / 0.5 + (yy - 0.5) ** 2 / 0.52), 0, 1
    )
    wall *= vignette[..., None]
    # wall texture
    rng = np.random.default_rng(7)
    texture = rng.normal(0, 1, (120, 160)).astype(np.float32)
    texture = np.asarray(
        Image.fromarray(((texture - texture.min()) / np.ptp(texture) * 255).astype(np.uint8))
        .resize((WIDTH, HEIGHT), Image.Resampling.BICUBIC)
        .filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(1.2)),
        dtype=np.float32,
    ) / 255.0
    wall *= (0.92 + 0.16 * texture)[..., None]

    image = wall

    # --- window opening / outside --------------------------------------------
    win_x0, win_x1 = 0.345, 0.865
    win_y0, win_y1 = 0.075, 0.675
    inner_x0, inner_x1 = 0.375, 0.835
    inner_y0, inner_y1 = 0.105, 0.645

    # plaster reveal around the opening (brighter, catches daylight)
    reveal = rect_mask(xx, yy, win_x0 - 0.016, win_x1 + 0.016, win_y0 - 0.016, win_y1 + 0.016) - rect_mask(
        xx, yy, win_x0, win_x1, win_y0, win_y1
    )
    over(image, (2.9, 2.55, 2.0), np.clip(reveal, 0, 1))

    frame = rect_mask(xx, yy, win_x0, win_x1, win_y0, win_y1) - rect_mask(
        xx, yy, inner_x0, inner_x1, inner_y0, inner_y1
    )
    over(image, (0.13, 0.095, 0.07), frame)

    # outside gradient: blue sky to warm horizon
    sky_t = np.clip((yy - inner_y0) / (inner_y1 - inner_y0), 0, 1)
    sky_colors = np.stack(
        [
            1.2 + 6.0 * (1 - sky_t) + 5.0 * np.exp(-((sky_t - 0.85) / 0.18) ** 2),
            2.2 + 13.0 * (1 - sky_t) + 3.0 * np.exp(-((sky_t - 0.85) / 0.18) ** 2),
            4.8 + 21.0 * (1 - sky_t),
        ],
        axis=-1,
    ).astype(np.float32)
    outside = sky_colors.copy()

    # clouds
    for cx, cy, rx, ry, strength in [
        (0.46, 0.19, 0.095, 0.026, 6.0),
        (0.55, 0.16, 0.075, 0.020, 4.5),
        (0.70, 0.24, 0.11, 0.022, 5.0),
        (0.49, 0.28, 0.12, 0.020, 2.0),
    ]:
        cloud = ellipse_mask(xx, yy, cx, cy, rx, ry, soft=0.5) * 0.75
        over(outside, (22.0, 19.0, 16.0), cloud * (strength / 10.0))

    # sun and bloom
    sun = gaussian(xx, yy, 0.755, 0.20, 0.028, 900.0) + gaussian(
        xx, yy, 0.755, 0.20, 0.105, 45.0
    )
    outside += sun[..., None] * np.array([1.0, 0.78, 0.46], dtype=np.float32)

    # distant mountain ridges (two layers, hazy)
    ridge1 = inner_y0 + 0.285 + 0.028 * np.sin(xx * 33) + 0.018 * np.sin(xx * 71 + 1.1)
    mountain1 = smoothstep(ridge1 - 0.002, ridge1 + 0.002, yy) * rect_mask(
        xx, yy, inner_x0, inner_x1, inner_y0, inner_y1, 0.001
    )
    over(outside, (0.42, 0.62, 0.95), mountain1 * 0.72)
    ridge2 = inner_y0 + 0.355 + 0.022 * np.sin(xx * 24 + 2.0) + 0.012 * np.sin(xx * 57)
    mountain2 = smoothstep(ridge2 - 0.002, ridge2 + 0.002, yy) * rect_mask(
        xx, yy, inner_x0, inner_x1, inner_y0, inner_y1, 0.001
    )
    over(outside, (0.30, 0.46, 0.66), mountain2 * 0.88)

    # foreground tree line
    tree_line = inner_y1 - 0.055 + 0.014 * np.sin(xx * 90 + 0.4)
    trees = smoothstep(tree_line - 0.002, tree_line + 0.002, yy) * rect_mask(
        xx, yy, inner_x0, inner_x1, inner_y0, inner_y1, 0.001
    )
    over(outside, (0.12, 0.38, 0.22), trees * 0.9)

    outside_mask = rect_mask(xx, yy, inner_x0, inner_x1, inner_y0, inner_y1)
    over(image, (0, 0, 0), 0)
    image = image * (1 - outside_mask[..., None]) + outside * outside_mask[..., None]

    # window mullions
    mullion_h = rect_mask(xx, yy, inner_x0, inner_x1, 0.365, 0.386)
    mullion_v = rect_mask(xx, yy, 0.594, 0.615, inner_y0, inner_y1)
    mullion = np.clip(mullion_h + mullion_v, 0, 1) * outside_mask
    over(image, (0.12, 0.085, 0.062), mullion)
    # thin highlights on the frame
    edge_light = (
        rect_mask(xx, yy, win_x0, win_x0 + 0.004, win_y0, win_y1)
        + rect_mask(xx, yy, win_x1 - 0.004, win_x1, win_y0, win_y1)
    ) * 0.75
    over(image, (2.6, 2.0, 1.35), np.clip(edge_light, 0, 1))

    # glass reflection streak
    streak = np.exp(-(((xx - 0.47) - (yy - 0.12) * 0.28) / 0.018) ** 2) * outside_mask * rect_mask(
        xx, yy, inner_x0, inner_x1, inner_y0, 0.42
    )
    image += (streak * 1.4)[..., None] * np.array([0.9, 0.95, 1.0], dtype=np.float32)

    # --- table / floor --------------------------------------------------------
    table_top = 0.695
    table = smoothstep(table_top - 0.002, table_top + 0.002, yy)
    wood_colors = np.stack(
        [
            0.78 + 0.55 * (1 - yy),
            0.46 + 0.34 * (1 - yy),
            0.24 + 0.20 * (1 - yy),
        ],
        axis=-1,
    ).astype(np.float32)
    grain = (
        np.sin(xx * 120 + 2.4 * np.sin(yy * 32)) * 0.06
        + np.sin(xx * 310 + 0.7) * 0.025
    )
    wood = wood_colors * (1.0 + grain[..., None])
    # window light falling across the table
    light_patch = (
        rect_mask(xx, yy, 0.40, 0.81, 0.71, 0.995, 0.01)
        * (0.35 + 0.65 * smoothstep(0.995, 0.70, yy))
    )
    wood += light_patch[..., None] * np.array([5.8, 4.8, 3.4], dtype=np.float32)
    image = image * (1 - table[..., None]) + wood * table[..., None]

    # --- window light patch on wall / floor ----------------------------------
    wall_glow = rect_mask(xx, yy, 0.32, 0.87, 0.66, 0.72, 0.02) * 0.6
    over(image, (7.0, 6.0, 4.4), wall_glow)

    # --- lamp on the left -----------------------------------------------------
    lamp_x = 0.155
    shade = poly_mask(
        [
            (WIDTH * (lamp_x - 0.075), HEIGHT * 0.385),
            (WIDTH * (lamp_x + 0.070), HEIGHT * 0.385),
            (WIDTH * (lamp_x + 0.100), HEIGHT * 0.555),
            (WIDTH * (lamp_x - 0.105), HEIGHT * 0.555),
        ],
        feather=1.5,
    )
    # lamp emits warm light; the shade is translucent
    image += shade[..., None] * np.array([18.0, 8.5, 2.4], dtype=np.float32)
    shade_rim = np.clip(
        poly_mask(
            [
                (WIDTH * (lamp_x - 0.075), HEIGHT * 0.382),
                (WIDTH * (lamp_x + 0.070), HEIGHT * 0.382),
                (WIDTH * (lamp_x + 0.074), HEIGHT * 0.396),
                (WIDTH * (lamp_x - 0.079), HEIGHT * 0.396),
            ],
            feather=1.0,
        ),
        0,
        1,
    )
    over(image, (0.11, 0.075, 0.045), shade_rim)
    # stem
    stem = rect_mask(xx, yy, lamp_x - 0.006, lamp_x + 0.006, 0.54, 0.70)
    over(image, (0.18, 0.14, 0.10), stem)
    # glow on wall behind lamp
    glow = gaussian(xx, yy, lamp_x, 0.52, 0.14, 0.85)
    image += glow[..., None] * np.array([3.2, 1.45, 0.42], dtype=np.float32)

    # --- ceramic pitcher and fruit -------------------------------------------
    pitcher = poly_mask(
        [
            (WIDTH * 0.585, HEIGHT * 0.615),
            (WIDTH * 0.620, HEIGHT * 0.630),
            (WIDTH * 0.655, HEIGHT * 0.690),
            (WIDTH * 0.667, HEIGHT * 0.810),
            (WIDTH * 0.636, HEIGHT * 0.858),
            (WIDTH * 0.585, HEIGHT * 0.858),
            (WIDTH * 0.556, HEIGHT * 0.810),
            (WIDTH * 0.565, HEIGHT * 0.690),
        ],
        feather=1.0,
    )
    # shaded ceramic: left side catches window/lamp, right side falls off
    pitcher_shade = np.clip(0.28 + 1.25 * (0.665 - xx), 0.18, 1.25)
    for channel, base in enumerate((3.07, 3.25, 3.35)):
        image[..., channel] += pitcher * pitcher_shade * base * 0.62
    # handle
    handle_outer = ellipse_mask(xx, yy, 0.672, 0.735, 0.042, 0.060, soft=0.03)
    handle_inner = ellipse_mask(xx, yy, 0.678, 0.735, 0.025, 0.042, soft=0.03)
    handle = np.clip(handle_outer - handle_inner, 0, 1) * 0.85
    over(image, (1.45, 1.60, 1.72), handle)
    # opening
    opening = ellipse_mask(xx, yy, 0.608, 0.638, 0.044, 0.014)
    over(image, (0.10, 0.075, 0.055), opening)

    # oranges
    for cx, cy, rx, ry in [(0.735, 0.815, 0.055, 0.043), (0.800, 0.842, 0.043, 0.035), (0.680, 0.865, 0.040, 0.031)]:
        fruit = ellipse_mask(xx, yy, cx, cy, rx, ry, soft=0.004)
        radial = np.clip(
            1.15 - 1.3 * np.sqrt(((xx - (cx - rx * 0.25)) / (rx * 2.2)) ** 2 + ((yy - (cy - ry * 0.3)) / (ry * 2.2)) ** 2),
            0.25,
            1.35,
        )
        color = np.array([6.8, 2.1, 0.22], dtype=np.float32) * radial[..., None]
        image = image * (1 - fruit[..., None]) + color * fruit[..., None]
        # highlight
        hl = gaussian(xx, yy, cx - rx * 0.3, cy - ry * 0.35, 0.006, 1)
        image += (hl * 9.0)[..., None]

    # a dark bowl under the fruit
    bowl = ellipse_mask(xx, yy, 0.748, 0.878, 0.135, 0.022, soft=0.01)
    over(image, (0.10, 0.075, 0.055), bowl * 0.8)

    # --- tall plant on the right ---------------------------------------------
    pot = poly_mask(
        [
            (WIDTH * 0.895, HEIGHT * 0.735),
            (WIDTH * 0.960, HEIGHT * 0.735),
            (WIDTH * 0.945, HEIGHT * 0.905),
            (WIDTH * 0.910, HEIGHT * 0.905),
        ],
        feather=1.2,
    )
    over(image, (0.85, 0.50, 0.30), pot * 0.55)
    rng = np.random.default_rng(22)
    for _ in range(9):
        base_x = rng.uniform(0.90, 0.945)
        base_y = 0.735
        length = rng.uniform(0.10, 0.25)
        lean = rng.uniform(-0.055, 0.055)
        for t in np.linspace(0, 1, 70):
            cx = base_x + lean * t + 0.008 * math.sin(t * 8)
            cy = base_y - length * t
            leaf = ellipse_mask(xx, yy, cx, cy, 0.010, 0.006, soft=0.04)
            tint = 0.4 + 0.6 * t
            over(image, (0.10 * tint, 0.50 * tint, 0.11 * tint), leaf * 0.85)

    # --- subtle atmospheric haze and bloom ------------------------------------
    bloom = gaussian(xx, yy, 0.73, 0.22, 0.30, 0.10)
    image += bloom[..., None] * np.array([1.4, 1.15, 0.80], dtype=np.float32)

    # --- final texture / grain ------------------------------------------------
    grain = rng.normal(0, 1, (HEIGHT, WIDTH)).astype(np.float32)
    image *= (1.0 + 0.012 * grain)[..., None]
    return np.maximum(image, 0.0005)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scene = build_scene()
    print("scene range", float(scene.min()), float(scene.max()))
    shots = [
        ("bracket_01_dark.jpg", 1 / 500.0, (-2, 2)),
        ("bracket_02_mid.jpg", 1 / 125.0, (1, -1)),
        ("bracket_03_bright.jpg", 1 / 30.0, (0, 0)),
    ]
    for name, exposure, (dx, dy) in shots:
        exposed = np.clip(scene * exposure, 0, None)
        encoded = linear_to_srgb(exposed)
        # tiny amount of photon/sensor noise, more in shadows
        rng = np.random.default_rng(hash(name) % (2**32))
        noise = rng.normal(0, 0.006, encoded.shape).astype(np.float32)
        encoded = np.clip(encoded + noise, 0, 1)
        rgb = (encoded * 255 + 0.5).astype(np.uint8)
        rgb = np.roll(rgb, shift=(dy, dx), axis=(0, 1))
        image = Image.fromarray(rgb, "RGB")
        exif = Image.Exif()
        exif[0x829A] = IFDRational(1, int(round(1 / exposure)))
        exif[0x0131] = "HDR Studio sample scene"
        image.save(OUT / name, quality=94, subsampling=1, exif=exif)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
