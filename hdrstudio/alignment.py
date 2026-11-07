"""Geometric alignment for multi-exposure brackets.

Alignment paths:

* pure translation -> integer-pixel crops when the shift is integral, or one
  high-quality sub-pixel warp when it is fractional;
* rotation / scale drift -> ORB + RANSAC similarity estimate, then a homography
  candidate scored on high-frequency texture; one cubic/Lanczos warp and a
  common-area crop remove the border;
* after either global model, a 7x9 phase-correlation grid estimates and corrects
  small depth-dependent residual shifts (foreground vs. background parallax).

The second path is what the DJI Mimo validation set needs: its frames contain
up to ~0.8 degrees of rotation and ~0.3% scale drift, which a translation-only
crop cannot remove.
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

import cv2
import numpy as np

ProgressFn = Callable[[str, float], None]


def _emit(progress: ProgressFn | None, message: str, fraction: float) -> None:
    if progress:
        progress(message, max(0.0, min(1.0, fraction)))


def _alignment_features(gray: np.ndarray) -> np.ndarray:
    """Exposure-tolerant edge map for phase correlation."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    gx = cv2.Scharr(blurred, cv2.CV_32F, 1, 0)
    gy = cv2.Scharr(blurred, cv2.CV_32F, 0, 1)
    magnitude = cv2.magnitude(gx, gy)
    magnitude -= float(magnitude.mean())
    magnitude /= float(magnitude.std()) + 1e-6
    return magnitude


def _align_translation(
    images: list[np.ndarray], reference: int, progress: ProgressFn | None
) -> tuple[list[np.ndarray], bool, float]:
    """Align a pure-translation bracket, using sub-pixel warp when needed."""
    _emit(progress, "正在测量平移并裁切对齐…", 0.20)
    height, width = images[0].shape[:2]
    scale = min(1.0, 1100.0 / float(max(height, width)))
    sample_size = (max(64, int(width * scale)), max(64, int(height * scale)))
    try:
        grays = [cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) for image in images]
        if scale < 1.0:
            grays = [
                cv2.resize(gray, sample_size, interpolation=cv2.INTER_AREA)
                for gray in grays
            ]
        features = [_alignment_features(gray) for gray in grays]
        window = cv2.createHanningWindow(sample_size, cv2.CV_32F)
        shifts: list[tuple[float, float]] = []
        for index in range(len(images)):
            if index == reference:
                shifts.append((0.0, 0.0))
                continue
            (dx, dy), response = cv2.phaseCorrelate(
                features[reference], features[index], window
            )
            dx /= scale
            dy /= scale
            limit_x = width * 0.12
            limit_y = height * 0.12
            if (
                not math.isfinite(dx)
                or not math.isfinite(dy)
                or abs(dx) > limit_x
                or abs(dy) > limit_y
                or response < 0.055
            ):
                shifts.append((0.0, 0.0))
            else:
                shifts.append((float(dx), float(dy)))
    except cv2.error:
        return images, False, 0.0

    max_x = max(abs(dx) for dx, _ in shifts)
    max_y = max(abs(dy) for _, dy in shifts)
    shift_magnitude = float(max(max_x, max_y))
    fractional = max(
        max(abs(dx - round(dx)), abs(dy - round(dy))) for dx, dy in shifts
    )
    if shift_magnitude < 0.15:
        return images, True, shift_magnitude

    # Sub-pixel translation cannot be removed by an integer crop.  Warp once
    # with a high-quality kernel so fine texture does not get a half-pixel blur.
    if fractional > 0.15:
        score_scale = min(1.0, 1200.0 / float(max(width, height)))
        work_size = (
            max(64, int(round(width * score_scale))),
            max(64, int(round(height * score_scale))),
        )
        work_matrices = []
        full_matrices = []
        for dx, dy in shifts:
            work_matrices.append(
                np.array(
                    [
                        [1.0, 0.0, -dx * score_scale],
                        [0.0, 1.0, -dy * score_scale],
                        [0.0, 0.0, 1.0],
                    ],
                    dtype=np.float32,
                )
            )
            full_matrices.append(
                np.array(
                    [[1.0, 0.0, -dx], [0.0, 1.0, -dy], [0.0, 0.0, 1.0]],
                    dtype=np.float32,
                )
            )
        subpixel = _warp_and_crop_homography(
            images, work_matrices, full_matrices, work_size, (width, height)
        )
        if subpixel is not None:
            return subpixel, True, shift_magnitude

    if shift_magnitude < 0.75:
        return images, True, shift_magnitude

    integer_shifts = [(int(round(dx)), int(round(dy))) for dx, dy in shifts]
    if all(sx == 0 and sy == 0 for sx, sy in integer_shifts):
        return images, True, float(max(max_x, max_y))

    min_x = min(sx for sx, _ in integer_shifts)
    max_x_i = max(sx for sx, _ in integer_shifts)
    min_y = min(sy for _, sy in integer_shifts)
    max_y_i = max(sy for _, sy in integer_shifts)
    left = max(0, -min_x)
    right = max(0, max_x_i)
    top = max(0, -min_y)
    bottom = max(0, max_y_i)
    new_width = width - left - right
    new_height = height - top - bottom
    if new_width < 64 or new_height < 64:
        return images, False, float(max(max_x, max_y))
    if (left + right) / width > 0.12 or (top + bottom) / height > 0.12:
        return images, False, float(max(max_x, max_y))

    aligned = []
    for image, (shift_x, shift_y) in zip(images, integer_shifts):
        x0 = left + shift_x
        x1 = width - right + shift_x
        y0 = top + shift_y
        y1 = height - bottom + shift_y
        aligned.append(np.ascontiguousarray(image[y0:y1, x0:x1]))
    return aligned, True, float(max(max_x, max_y))


def _largest_rectangle(mask: np.ndarray) -> tuple[int, int, int, int]:
    """Largest axis-aligned all-true rectangle in a binary mask."""
    height, width = mask.shape
    heights = np.zeros(width + 1, dtype=np.int32)
    best = (0, 0, width, height)
    best_area = 0
    for y in range(height):
        row = mask[y]
        for x in range(width):
            heights[x] = heights[x] + 1 if row[x] else 0
        stack: list[int] = []
        for x in range(width + 1):
            current = int(heights[x]) if x < width else 0
            while stack and int(heights[stack[-1]]) > current:
                idx = stack.pop()
                left = stack[-1] + 1 if stack else 0
                area = int(heights[idx]) * (x - left)
                if area > best_area:
                    best_area = area
                    best = (left, y - int(heights[idx]) + 1, x, y + 1)
            stack.append(x)
    return best


def _estimate_similarity(
    images: list[np.ndarray], reference: int
) -> tuple[
    list[np.ndarray], list[np.ndarray], bool, float, tuple[int, int]
] | None:
    """Estimate rotation / scale / translation with ORB + RANSAC.

    Returns work-resolution matrices, processing-resolution matrices, whether
    a warp is warranted, the largest translation, and the work-image size.
    ``None`` means the caller should fall back to the translation crop path.
    """
    height, width = images[0].shape[:2]
    work_scale = min(1.0, 1400.0 / float(max(height, width)))
    if min(height, width) * work_scale < 180:
        return None
    work_w = max(64, int(round(width * work_scale)))
    work_h = max(64, int(round(height * work_scale)))
    small = [
        cv2.resize(image, (work_w, work_h), interpolation=cv2.INTER_AREA)
        for image in images
    ]
    grays = [cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) for image in small]
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        grays = [clahe.apply(gray) for gray in grays]
        orb = cv2.ORB_create(
            nfeatures=5500,
            scaleFactor=1.2,
            nlevels=8,
            fastThreshold=10,
            edgeThreshold=15,
            patchSize=31,
        )
        key_ref, desc_ref = orb.detectAndCompute(grays[reference], None)
        if desc_ref is None or len(key_ref) < 20:
            return None
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        work_matrices: list[np.ndarray] = []
        full_matrices: list[np.ndarray] = []
        max_angle = 0.0
        max_scale_delta = 0.0
        max_translation = 0.0
        for index, gray in enumerate(grays):
            identity = np.eye(2, 3, dtype=np.float32)
            if index == reference:
                work_matrices.append(identity)
                full_matrices.append(identity.copy())
                continue
            key, desc = orb.detectAndCompute(gray, None)
            if desc is None or len(key) < 20:
                return None
            matches = matcher.knnMatch(desc_ref, desc, k=2)
            good = []
            for pair in matches:
                if len(pair) != 2:
                    continue
                first, second = pair
                if first.distance < 0.72 * second.distance:
                    good.append(first)
            if len(good) < 14:
                return None
            src = np.float32([key[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([key_ref[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            matrix, inliers = cv2.estimateAffinePartial2D(
                src,
                dst,
                method=cv2.RANSAC,
                ransacReprojThreshold=2.0,
                maxIters=4000,
                confidence=0.995,
                refineIters=15,
            )
            if matrix is None or inliers is None:
                return None
            inlier_count = int(inliers.sum())
            if inlier_count < 12 or inlier_count / max(1, len(good)) < 0.25:
                return None
            angle = float(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
            scale = float(math.sqrt(matrix[0, 0] ** 2 + matrix[1, 0] ** 2))
            if (
                not math.isfinite(angle)
                or not math.isfinite(scale)
                or abs(angle) > 4.5
                or not 0.94 < scale < 1.06
            ):
                return None
            full = matrix.astype(np.float32).copy()
            full[:, 2] /= work_scale
            if (
                abs(float(full[0, 2])) > width * 0.12
                or abs(float(full[1, 2])) > height * 0.12
            ):
                return None
            work_matrices.append(matrix.astype(np.float32))
            full_matrices.append(full)
            max_angle = max(max_angle, abs(angle))
            max_scale_delta = max(max_scale_delta, abs(scale - 1.0))
            max_translation = max(
                max_translation,
                float(math.hypot(full[0, 2], full[1, 2])),
            )
        needs_warp = max_angle > 0.18 or max_scale_delta > 0.0016
        return (
            work_matrices,
            full_matrices,
            needs_warp,
            max_translation,
            (work_w, work_h),
        )
    except cv2.error:
        return None


def _warp_and_crop_similarity(
    images: list[np.ndarray],
    work_matrices: list[np.ndarray],
    full_matrices: list[np.ndarray],
    work_size: tuple[int, int],
    output_size: tuple[int, int],
) -> list[np.ndarray] | None:
    """Warp with the similarity transform, then keep the common sharp area."""
    work_w, work_h = work_size
    width, height = output_size
    ones = np.ones((work_h, work_w), dtype=np.uint8)
    masks = []
    for matrix in work_matrices:
        mask = cv2.warpAffine(
            ones,
            matrix,
            (work_w, work_h),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        masks.append(mask > 0)
    common = np.logical_and.reduce(masks)
    common = cv2.erode(
        common.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1
    ) > 0
    # The mask boundary is smooth and only a few pixels wide.  Finding the
    # maximum rectangle on a 1/4-scale mask is ~16x faster and the extra margin
    # below absorbs the quantization.
    small_w = max(96, work_w // 4)
    small_h = max(72, work_h // 4)
    common_small = cv2.resize(
        common.astype(np.uint8) * 255,
        (small_w, small_h),
        interpolation=cv2.INTER_AREA,
    ) >= 250
    rx0, ry0, rx1, ry1 = _largest_rectangle(common_small)
    x0 = max(0, int(math.floor(rx0 * work_w / small_w)) + 3)
    y0 = max(0, int(math.floor(ry0 * work_h / small_h)) + 3)
    x1 = min(work_w, int(math.ceil(rx1 * work_w / small_w)) - 3)
    y1 = min(work_h, int(math.ceil(ry1 * work_h / small_h)) - 3)
    area = max(0, x1 - x0) * max(0, y1 - y0)
    if area < 0.60 * work_w * work_h or x1 - x0 < 64 or y1 - y0 < 64:
        return None

    scale_x = width / float(work_w)
    scale_y = height / float(work_h)
    # Scale the safe work-resolution rectangle back up, then trim a little more
    # for the interpolation fringe of the full-resolution warp.
    px0 = max(0, int(math.floor(x0 * scale_x)) + 2)
    py0 = max(0, int(math.floor(y0 * scale_y)) + 2)
    px1 = min(width, int(math.ceil(x1 * scale_x)) - 2)
    py1 = min(height, int(math.ceil(y1 * scale_y)) - 2)
    if px1 - px0 < 64 or py1 - py0 < 64:
        return None

    warped_images = []
    for image, matrix in zip(images, full_matrices):
        warped = cv2.warpAffine(
            image,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        warped_images.append(np.ascontiguousarray(warped[py0:py1, px0:px1]))
    return warped_images


def _to_matrix3(matrix: np.ndarray) -> np.ndarray:
    if matrix.shape == (3, 3):
        return matrix.astype(np.float32)
    return np.vstack([matrix.astype(np.float32), np.array([0.0, 0.0, 1.0], dtype=np.float32)])


def _score_geometry(
    images: list[np.ndarray],
    reference: int,
    work_size: tuple[int, int],
    matrices: list[np.ndarray],
    source_size: tuple[int, int] | None = None,
) -> float:
    """Texture-based score for a candidate transform, using high frequencies.

    Matrices can come from different work resolutions.  When ``source_size`` is
    supplied the matrices are interpreted in full-resolution coordinates and
    scaled to ``work_size`` first, so similarity and homography are compared at
    exactly the same texture scale.
    """
    work_w, work_h = work_size
    if source_size is not None:
        source_w, source_h = source_size
        sx = work_w / float(source_w)
        sy = work_h / float(source_h)
        scale = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], dtype=np.float64)
        scale_inv = np.array(
            [[1.0 / sx, 0, 0], [0, 1.0 / sy, 0], [0, 0, 1]], dtype=np.float64
        )
        matrices = [
            (scale @ _to_matrix3(matrix).astype(np.float64) @ scale_inv).astype(
                np.float32
            )
            for matrix in matrices
        ]
    small = [
        cv2.resize(image, (work_w, work_h), interpolation=cv2.INTER_AREA)
        for image in images
    ]
    grays = [cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) for image in small]
    ref_features = _alignment_features(grays[reference])
    scores = []
    for index, gray in enumerate(grays):
        if index == reference:
            continue
        warped = cv2.warpPerspective(
            gray,
            _to_matrix3(matrices[index]),
            (work_w, work_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        features = _alignment_features(warped)
        top, bottom = int(work_h * 0.10), int(work_h * 0.90)
        left, right = int(work_w * 0.10), int(work_w * 0.90)
        a = ref_features[top:bottom, left:right].ravel()
        b = features[top:bottom, left:right].ravel()
        if a.std() < 1e-6 or b.std() < 1e-6:
            continue
        score = float(np.corrcoef(a, b)[0, 1])
        if math.isfinite(score):
            scores.append(score)
    return float(np.mean(scores)) if scores else 0.0


def _estimate_homography(
    images: list[np.ndarray], reference: int
) -> tuple[
    list[np.ndarray], list[np.ndarray], float, tuple[int, int], float
] | None:
    """Estimate a full homography to align local texture better than similarity."""
    height, width = images[0].shape[:2]
    work_scale = min(1.0, 1800.0 / float(max(height, width)))
    if min(height, width) * work_scale < 180:
        return None
    work_w = max(64, int(round(width * work_scale)))
    work_h = max(64, int(round(height * work_scale)))
    small = [
        cv2.resize(image, (work_w, work_h), interpolation=cv2.INTER_AREA)
        for image in images
    ]
    grays = [cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) for image in small]
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        grays = [clahe.apply(gray) for gray in grays]
        orb = cv2.ORB_create(
            nfeatures=7000,
            scaleFactor=1.2,
            nlevels=8,
            fastThreshold=10,
            edgeThreshold=15,
            patchSize=31,
        )
        key_ref, desc_ref = orb.detectAndCompute(grays[reference], None)
        if desc_ref is None or len(key_ref) < 20:
            return None
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        work_matrices: list[np.ndarray] = []
        full_matrices: list[np.ndarray] = []
        ratios: list[float] = []
        identity = np.eye(3, dtype=np.float32)
        for index, gray in enumerate(grays):
            if index == reference:
                work_matrices.append(identity)
                full_matrices.append(identity.copy())
                continue
            key, desc = orb.detectAndCompute(gray, None)
            if desc is None or len(key) < 20:
                return None
            matches = matcher.knnMatch(desc_ref, desc, k=2)
            good = []
            for pair in matches:
                if len(pair) != 2:
                    continue
                first, second = pair
                if first.distance < 0.72 * second.distance:
                    good.append(first)
            if len(good) < 16:
                return None
            src = np.float32([key[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([key_ref[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            matrix, inliers = cv2.findHomography(
                src,
                dst,
                cv2.RANSAC,
                2.0,
                maxIters=5000,
                confidence=0.995,
            )
            if matrix is None or inliers is None:
                return None
            inlier_count = int(inliers.sum())
            ratio = inlier_count / max(1, len(good))
            if inlier_count < 14 or ratio < 0.35:
                return None
            corners = np.float32(
                [[0, 0], [work_w, 0], [work_w, work_h], [0, work_h]]
            ).reshape(-1, 1, 2)
            projected = cv2.perspectiveTransform(corners, matrix)
            area = abs(float(cv2.contourArea(projected)))
            if not 0.60 * work_w * work_h < area < 1.80 * work_w * work_h:
                return None
            if not cv2.isContourConvex(projected.astype(np.float32)):
                return None
            sx = width / float(work_w)
            sy = height / float(work_h)
            s = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], dtype=np.float64)
            s_inv = np.array([[1.0 / sx, 0, 0], [0, 1.0 / sy, 0], [0, 0, 1]], dtype=np.float64)
            full = (s @ matrix.astype(np.float64) @ s_inv).astype(np.float32)
            center = cv2.perspectiveTransform(
                np.float32([[[width / 2.0, height / 2.0]]]), full
            )[0, 0]
            translation = float(math.hypot(center[0] - width / 2.0, center[1] - height / 2.0))
            if translation > math.hypot(width * 0.12, height * 0.12):
                return None
            work_matrices.append(matrix.astype(np.float32))
            full_matrices.append(full)
            ratios.append(ratio)
        return work_matrices, full_matrices, translation, (work_w, work_h), float(np.mean(ratios))
    except cv2.error:
        return None


def _warp_and_crop_homography(
    images: list[np.ndarray],
    work_matrices: list[np.ndarray],
    full_matrices: list[np.ndarray],
    work_size: tuple[int, int],
    output_size: tuple[int, int],
) -> list[np.ndarray] | None:
    work_w, work_h = work_size
    width, height = output_size
    ones = np.ones((work_h, work_w), dtype=np.uint8)
    masks = []
    for matrix in work_matrices:
        mask = cv2.warpPerspective(
            ones,
            matrix,
            (work_w, work_h),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        masks.append(mask > 0)
    common = np.logical_and.reduce(masks)
    common = cv2.erode(
        common.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1
    ) > 0
    small_w = max(96, work_w // 4)
    small_h = max(72, work_h // 4)
    common_small = cv2.resize(
        common.astype(np.uint8) * 255,
        (small_w, small_h),
        interpolation=cv2.INTER_AREA,
    ) >= 250
    rx0, ry0, rx1, ry1 = _largest_rectangle(common_small)
    x0 = max(0, int(math.floor(rx0 * work_w / small_w)) + 3)
    y0 = max(0, int(math.floor(ry0 * work_h / small_h)) + 3)
    x1 = min(work_w, int(math.ceil(rx1 * work_w / small_w)) - 3)
    y1 = min(work_h, int(math.ceil(ry1 * work_h / small_h)) - 3)
    area = max(0, x1 - x0) * max(0, y1 - y0)
    if area < 0.60 * work_w * work_h or x1 - x0 < 64 or y1 - y0 < 64:
        return None
    scale_x = width / float(work_w)
    scale_y = height / float(work_h)
    px0 = max(0, int(math.floor(x0 * scale_x)) + 2)
    py0 = max(0, int(math.floor(y0 * scale_y)) + 2)
    px1 = min(width, int(math.ceil(x1 * scale_x)) - 2)
    py1 = min(height, int(math.ceil(y1 * scale_y)) - 2)
    if px1 - px0 < 64 or py1 - py0 < 64:
        return None
    warped_images = []
    for image, matrix in zip(images, full_matrices):
        warped = cv2.warpPerspective(
            image,
            matrix,
            (width, height),
            flags=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        warped_images.append(np.ascontiguousarray(warped[py0:py1, px0:px1]))
    return warped_images


def _texture_correlation(reference: np.ndarray, moving: np.ndarray) -> float:
    """Correlation of high-frequency texture in the central overlap."""
    ref_gray = cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY)
    mov_gray = cv2.cvtColor(moving, cv2.COLOR_RGB2GRAY)
    ref_features = _alignment_features(ref_gray)
    mov_features = _alignment_features(mov_gray)
    height, width = ref_features.shape[:2]
    top, bottom = int(height * 0.10), int(height * 0.90)
    left, right = int(width * 0.10), int(width * 0.90)
    a = ref_features[top:bottom, left:right].ravel()
    b = mov_features[top:bottom, left:right].ravel()
    if a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0
    score = float(np.corrcoef(a, b)[0, 1])
    return score if math.isfinite(score) else 0.0


def _local_texture_shift(
    reference: np.ndarray, moving: np.ndarray
) -> tuple[np.ndarray, np.ndarray] | None:
    """Estimate a smooth residual shift field after global alignment.

    The camera translation is not a pure rotation around the optical center, so
    nearby foreground and distant background can need slightly different shifts.
    A coarse phase-correlation grid captures that low-frequency parallax without
    letting individual moving objects drag the whole frame.
    """
    height, width = reference.shape[:2]
    if min(height, width) < 600:
        return None
    work_scale = min(1.0, 1200.0 / float(max(height, width)))
    sw = max(64, int(round(width * work_scale)))
    sh = max(64, int(round(height * work_scale)))
    ref_small = cv2.resize(reference, (sw, sh), interpolation=cv2.INTER_AREA)
    mov_small = cv2.resize(moving, (sw, sh), interpolation=cv2.INTER_AREA)
    ref_gray = cv2.cvtColor(ref_small, cv2.COLOR_RGB2GRAY).astype(np.float32)
    mov_gray = cv2.cvtColor(mov_small, cv2.COLOR_RGB2GRAY).astype(np.float32)
    ref_high = ref_gray - cv2.GaussianBlur(ref_gray, (0, 0), 2.0)
    mov_high = mov_gray - cv2.GaussianBlur(mov_gray, (0, 0), 2.0)

    rows, cols = 7, 9
    shifts = np.zeros((rows, cols, 2), dtype=np.float32)
    weights = np.zeros((rows, cols), dtype=np.float32)
    tile_w = max(64, int(sw / cols * 1.28))
    tile_h = max(64, int(sh / rows * 1.28))
    tile_w = min(tile_w, sw)
    tile_h = min(tile_h, sh)
    window = cv2.createHanningWindow((tile_w, tile_h), cv2.CV_32F)
    valid = 0
    for row in range(rows):
        cy = int((row + 0.5) * sh / rows)
        for col in range(cols):
            cx = int((col + 0.5) * sw / cols)
            x0 = min(max(0, cx - tile_w // 2), sw - tile_w)
            y0 = min(max(0, cy - tile_h // 2), sh - tile_h)
            a = ref_high[y0:y0 + tile_h, x0:x0 + tile_w]
            b = mov_high[y0:y0 + tile_h, x0:x0 + tile_w]
            (dx, dy), response = cv2.phaseCorrelate(a, b, window)
            if response >= 0.20 and abs(dx) <= 12.0 and abs(dy) <= 12.0:
                shifts[row, col] = (dx, dy)
                weights[row, col] = response
                valid += 1
    if valid < rows * cols * 0.25:
        return None

    field_x = cv2.resize(shifts[..., 0], (width, height), interpolation=cv2.INTER_CUBIC)
    field_y = cv2.resize(shifts[..., 1], (width, height), interpolation=cv2.INTER_CUBIC)
    field_x *= width / float(sw)
    field_y *= height / float(sh)
    sigma = max(8.0, max(width, height) * 0.012)
    field_x = cv2.GaussianBlur(field_x, (0, 0), sigma)
    field_y = cv2.GaussianBlur(field_y, (0, 0), sigma)
    np.clip(field_x, -8.0, 8.0, out=field_x)
    np.clip(field_y, -8.0, 8.0, out=field_y)
    return field_x, field_y


def _apply_local_texture_shift(
    image: np.ndarray, field_x: np.ndarray, field_y: np.ndarray
) -> np.ndarray:
    height, width = image.shape[:2]
    x, y = np.meshgrid(
        np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32)
    )
    return cv2.remap(
        image,
        x + field_x,
        y + field_y,
        interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT,
    )


def _refine_local_texture(
    images: list[np.ndarray], reference: int, progress: ProgressFn | None
) -> list[np.ndarray]:
    """Reduce residual parallax without replacing the global alignment."""
    if len(images) < 2 or max(images[0].shape[:2]) < 900:
        return images
    ref = images[reference]
    refined = list(images)
    changed = False
    _emit(progress, "正在校正局部纹理…", 0.235)
    for index, image in enumerate(images):
        if index == reference:
            continue
        fields = _local_texture_shift(ref, image)
        if fields is None:
            continue
        field_x, field_y = fields
        if max(float(np.abs(field_x).max()), float(np.abs(field_y).max())) < 0.35:
            continue
        corrected = _apply_local_texture_shift(image, field_x, field_y)
        before = _texture_correlation(ref, image)
        after = _texture_correlation(ref, corrected)
        if after > before + 0.004:
            refined[index] = corrected
            changed = True
    return refined if changed else images


def _align(
    images: list[np.ndarray], reference: int, progress: ProgressFn | None
) -> tuple[list[np.ndarray], bool, float]:
    """Align a bracket with the simplest model that preserves texture.

    Pure translations use integer crops (or one sub-pixel warp).  If rotation or
    scale drift is present, ORB + RANSAC estimates a similarity transform; a
    homography candidate is accepted only when its high-frequency texture score
    is better.  Accepted transforms are applied once, then the common valid area
    is cropped to hide the border.
    """
    _emit(progress, "正在分析自动对齐方式…", 0.18)
    similarity = _estimate_similarity(images, reference)
    if similarity is not None:
        work_matrices, full_matrices, needs_warp, translation, work_size = similarity
        if needs_warp:
            output_size = (images[0].shape[1], images[0].shape[0])
            score_scale = min(
                1.0,
                1200.0 / float(max(output_size[0], output_size[1])),
            )
            score_size = (
                max(64, int(round(output_size[0] * score_scale))),
                max(64, int(round(output_size[1] * score_scale))),
            )
            similarity_score = _score_geometry(
                images,
                reference,
                score_size,
                full_matrices,
                source_size=output_size,
            )
            # A full homography keeps straight texture on several depth layers
            # better than a four-parameter similarity, but it is only accepted
            # when it measurably improves high-frequency alignment.
            _emit(progress, "正在精修纹理对齐…", 0.21)
            homography = _estimate_homography(images, reference)
            if homography is not None:
                h_work, h_full, h_translation, h_size, _ = homography
                homography_score = _score_geometry(
                    images,
                    reference,
                    score_size,
                    h_full,
                    source_size=output_size,
                )
                if homography_score > similarity_score + 0.008:
                    warped = _warp_and_crop_homography(
                        images,
                        h_work,
                        h_full,
                        h_size,
                        output_size,
                    )
                    if warped is not None:
                        warped = _refine_local_texture(warped, reference, progress)
                        return warped, True, float(h_translation)
            _emit(progress, "正在校正旋转/缩放并裁切对齐…", 0.22)
            warped = _warp_and_crop_similarity(
                images,
                work_matrices,
                full_matrices,
                work_size,
                output_size,
            )
            if warped is not None:
                warped = _refine_local_texture(warped, reference, progress)
                return warped, True, float(translation)
    return _align_translation(images, reference, progress)
