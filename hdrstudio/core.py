"""Core HDR / exposure-fusion pipeline for HDR Studio.

The module deliberately has no GUI dependencies so it can be tested and reused.
Images are represented as RGB uint8 numpy arrays and results as RGB uint8 plus,
for the true-HDR path, a float32 radiance map.
"""

from __future__ import annotations

import math
import tempfile
import time
import warnings as _warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageOps, ImageStat

from .alignment import _align

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}

MODE_FUSION = "fusion"
MODE_HDR = "hdr"
TONE_NATURAL = "natural"
TONE_DETAIL = "detail"
TONE_SOFT = "soft"

ProgressFn = Callable[[str, float], None]


class HDRMergeError(RuntimeError):
    """Raised when a bracket cannot be merged."""


@dataclass(frozen=True)
class ImageInfo:
    path: Path
    name: str
    width: int
    height: int
    exposure_time: float | None
    exposure_source: str  # "exif" or "unknown"


@dataclass(frozen=True)
class ImagePreview:
    """Everything the exposure list needs, loaded in one decode."""

    info: ImageInfo
    thumbnail: Image.Image
    brightness: float


@dataclass
class LoadedImage:
    path: Path
    rgb: np.ndarray
    exposure_time: float | None
    exposure_source: str


@dataclass
class MergeSettings:
    mode: str = MODE_FUSION
    tone: str = TONE_NATURAL
    align: bool = True
    deghost: bool = False
    max_dim: int = 2400
    brightness: float = 1.0
    saturation: float = 1.05
    detail: float = 1.0

    def validate(self) -> None:
        if self.mode not in (MODE_FUSION, MODE_HDR):
            raise ValueError(f"Unknown merge mode: {self.mode}")
        if self.tone not in (TONE_NATURAL, TONE_DETAIL, TONE_SOFT):
            raise ValueError(f"Unknown tone style: {self.tone}")


@dataclass
class MergeResult:
    image: np.ndarray  # display-referred RGB uint8
    base_ldr: np.ndarray  # unadjusted RGB float32, for live finishing
    radiance: np.ndarray | None
    reference: np.ndarray
    width: int
    height: int
    times: list[float]
    time_source: str
    mode: str
    tone: str
    aligned: bool
    deghosted: bool
    warnings: list[str] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def method_label(self) -> str:
        if self.mode == MODE_HDR:
            return {
                TONE_NATURAL: "真实 HDR · 自然",
                TONE_DETAIL: "真实 HDR · 细节",
                TONE_SOFT: "真实 HDR · 柔和",
            }[self.tone]
        return "曝光融合 · 自然光影"


# ---------------------------------------------------------------------------
# Image inspection / loading


def _read_exposure_seconds(im: Image.Image) -> float | None:
    """Read ExposureTime (0x829A) from an image's EXIF block."""
    try:
        exif = im.getexif()
    except Exception:
        return None
    value = exif.get(0x829A)
    if value is None:
        try:
            value = exif.get_ifd(ExifTags.IFD.Exif).get(0x829A)
        except Exception:
            value = None
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def inspect_image(path: str | Path) -> ImageInfo:
    p = Path(path)
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HDRMergeError(f"不支持的图片格式：{p.suffix or '未知'}")
    try:
        with Image.open(p) as im:
            exposure = _read_exposure_seconds(im)
            oriented = ImageOps.exif_transpose(im)
            width, height = oriented.size
    except Exception as exc:  # pragma: no cover - depends on broken files
        raise HDRMergeError(f"无法读取图片：{p.name}") from exc
    return ImageInfo(
        path=p,
        name=p.name,
        width=width,
        height=height,
        exposure_time=exposure,
        exposure_source="exif" if exposure else "unknown",
    )


def make_thumbnail(path: str | Path, size: tuple[int, int] = (140, 96)) -> Image.Image:
    """Return a cropped RGB thumbnail suitable for the exposure list."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = ImageOps.fit(
            im.convert("RGB"),
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.45),
        )
        return im.copy()


def read_image_preview(
    path: str | Path, size: tuple[int, int] = (78, 56)
) -> ImagePreview:
    """Read metadata, exposure and a small thumbnail in a single decode.

    This is deliberately GUI-free so the caller can run it on a worker thread.
    JPEGs use ``Image.draft`` before the full decode; a 12 MP phone photo can
    therefore produce a 78x56 card thumbnail without decoding all 36 MB of
    pixels on the UI thread.
    """
    p = Path(path)
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HDRMergeError(f"不支持的图片格式：{p.suffix or '未知'}")
    try:
        with Image.open(p) as im:
            exposure = _read_exposure_seconds(im)
            orientation = int(im.getexif().get(0x0112, 1) or 1)
            width, height = im.size
            if orientation in (5, 6, 7, 8):
                width, height = height, width
            if im.format == "JPEG" and max(width, height) > size[0] * 6:
                try:
                    im.draft("RGB", (size[0] * 6, size[1] * 6))
                except (ValueError, OSError):
                    pass
            oriented = ImageOps.exif_transpose(im)
            thumbnail = ImageOps.fit(
                oriented.convert("RGB"),
                size,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.45),
            ).copy()
            brightness = float(ImageStat.Stat(thumbnail.convert("L")).mean[0])
    except HDRMergeError:
        raise
    except Exception as exc:  # pragma: no cover - depends on broken files
        raise HDRMergeError(f"无法读取图片：{p.name}") from exc
    info = ImageInfo(
        path=p,
        name=p.name,
        width=width,
        height=height,
        exposure_time=exposure,
        exposure_source="exif" if exposure else "unknown",
    )
    return ImagePreview(info=info, thumbnail=thumbnail, brightness=brightness)


def _load_rgb(path: Path, max_dim: int) -> tuple[np.ndarray, float | None]:
    with Image.open(path) as im:
        exposure = _read_exposure_seconds(im)
        im = ImageOps.exif_transpose(im)
        if max_dim and max(im.size) > max_dim:
            im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        if im.mode in ("RGBA", "LA"):
            rgba = im.convert("RGBA")
            background = Image.new("RGB", rgba.size, (14, 17, 22))
            background.paste(rgba, mask=rgba.getchannel("A"))
            rgb = background
        else:
            rgb = im.convert("RGB")
        arr = np.asarray(rgb, dtype=np.uint8).copy()
    return arr, exposure


# ---------------------------------------------------------------------------
# Color and exposure helpers


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    x = np.clip(rgb.astype(np.float32) / 255.0, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(
        np.float32
    )


def linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    x = np.clip(linear, 0.0, 1.0)
    out = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim == 2:
        return rgb.astype(np.float32)
    return (
        rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
    ).astype(np.float32)


def _estimate_relative_times(images: Sequence[np.ndarray]) -> list[float]:
    """Estimate exposure ratios for photos without EXIF.

    We use the mean linear luminance, including clipped highlights and noisy
    shadows: unlike a mid-tone median, that quantity tracks the exposure itself.
    Absolute values do not matter for the radiance merge -- only the ratios do.
    """
    scores: list[float] = []
    for rgb in images:
        linear = srgb_to_linear(rgb)
        lum = _luminance(linear)
        score = float(np.mean(lum))
        if not math.isfinite(score):
            score = float(np.median(lum))
        scores.append(max(score, 1e-7))
    base = min(scores)
    return [float(score / base) for score in scores]


def format_exposure(seconds: float, estimated: bool = False) -> str:
    if estimated:
        if seconds >= 10.0:
            return f"{seconds:.0f}×"
        if seconds >= 2.0:
            return f"{seconds:.1f}×"
        return f"{seconds:.2f}×"
    if seconds >= 1.0:
        return f"{seconds:.1f} s" if seconds < 10 else f"{seconds:.0f} s"
    denominator = int(round(1.0 / seconds))
    if denominator <= 1:
        return f"{seconds:.2f} s"
    common = [8000, 4000, 3200, 2500, 2000, 1600, 1250, 1000, 800, 640, 500,
              400, 320, 250, 200, 160, 125, 100, 80, 60, 50, 40, 30, 25, 20,
              15, 13, 10, 8, 6, 5, 4, 3, 2]
    nearest = min(common, key=lambda item: abs(item - denominator))
    if abs(nearest - denominator) / denominator < 0.06:
        denominator = nearest
    return f"1/{denominator} s"


def _common_crop(images: list[np.ndarray]) -> tuple[list[np.ndarray], tuple[int, int]]:
    height = min(image.shape[0] for image in images)
    width = min(image.shape[1] for image in images)
    cropped = []
    for image in images:
        y0 = (image.shape[0] - height) // 2
        x0 = (image.shape[1] - width) // 2
        cropped.append(np.ascontiguousarray(image[y0 : y0 + height, x0 : x0 + width]))
    return cropped, (width, height)


def _pick_reference(times: Sequence[float]) -> int:
    logs = np.log(np.asarray(times, dtype=np.float64))
    center = float(np.median(logs))
    return int(np.argmin(np.abs(logs - center)))


def _emit(progress: ProgressFn | None, message: str, fraction: float) -> None:
    if progress:
        progress(message, max(0.0, min(1.0, fraction)))


# ---------------------------------------------------------------------------
# Alignment / deghosting


def _detect_ghost_masks(
    images: Sequence[np.ndarray],
    times: Sequence[float],
    reference: int,
    max_side: int = 800,
) -> list[np.ndarray] | None:
    """Find moving objects at low resolution and return feathered alpha masks.

    The middle exposure is treated as the reference.  This is intentionally
    conservative: when in doubt, we keep the reference instead of inventing
    detail that was never captured.
    """
    height, width = images[0].shape[:2]
    scale = min(1.0, max_side / float(max(height, width)))
    if scale < 1.0:
        small = [
            cv2.resize(image, (max(16, int(width * scale)), max(16, int(height * scale))),
                       interpolation=cv2.INTER_AREA)
            for image in images
        ]
    else:
        small = [image for image in images]

    luminances = []
    for image in small:
        lum = _luminance(srgb_to_linear(image))
        valid = (lum > 0.003) & (lum < 0.94)
        luminances.append((lum, valid))

    stack = np.stack([lum / max(times[i], 1e-6) for i, (lum, _) in enumerate(luminances)])
    valid_stack = np.stack([valid for _, valid in luminances])
    masked = np.where(valid_stack, stack, np.nan)
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", category=RuntimeWarning)
        with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
            median = np.nanmedian(masked, axis=0)
    valid_count = valid_stack.sum(axis=0)
    median_safe = np.where(np.isfinite(median), median, 0.0).astype(np.float32)
    denominator = np.maximum(median_safe, 1e-4)
    deviation = np.abs(stack - median_safe) / denominator
    raw = (
        valid_stack
        & (valid_count >= 2)
        & (median_safe > 0.008)
        & (deviation > 0.42)
    ).astype(np.uint8)
    if raw.sum() == 0:
        return None
    if float(raw.mean()) > 0.20:
        return None
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    ref_lum = luminances[reference][0]
    reference_usable = (ref_lum > 0.001) & (ref_lum < 0.98)
    cleaned = []
    for index in range(len(images)):
        layer = cv2.morphologyEx(raw[index], cv2.MORPH_OPEN, kernel)
        layer = cv2.morphologyEx(layer, cv2.MORPH_CLOSE, close_kernel)
        layer = cv2.dilate(layer, dilate_kernel)
        layer = (layer > 0) & reference_usable
        cleaned.append(layer.astype(np.uint8))
    cleaned = np.stack(cleaned)
    minimum_area = max(24, int(round(cleaned[0].size * 0.0004)))
    if int(cleaned.sum()) < minimum_area:
        return None

    masks = []
    for layer in cleaned:
        mask = cv2.GaussianBlur(layer.astype(np.float32), (0, 0), 2.0)
        masks.append(np.clip(mask, 0.0, 1.0))
    # No need to replace the reference with itself.
    masks[reference] = np.zeros_like(masks[reference])
    if any(
        float(mask.mean()) > 0.12
        for index, mask in enumerate(masks)
        if index != reference
    ):
        # A huge "moving object" is almost always changing clouds/light rather
        # than something we should paste the reference frame over.
        return None
    return masks


def _apply_ghost_masks_for_fusion(
    images: list[np.ndarray], masks_full: list[np.ndarray], reference: int
) -> list[np.ndarray]:
    ref = images[reference].astype(np.float32)
    output = [image.astype(np.float32) for image in images]
    for index in range(len(images)):
        if index == reference:
            continue
        alpha = masks_full[index][..., None]
        output[index] = output[index] * (1.0 - alpha) + ref * alpha
    return [np.clip(image, 0, 255).astype(np.uint8) for image in output]


def _upscale_masks(
    masks: list[np.ndarray], size: tuple[int, int]
) -> list[np.ndarray]:
    width, height = size
    output = []
    for mask in masks:
        if mask.shape[:2] != (height, width):
            mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_LINEAR)
        output.append(mask.astype(np.float32))
    return output


# ---------------------------------------------------------------------------
# Merge / tone mapping / finishing


def _merge_radiance(
    images: list[np.ndarray],
    times: list[float],
    ghost_masks: list[np.ndarray] | None = None,
) -> np.ndarray:
    """Weighted linear-domain merge.

    Doing the merge ourselves (rather than a camera-response calibration) keeps
    clipped highlights out of the result and lets the deghosting masks act
    directly on the merge weights.  One shared weight per pixel prevents the
    colour fringes that per-channel weighting produces at high-contrast edges.
    """
    accum = np.zeros(images[0].shape, dtype=np.float32)
    total = np.zeros(images[0].shape[:2], dtype=np.float32)
    reference = _pick_reference(times)
    for index, (image, exposure) in enumerate(zip(images, times)):
        linear = srgb_to_linear(image)
        radiance = linear / max(float(exposure), 1e-7)
        lum = np.clip(_luminance(linear), 0.0, 1.0)
        weight = 1.0 - np.power(np.abs(2.0 * lum - 1.0), 4.0)
        # Keep partially clipped pixels (one channel may still hold data), but
        # reject pixels that are clipped in every channel.
        weight *= (linear.min(axis=2) < 0.995) & (lum > 0.0025)
        if ghost_masks is not None and index != reference:
            weight *= 1.0 - ghost_masks[index]
        weight = np.clip(weight, 0.0, 1.0).astype(np.float32)
        accum += radiance * weight[..., None]
        total += weight
    if float(total.max()) <= 0:
        raise HDRMergeError("HDR 亮度合成失败，请检查曝光时间。")
    radiance = accum / np.maximum(total, 1e-4)[..., None]
    blind = total <= 1e-4
    if np.any(blind):
        # No exposure holds usable data here.  Use the clipping limit (neutral)
        # rather than amplifying JPEG noise into coloured speckles.
        radiance[blind] = 1.0 / max(float(min(times)), 1e-7)
    radiance = np.nan_to_num(radiance, nan=0.0, posinf=0.0, neginf=0.0)
    return np.maximum(radiance, 0.0).astype(np.float32)


def _reinhard(
    radiance: np.ndarray, light_adapt: float, color_adapt: float
) -> np.ndarray:
    # Normalise by the log-average luminance so the result is independent of
    # the absolute exposure unit (seconds, fractions, or arbitrary ratios).
    lum = _luminance(radiance)
    positive = lum[lum > 1e-7]
    if positive.size == 0:
        return np.zeros_like(radiance, dtype=np.float32)
    log_average = float(np.exp(np.mean(np.log(positive))))
    scale = 0.18 / max(log_average, 1e-7)
    normalised = np.clip(radiance * scale, 0.0, 1.0e4).astype(np.float32)
    tonemap = cv2.createTonemapReinhard(
        gamma=2.2, intensity=0.0, light_adapt=light_adapt, color_adapt=color_adapt
    )
    result = tonemap.process(normalised)
    result = np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def _tonemap(radiance: np.ndarray, tone: str, progress: ProgressFn | None) -> np.ndarray:
    _emit(progress, "正在进行色调映射…", 0.76)
    try:
        if tone == TONE_DETAIL:
            # Lower adaptation keeps global contrast; a small unsharp pass
            # restores the micro-detail that highlight compression softens.
            result = _reinhard(radiance, light_adapt=0.20, color_adapt=0.0)
            blurred = cv2.GaussianBlur(result, (0, 0), 1.4)
            result = np.clip(result + 0.16 * (result - blurred), 0.0, 1.0)
        elif tone == TONE_SOFT:
            result = _reinhard(radiance, light_adapt=0.50, color_adapt=0.18)
            # A gentle shoulder lifts the shadows without flattening highlights.
            result = 1.0 - np.power(np.clip(1.0 - result, 0.0, 1.0), 0.94)
        else:
            result = _reinhard(radiance, light_adapt=0.28, color_adapt=0.08)
    except cv2.error:
        result = _reinhard(radiance, light_adapt=0.28, color_adapt=0.08)
    if result is None or result.size == 0:
        raise HDRMergeError("色调映射失败。")
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def _fusion(images: list[np.ndarray], progress: ProgressFn | None) -> np.ndarray:
    _emit(progress, "正在融合不同曝光的细节…", 0.58)
    fusion = cv2.createMergeMertens(
        contrast_weight=1.0, saturation_weight=1.05, exposure_weight=0.85
    )
    result = fusion.process(images)
    if result is None:
        raise HDRMergeError("曝光融合失败。")
    result = np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def render_adjustments(
    base_ldr: np.ndarray,
    brightness: float,
    saturation: float,
    detail: float,
) -> np.ndarray:
    """Render user finishing controls without redoing the HDR merge."""
    return _polish(
        base_ldr,
        brightness=brightness,
        saturation=saturation,
        detail=detail,
    )


def _polish(
    ldr: np.ndarray,
    brightness: float,
    saturation: float,
    detail: float,
) -> np.ndarray:
    """Apply subtle, user-controlled finishing in RGB float space."""
    x = np.nan_to_num(np.clip(ldr, 0.0, 1.0), nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32)
    if abs(brightness - 1.0) > 1e-3:
        x = np.power(np.clip(x, 0.0, 1.0), 1.0 / max(brightness, 0.1))
    if abs(detail - 1.0) > 1e-3:
        sigma = max(1.2, min(x.shape[:2]) / 1100.0)
        blurred = cv2.GaussianBlur(x, (0, 0), sigma)
        amount = float(np.clip((detail - 1.0) * 0.62, -0.55, 0.65))
        x = np.clip(x + amount * (x - blurred), 0.0, 1.0)
    if abs(saturation - 1.0) > 1e-3:
        hsv = cv2.cvtColor(x, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1] * saturation, 0.0, 1.0)
        x = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    # Gentle S-curve keeps the result from looking flat after tone mapping.
    curve = x * x * (3.0 - 2.0 * x)
    x = np.clip(x * 0.86 + curve * 0.14, 0.0, 1.0)
    return np.clip(x * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)


def process_bracket(
    paths: Sequence[str | Path],
    settings: MergeSettings | None = None,
    progress: ProgressFn | None = None,
) -> MergeResult:
    """Load, align, deghost and merge a 2–5 shot exposure bracket."""
    settings = settings or MergeSettings()
    settings.validate()
    paths = [Path(path) for path in paths]
    if not 2 <= len(paths) <= 5:
        raise HDRMergeError("请选择 2 到 5 张不同曝光的照片。")
    for path in paths:
        if not path.is_file():
            raise HDRMergeError(f"找不到文件：{path.name}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise HDRMergeError(f"不支持的图片格式：{path.suffix}")

    started = time.perf_counter()
    warnings: list[str] = []
    _emit(progress, "读取照片…", 0.03)
    loaded: list[LoadedImage] = []
    for index, path in enumerate(paths):
        rgb, exposure = _load_rgb(path, settings.max_dim)
        loaded.append(
            LoadedImage(
                path=path,
                rgb=rgb,
                exposure_time=exposure,
                exposure_source="exif" if exposure else "unknown",
            )
        )
        _emit(progress, f"读取照片 {index + 1}/{len(paths)}…", 0.03 + 0.14 * (index + 1) / len(paths))

    images, size = _common_crop([item.rgb for item in loaded])
    if size[0] < 64 or size[1] < 64:
        raise HDRMergeError("图片尺寸过小，无法合成。")

    exif_times = [item.exposure_time for item in loaded]
    if all(value is not None for value in exif_times):
        times = [float(value) for value in exif_times]  # type: ignore[arg-type]
        time_source = "exif"
        if max(times) / max(min(times), 1e-9) < 1.05:
            warnings.append("所有照片的曝光时间几乎相同，HDR 动态范围提升有限。")
    else:
        times = _estimate_relative_times(images)
        time_source = "estimated"
        if any(value is not None for value in exif_times):
            warnings.append("部分照片缺少曝光信息，已统一按画面亮度估算曝光比例。")
        else:
            warnings.append("未读取到 EXIF 曝光时间，已按画面亮度估算曝光比例。")

    for index, image in enumerate(images):
        if float(image.mean()) < 1.5:
            warnings.append(f"第 {index + 1} 张照片接近全黑，可能影响合成结果。")

    reference = _pick_reference(times)

    aligned = False
    if settings.align:
        images, aligned, _ = _align(images, reference, progress)
        if not aligned:
            warnings.append("自动对齐未能可靠完成（纹理不足或位移过大），已使用原始位置。")
    else:
        _emit(progress, "已跳过自动对齐。", 0.22)

    deghosted = False
    ghost_masks_full: list[np.ndarray] | None = None
    if settings.deghost and len(images) < 3:
        warnings.append("去除移动重影至少需要 3 张照片，本次已跳过。")
    if settings.deghost and len(images) >= 3:
        _emit(progress, "正在检测移动物体…", 0.30)
        masks = _detect_ghost_masks(images, times, reference)
        if masks is not None:
            masks_full = _upscale_masks(masks, (images[0].shape[1], images[0].shape[0]))
            meaningful = any(float(mask.mean()) > 0.001 for mask in masks_full)
            if meaningful:
                deghosted = True
                ghost_masks_full = masks_full
                _emit(progress, "已抑制移动物体造成的重影。", 0.36)
            else:
                _emit(progress, "画面稳定，无需去除重影。", 0.36)
        else:
            _emit(progress, "画面稳定，无需去除重影。", 0.36)
    else:
        _emit(progress, "已跳过重影抑制。", 0.30)

    radiance: np.ndarray | None = None
    if settings.mode == MODE_HDR:
        _emit(progress, "正在合并 32 位亮度数据…", 0.58)
        radiance = _merge_radiance(
            images, times, ghost_masks_full if deghosted else None
        )
        ldr = _tonemap(radiance, settings.tone, progress)
        _emit(progress, "正在收尾处理…", 0.90)
    else:
        if deghosted and ghost_masks_full is not None:
            images = _apply_ghost_masks_for_fusion(
                images, ghost_masks_full, reference
            )
        ldr = _fusion(images, progress)
        _emit(progress, "正在收尾处理…", 0.90)

    ldr = np.asarray(ldr, dtype=np.float32)
    polished = render_adjustments(
        ldr,
        brightness=settings.brightness,
        saturation=settings.saturation,
        detail=settings.detail,
    )
    reference_image = images[reference].copy()
    elapsed = time.perf_counter() - started
    _emit(progress, "合成完成", 1.0)
    return MergeResult(
        image=polished,
        base_ldr=ldr,
        radiance=radiance,
        reference=reference_image,
        width=polished.shape[1],
        height=polished.shape[0],
        times=times,
        time_source=time_source,
        mode=settings.mode,
        tone=settings.tone,
        aligned=aligned,
        deghosted=deghosted,
        warnings=warnings,
        elapsed=elapsed,
    )


# ---------------------------------------------------------------------------
# Export


def save_result(result: MergeResult, path: str | Path, quality: int = 95) -> Path:
    """Save an 8/16-bit LDR image or, for HDR results, a Radiance .hdr file.

    HDR uses an OpenCV temporary file because OpenCV 5 no longer exposes a
    working ``.hdr`` encoder through ``imencode``; TIFF still uses imencode.
    The temporary file also keeps non-ASCII Windows paths working.
    """
    destination = Path(path)
    suffix = destination.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".hdr"}:
        raise HDRMergeError(f"不支持的导出格式：{suffix or '未知'}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    if suffix == ".hdr":
        if result.radiance is None:
            raise HDRMergeError("当前是曝光融合结果，没有可保存的 32 位亮度数据。")
        bgr = cv2.cvtColor(result.radiance, cv2.COLOR_RGB2BGR).astype(np.float32)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".hdr", delete=False) as handle:
                temporary = Path(handle.name)
            if not cv2.imwrite(str(temporary), bgr):
                raise HDRMergeError("HDR 文件编码失败。")
            destination.write_bytes(temporary.read_bytes())
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return destination

    if suffix in {".tif", ".tiff"}:
        bgr = cv2.cvtColor(result.image, cv2.COLOR_RGB2BGR)
        bgr16 = (bgr.astype(np.uint16) * 257)
        ok, encoded = cv2.imencode(".tiff", bgr16)
        if not ok:
            raise HDRMergeError("TIFF 文件编码失败。")
        destination.write_bytes(encoded.tobytes())
        return destination

    image = Image.fromarray(result.image)
    if suffix in {".jpg", ".jpeg"}:
        image.save(destination, quality=quality, subsampling=1, optimize=True)
    else:
        image.save(destination, optimize=True)
    return destination
