"""Generate the small, dependency-free visual assets used by HDR Studio."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

ACCENT = (255, 179, 92, 255)
CREAM = (255, 240, 214, 255)
TEAL = (86, 214, 199, 255)
MUTED = (109, 123, 140, 255)


def _rounded(size: int, radius: int, fill) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=fill)
    return image


def _vertical_gradient(size: int, top, bottom) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(4))
        for x in range(size):
            pixels[x, y] = color
    return image


def make_logo(size: int = 512) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = _vertical_gradient(size, (31, 40, 53, 255), (10, 13, 18, 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * 0.235), fill=255
    )
    canvas.paste(bg, (0, 0), mask)

    # Aperture ring
    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(ring)
    cx, cy = size * 0.50, size * 0.48
    r = size * 0.285
    d.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        outline=(80, 99, 120, 120),
        width=max(1, int(size * 0.018)),
    )
    # Three overlapping exposures, blended into light.
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    spots = [
        (size * 0.38, size * 0.55, size * 0.195, (255, 150, 62, 190)),
        (size * 0.50, size * 0.37, size * 0.195, (255, 205, 107, 190)),
        (size * 0.62, size * 0.55, size * 0.195, (78, 205, 192, 175)),
    ]
    for x, y, rad, color in spots:
        d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(size * 0.012))
    canvas.alpha_composite(layer)
    # A crisp sun highlight in the overlap.
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(highlight)
    r = size * 0.086
    cx, cy = size * 0.50, size * 0.485
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 246, 228, 235))
    highlight = highlight.filter(ImageFilter.GaussianBlur(size * 0.006))
    canvas.alpha_composite(highlight)
    # Small exposure ticks
    d = ImageDraw.Draw(canvas)
    for i, x in enumerate((0.29, 0.36, 0.64, 0.71)):
        y = size * 0.78
        r = size * 0.007
        color = (255, 255, 255, 95) if i in (0, 3) else (255, 179, 92, 180)
        d.ellipse((size * x - r, y - r, size * x + r, y + r), fill=color)
    return canvas


def make_empty_photos(size: tuple[int, int] = (260, 176)) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    frames = [
        ((34, 52, 174, 152), (63, 75, 92, 255), -8),
        ((52, 38, 192, 138), (91, 108, 130, 255), 0),
        ((70, 24, 210, 124), (255, 179, 92, 255), 0),
    ]
    # Draw back-to-front with a tiny rotation for the first card.
    for index, (box, outline, angle) in enumerate(frames):
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle(box, radius=12, fill=(26, 33, 43, 255), outline=outline, width=3)
        x0, y0, x1, y1 = box
        if index == 2:
            d.rounded_rectangle(
                (x0 + 14, y0 + 14, x1 - 14, y1 - 20),
                radius=5,
                fill=(18, 23, 30, 255),
            )
            d.ellipse((x0 + 30, y0 + 28, x0 + 48, y0 + 46), fill=(255, 202, 114, 160))
            d.polygon(
                [
                    (x0 + 18, y1 - 28),
                    (x0 + 58, y0 + 62),
                    (x0 + 92, y1 - 34),
                    (x1 - 22, y1 - 28),
                ],
                fill=(55, 72, 90, 255),
            )
            d.ellipse((x1 - 48, y0 + 26, x1 - 28, y0 + 46), fill=(86, 214, 199, 170))
        elif index == 1:
            d.line((x0 + 22, y0 + 32, x1 - 22, y0 + 32), fill=(75, 89, 108, 255), width=3)
            d.line((x0 + 22, y0 + 46, x1 - 52, y0 + 46), fill=(53, 65, 81, 255), width=2)
        if angle:
            layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC, center=(size[0] / 2, size[1] / 2))
        image.alpha_composite(layer)
    # dashed plus badge
    draw.rounded_rectangle((204, 104, 252, 152), radius=16, fill=(24, 30, 39, 255), outline=(255, 179, 92, 210), width=2)
    draw.line((228, 116, 228, 140), fill=ACCENT, width=3)
    draw.line((216, 128, 240, 128), fill=ACCENT, width=3)
    return image


def make_preview_empty() -> Image.Image:
    image = make_empty_photos((300, 200))
    # Add a soft glow behind the cards.
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((60, 36, 240, 174), fill=(255, 179, 92, 18))
    glow = glow.filter(ImageFilter.GaussianBlur(28))
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(image)
    return out


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    logo = make_logo(512)
    logo.save(ASSETS / "logo.png")
    logo.resize((256, 256), Image.Resampling.LANCZOS).save(
        ASSETS / "logo.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    make_empty_photos().save(ASSETS / "empty_list.png")
    make_preview_empty().save(ASSETS / "empty_preview.png")
    print("assets written to", ASSETS)


if __name__ == "__main__":
    main()
