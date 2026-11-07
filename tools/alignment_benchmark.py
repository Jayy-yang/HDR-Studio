"""Benchmark texture-aware alignment on the user-provided DJI Mimo bracket.

The folder is used as a validation set, not as machine-learning training data:
there are no labels, but every frame is a different exposure of the same static
scene, so edge correlation between the reference and each aligned frame is a
useful proxy for registration quality.

Run:
    python tools/alignment_benchmark.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from hdrstudio.alignment import (
    _align,
    _estimate_similarity,
    _warp_and_crop_similarity,
)
from hdrstudio.core import _common_crop, _load_rgb, _pick_reference, inspect_image

DATASET = ROOT / "照片对齐训练用例"
OUT = ROOT / "docs"
MAX_DIM = 2400


def edge_correlation(reference: np.ndarray, image: np.ndarray) -> float:
    def edges(rgb):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        gx = cv2.Scharr(gray, cv2.CV_32F, 1, 0)
        gy = cv2.Scharr(gray, cv2.CV_32F, 0, 1)
        return cv2.magnitude(gx, gy).ravel()

    a = edges(reference)
    b = edges(image[: reference.shape[0], : reference.shape[1]])
    if a.size != b.size:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def thumbnail(rgb: np.ndarray, width: int = 420, height: int = 300) -> Image.Image:
    return ImageOps.fit(
        Image.fromarray(rgb),
        (width, height),
        method=Image.Resampling.LANCZOS,
    )


def main() -> None:
    paths = sorted(DATASET.glob("*.jpg"))
    if len(paths) < 2:
        raise SystemExit(f"No benchmark images found in {DATASET}")

    images = [_load_rgb(path, MAX_DIM)[0] for path in paths]
    images, _ = _common_crop(images)
    exposures = [inspect_image(path).exposure_time for path in paths]
    times = [float(value) if value else 1.0 for value in exposures]
    reference = _pick_reference(times)
    height, width = images[0].shape[:2]

    started = time.perf_counter()
    similarity = _estimate_similarity(images, reference)
    if similarity is None:
        raise SystemExit("Similarity estimation failed on the validation set")
    work_matrices, full_matrices, needs_warp, _, work_size = similarity
    similarity_result = _warp_and_crop_similarity(
        images, work_matrices, full_matrices, work_size, (width, height)
    )
    if similarity_result is None:
        raise SystemExit("Similarity crop failed on the validation set")
    similarity_time = time.perf_counter() - started

    started = time.perf_counter()
    aligned_result, aligned_ok, shift = _align(images, reference, None)
    aligned_time = time.perf_counter() - started
    if not aligned_ok:
        raise SystemExit("Texture-aware alignment failed on the validation set")
    used_homography = aligned_result[0].shape != similarity_result[0].shape

    ref_similarity = similarity_result[reference]
    ref_aligned = aligned_result[reference]

    rows = []
    for index, path in enumerate(paths):
        if index == reference:
            rotation = scale = tx = ty = 0.0
        else:
            matrix = full_matrices[index]
            rotation = float(np.degrees(np.arctan2(matrix[1, 0], matrix[0, 0])))
            scale = float(np.sqrt(matrix[0, 0] ** 2 + matrix[1, 0] ** 2))
            tx, ty = float(matrix[0, 2]), float(matrix[1, 2])
        old_corr = edge_correlation(ref_similarity, similarity_result[index])
        new_corr = edge_correlation(ref_aligned, aligned_result[index])
        rows.append(
            {
                "index": index + 1,
                "name": path.name,
                "exposure": exposures[index],
                "rotation": rotation,
                "scale": scale,
                "tx": tx,
                "ty": ty,
                "old_corr": old_corr,
                "new_corr": new_corr,
            }
        )
        print(
            f"{index + 1}: rot={rotation:+.3f}deg scale={scale:.5f} "
            f"t=({tx:+.2f},{ty:+.2f}) "
            f"edge similarity={old_corr:.4f} texture={new_corr:.4f}"
        )

    old_mean = float(
        np.mean([row["old_corr"] for row in rows if row["index"] != reference + 1])
    )
    new_mean = float(
        np.mean([row["new_corr"] for row in rows if row["index"] != reference + 1])
    )

    # Visual comparison: top = similarity, bottom = texture-aware model.
    columns = [i for i in range(len(images)) if i != reference]
    tile_w, tile_h = 420, 300
    sheet = Image.new(
        "RGB", (tile_w * len(columns), tile_h * 2 + 52), (9, 12, 16)
    )
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (10, 8),
        f"Top: similarity (edge corr {old_mean:.3f})   "
        f"Bottom: texture-aware (edge corr {new_mean:.3f})",
        fill=(220, 225, 235),
    )
    for column, index in enumerate(columns):
        x = column * tile_w
        sheet.paste(thumbnail(similarity_result[index]), (x, 32))
        sheet.paste(thumbnail(aligned_result[index]), (x, 32 + tile_h))
        draw.text(
            (x + 8, 32 + tile_h - 18),
            f"frame {index + 1}  similarity",
            fill=(255, 210, 150),
        )
        draw.text(
            (x + 8, 32 + 2 * tile_h - 18),
            f"frame {index + 1}  texture-aware",
            fill=(120, 235, 215),
        )
    OUT.mkdir(exist_ok=True)
    sheet.save(OUT / "alignment_compare.jpg", quality=92)

    report = [
        "# 自动对齐验证报告",
        "",
        f"数据：`{DATASET.name}/`，{len(paths)} 张 4000×3000 的 DJI Mimo AEB 照片。",
        f"验证分辨率：长边 {MAX_DIM}px；参考帧：第 {reference + 1} 张（按曝光中位数）。",
        "",
        "## 结论",
        "",
        f"- 仅相似变换（ORB + RANSAC）：边缘相关系数均值 **{old_mean:.3f}**。",
        f"- 全局几何 + 局部纹理修正（相似变换 / 单应择优后修正视差）：**{new_mean:.3f}**。",
        f"- 输出尺寸：{aligned_result[0].shape[1]}×{aligned_result[0].shape[0]}，"
        f"保留约 {100.0 * aligned_result[0].shape[1] * aligned_result[0].shape[0] / (width * height):.1f}% 画面面积。",
        f"- 耗时：相似变换 {similarity_time:.2f}s；全局+局部完整对齐 {aligned_time:.2f}s。",
        f"- 本次选中单应：{'是' if used_homography else '否'}；平均平移量 {shift:.2f}px。",
        "",
        "## 每帧参数",
        "",
        "| 帧 | 曝光(s) | 旋转(°) | 缩放 | 平移(px) | 相似变换相关性 | 全局+局部相关性 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| {row['index']} | {row['exposure']:.5f} | {row['rotation']:+.3f} | "
            f"{row['scale']:.5f} | ({row['tx']:+.2f}, {row['ty']:+.2f}) | "
            f"{row['old_corr']:.3f} | {row['new_corr']:.3f} |"
        )
    report += [
        "",
        "> 相关性使用 Scharr 梯度幅值计算，范围约 0–1；越高表示边缘越一致。",
        "> 相似变换的 4 参数模型无法消除不同景深处的视差；单应候选只有在",
        "> 高频纹理相关性明显优于相似变换时才会被采用，否则自动回退。",
        "> 全局几何确定后，再用 7×9 相位相关局部位移场修正景深视差；只有纹理",
        "> 评分确实提升时才追加一次小位移 remap。整数平移仍保持无损裁切。",
        "",
        "![对齐对比](alignment_compare.jpg)",
        "",
        "![纹理优先最终合成](alignment_final.jpg)",
        "",
    ]
    (OUT / "alignment_report.md").write_text("\n".join(report), encoding="utf-8")
    print("report:", OUT / "alignment_report.md")
    print("comparison:", OUT / "alignment_compare.jpg")
    print(
        "similarity mean:",
        round(old_mean, 4),
        "texture mean:",
        round(new_mean, 4),
        "used homography:",
        used_homography,
    )


if __name__ == "__main__":
    main()
