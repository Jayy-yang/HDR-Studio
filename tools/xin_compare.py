from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image, ImageDraw

from hdrstudio.alignment import (
    _align,
    _estimate_similarity,
    _texture_correlation,
    _warp_and_crop_similarity,
)
from hdrstudio.core import _common_crop, _estimate_relative_times, _load_rgb, _pick_reference

paths = sorted((ROOT / "照片对齐训练用例" / "xin").glob("*.jpg"))
images = [_load_rgb(path, 2400)[0] for path in paths]
images, _ = _common_crop(images)
reference = _pick_reference(_estimate_relative_times(images))
height, width = images[0].shape[:2]


def edge_correlation(reference_image, moving_image) -> float:
    first = cv2.cvtColor(reference_image, cv2.COLOR_RGB2GRAY)
    second = cv2.cvtColor(moving_image, cv2.COLOR_RGB2GRAY)
    first = cv2.magnitude(
        cv2.Scharr(first, cv2.CV_32F, 1, 0),
        cv2.Scharr(first, cv2.CV_32F, 0, 1),
    )
    second = cv2.magnitude(
        cv2.Scharr(second, cv2.CV_32F, 1, 0),
        cv2.Scharr(second, cv2.CV_32F, 0, 1),
    )
    h, w = first.shape
    top, bottom = int(h * 0.10), int(h * 0.90)
    left, right = int(w * 0.10), int(w * 0.90)
    return float(
        np.corrcoef(
            first[top:bottom, left:right].ravel(),
            second[top:bottom, left:right].ravel(),
        )[0, 1]
    )

sim = _estimate_similarity(images, reference)
assert sim is not None
work_matrices, full_matrices, _, _, work_size = sim
before = _warp_and_crop_similarity(images, work_matrices, full_matrices, work_size, (width, height))
assert before is not None
after, ok, shift = _align(images, reference, None)
assert ok
print("ref", reference + 1, "before", before[0].shape, "after", after[0].shape, "shift", shift)
for index in range(1, len(after)):
    print(
        "frame",
        index + 1,
        "texture",
        round(_texture_correlation(before[0], before[index]), 4),
        "->",
        round(_texture_correlation(after[0], after[index]), 4),
        "edge",
        round(edge_correlation(before[0], before[index]), 4),
        "->",
        round(edge_correlation(after[0], after[index]), 4),
    )

Image.fromarray(before[4]).save(ROOT / "docs" / "xin_before.jpg", quality=92)
Image.fromarray(after[4]).save(ROOT / "docs" / "xin_after.jpg", quality=92)

x0, y0, cw, ch = 1250, 500, 900, 700
panels = [
    ("reference", before[reference]),
    ("before local refinement", before[4]),
    ("after local refinement", after[4]),
]
tiles = []
for label, image in panels:
    crop = image[y0:y0 + ch, x0:x0 + cw]
    tile = Image.new("RGB", (cw, ch + 30), (9, 12, 16))
    tile.paste(Image.fromarray(crop), (0, 30))
    ImageDraw.Draw(tile).text((8, 8), label, fill=(255, 220, 170))
    tiles.append(tile)
sheet = Image.new("RGB", (cw * len(tiles), ch + 30), (9, 12, 16))
for index, tile in enumerate(tiles):
    sheet.paste(tile, (index * cw, 0))
sheet.save(ROOT / "docs" / "xin_crop_before_after.jpg", quality=94)
print("saved")
