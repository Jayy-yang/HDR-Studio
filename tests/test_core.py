"""Core pipeline tests. Run with: python -m unittest discover -s tests -v"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / ".vendor"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from hdrstudio.core import (  # noqa: E402
    MODE_FUSION,
    MODE_HDR,
    HDRMergeError,
    MergeSettings,
    _align,
    format_exposure,
    inspect_image,
    process_bracket,
    read_image_preview,
    render_adjustments,
    save_result,
)
from hdrstudio.alignment import (  # noqa: E402
    _refine_local_texture,
    _texture_correlation,
)

SAMPLES = sorted((ROOT / "samples").glob("bracket_*.jpg"))
OUTPUT = Path(__file__).resolve().parent


class CorePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fusion = process_bracket(
            SAMPLES,
            MergeSettings(mode=MODE_FUSION, max_dim=760, deghost=False),
        )
        cls.hdr = process_bracket(
            SAMPLES,
            MergeSettings(mode=MODE_HDR, max_dim=760, deghost=False),
        )
        cls.two_fusion = process_bracket(
            SAMPLES[:2],
            MergeSettings(mode=MODE_FUSION, max_dim=600, deghost=False),
        )
        cls.two_hdr = process_bracket(
            SAMPLES[:2],
            MergeSettings(mode=MODE_HDR, max_dim=600, deghost=False),
        )

    def test_exif_is_read(self) -> None:
        info = inspect_image(SAMPLES[0])
        self.assertIsNotNone(info.exposure_time)
        assert info.exposure_time is not None
        self.assertAlmostEqual(info.exposure_time, 1 / 500, places=5)
        self.assertEqual(info.exposure_source, "exif")

    def test_exposure_labels(self) -> None:
        self.assertEqual(format_exposure(1 / 125), "1/125 s")
        self.assertEqual(format_exposure(2.5), "2.5 s")
        self.assertEqual(format_exposure(12.5), "12 s")
        self.assertEqual(format_exposure(8.0, estimated=True), "8.0×")

    def test_preview_loader(self) -> None:
        preview = read_image_preview(SAMPLES[0], (78, 56))
        self.assertEqual(preview.thumbnail.size, (78, 56))
        self.assertEqual((preview.info.width, preview.info.height), (1800, 1200))
        self.assertAlmostEqual(preview.info.exposure_time or 0, 1 / 500, places=5)
        self.assertGreater(preview.brightness, 0.0)
        self.assertLess(preview.brightness, 255.0)

    def test_fusion_result(self) -> None:
        result = self.fusion
        self.assertEqual(result.image.dtype, np.uint8)
        self.assertEqual(result.image.ndim, 3)
        self.assertEqual(result.image.shape[2], 3)
        self.assertGreater(result.width, 600)
        self.assertGreater(result.height, 400)
        self.assertIsNone(result.radiance)
        self.assertTrue(result.aligned)
        self.assertEqual(result.time_source, "exif")
        self.assertGreater(float(result.image.std()), 5.0)
        self.assertEqual(result.base_ldr.dtype, np.float32)
        self.assertEqual(result.base_ldr.shape, (result.height, result.width, 3))

    def test_hdr_result_and_radiance(self) -> None:
        result = self.hdr
        self.assertIsNotNone(result.radiance)
        assert result.radiance is not None
        self.assertEqual(result.radiance.dtype, np.float32)
        self.assertTrue(np.isfinite(result.radiance).all())
        self.assertGreater(float(result.radiance.max()), 1.0)
        self.assertEqual(result.mode, MODE_HDR)
        self.assertEqual(result.image.shape[:2], result.radiance.shape[:2])

    def test_two_photo_bracket(self) -> None:
        self.assertGreater(self.two_fusion.width, 400)
        self.assertEqual(self.two_fusion.image.dtype, np.uint8)
        self.assertIsNotNone(self.two_hdr.radiance)
        assert self.two_hdr.radiance is not None
        self.assertTrue(np.isfinite(self.two_hdr.radiance).all())
        self.assertGreater(float(self.two_fusion.image.std()), 5.0)
        with_deghost = process_bracket(
            SAMPLES[:2],
            MergeSettings(mode=MODE_FUSION, max_dim=400, deghost=True),
        )
        self.assertTrue(
            any("至少需要 3 张" in warning for warning in with_deghost.warnings)
        )

    def test_crop_alignment_keeps_pixels(self) -> None:
        rng = np.random.default_rng(4)
        base = (rng.random((240, 320, 3)) * 255).astype(np.uint8)
        base = cv2.GaussianBlur(base, (0, 0), 1.1)
        shifted = np.roll(base, (3, -5), axis=(0, 1))
        aligned, ok, shift = _align([base, shifted], 0, None)
        self.assertTrue(ok)
        self.assertGreater(shift, 1.0)
        self.assertEqual(aligned[0].shape, (237, 315, 3))
        difference = np.abs(
            aligned[0].astype(np.float32) - aligned[1].astype(np.float32)
        )
        # Integer cropping must align the overlap exactly, with no resampling.
        self.assertLess(float(difference.mean()), 0.01)

    def test_live_finishing_controls(self) -> None:
        base = self.fusion.base_ldr
        normal = render_adjustments(base, 1.0, 1.0, 1.0)
        brighter = render_adjustments(base, 1.18, 1.0, 1.0)
        saturated = render_adjustments(base, 1.0, 1.45, 1.0)
        sharper = render_adjustments(base, 1.0, 1.0, 1.35)
        self.assertGreater(float(brighter.mean()), float(normal.mean()) + 2.0)

        normal_hsv = cv2.cvtColor(normal, cv2.COLOR_RGB2HSV)
        saturated_hsv = cv2.cvtColor(saturated, cv2.COLOR_RGB2HSV)
        self.assertGreater(
            float(saturated_hsv[..., 1].mean()),
            float(normal_hsv[..., 1].mean()) + 2.0,
        )

        normal_gray = cv2.cvtColor(normal, cv2.COLOR_RGB2GRAY)
        sharper_gray = cv2.cvtColor(sharper, cv2.COLOR_RGB2GRAY)
        normal_edges = cv2.Laplacian(normal_gray, cv2.CV_32F).var()
        sharper_edges = cv2.Laplacian(sharper_gray, cv2.CV_32F).var()
        self.assertGreater(float(sharper_edges), float(normal_edges))

    def test_rotation_alignment_uses_similarity(self) -> None:
        rng = np.random.default_rng(8)
        height, width = 360, 480
        base = (rng.random((height, width, 3)) * 255).astype(np.uint8)
        base = cv2.GaussianBlur(base, (0, 0), 1.2)
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), 0.9, 1.003)
        matrix[0, 2] += 4
        matrix[1, 2] -= 3
        moved = cv2.warpAffine(
            base,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        aligned, ok, _ = _align([base, moved], 0, None)
        self.assertTrue(ok)
        self.assertLess(aligned[0].shape[0], height)
        self.assertLess(aligned[0].shape[1], width)
        first = cv2.cvtColor(aligned[0], cv2.COLOR_RGB2GRAY)
        second = cv2.cvtColor(aligned[1], cv2.COLOR_RGB2GRAY)
        edge_first = cv2.magnitude(
            cv2.Scharr(first, cv2.CV_32F, 1, 0),
            cv2.Scharr(first, cv2.CV_32F, 0, 1),
        )
        edge_second = cv2.magnitude(
            cv2.Scharr(second, cv2.CV_32F, 1, 0),
            cv2.Scharr(second, cv2.CV_32F, 0, 1),
        )
        correlation = float(np.corrcoef(edge_first.ravel(), edge_second.ravel())[0, 1])
        self.assertGreater(correlation, 0.9)

    def test_subpixel_translation_preserves_texture(self) -> None:
        rng = np.random.default_rng(12)
        height, width = 260, 340
        base = (rng.random((height, width, 3)) * 255).astype(np.uint8)
        base = cv2.GaussianBlur(base, (0, 0), 1.0)
        moved = cv2.warpAffine(
            base,
            np.float32([[1, 0, 2.35], [0, 1, -3.7]]),
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        aligned, ok, shift = _align([base, moved], 0, None)
        self.assertTrue(ok)
        self.assertGreater(shift, 2.0)
        first = cv2.cvtColor(aligned[0], cv2.COLOR_RGB2GRAY)
        second = cv2.cvtColor(aligned[1], cv2.COLOR_RGB2GRAY)
        first_edges = cv2.magnitude(
            cv2.Scharr(first, cv2.CV_32F, 1, 0),
            cv2.Scharr(first, cv2.CV_32F, 0, 1),
        )
        second_edges = cv2.magnitude(
            cv2.Scharr(second, cv2.CV_32F, 1, 0),
            cv2.Scharr(second, cv2.CV_32F, 0, 1),
        )
        correlation = float(
            np.corrcoef(first_edges.ravel(), second_edges.ravel())[0, 1]
        )
        self.assertGreater(correlation, 0.96)

    def test_local_texture_refinement_corrects_parallax(self) -> None:
        rng = np.random.default_rng(20)
        height, width = 900, 1200
        base = (rng.random((height, width, 3)) * 255).astype(np.uint8)
        base = cv2.GaussianBlur(base, (0, 0), 1.2)
        x, y = np.meshgrid(
            np.arange(width, dtype=np.float32),
            np.arange(height, dtype=np.float32),
        )
        # Smooth depth-dependent displacement, not a single global shift.
        field_x = 8.0 * (y / (height - 1) - 0.5)
        field_y = 6.0 * (x / (width - 1) - 0.5)
        moved = cv2.remap(
            base,
            x + field_x,
            y + field_y,
            interpolation=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        before = _texture_correlation(base, moved)
        refined = _refine_local_texture([base, moved], 0, None)
        after = _texture_correlation(base, refined[1])
        self.assertGreater(after, before + 0.02)

    def test_perspective_alignment_uses_homography(self) -> None:
        rng = np.random.default_rng(16)
        height, width = 360, 480
        base = (rng.random((height, width, 3)) * 255).astype(np.uint8)
        base = cv2.GaussianBlur(base, (0, 0), 1.1)
        source = np.float32(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]
        )
        target = np.float32(
            [[4, 2], [width - 7, 1], [width - 2, height - 5], [1, height - 8]]
        )
        matrix = cv2.getPerspectiveTransform(source, target)
        moved = cv2.warpPerspective(
            base,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        aligned, ok, _ = _align([base, moved], 0, None)
        self.assertTrue(ok)
        first = cv2.cvtColor(aligned[0], cv2.COLOR_RGB2GRAY)
        second = cv2.cvtColor(aligned[1], cv2.COLOR_RGB2GRAY)
        first_edges = cv2.magnitude(
            cv2.Scharr(first, cv2.CV_32F, 1, 0),
            cv2.Scharr(first, cv2.CV_32F, 0, 1),
        )
        second_edges = cv2.magnitude(
            cv2.Scharr(second, cv2.CV_32F, 1, 0),
            cv2.Scharr(second, cv2.CV_32F, 0, 1),
        )
        correlation = float(
            np.corrcoef(first_edges.ravel(), second_edges.ravel())[0, 1]
        )
        self.assertGreater(correlation, 0.9)

    def test_invalid_bracket_size(self) -> None:
        with self.assertRaises(HDRMergeError):
            process_bracket(SAMPLES[:1], MergeSettings(max_dim=500))

    def test_export_formats(self) -> None:
        jpg = save_result(self.fusion, OUTPUT / "_test_result.jpg")
        png = save_result(self.fusion, OUTPUT / "_test_result.png")
        tif = save_result(self.fusion, OUTPUT / "_test_result.tif")
        hdr = save_result(self.hdr, OUTPUT / "_test_result.hdr")
        for path in (jpg, png, tif, hdr):
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 1000, path)
        loaded = cv2.imread(str(hdr), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.dtype, np.float32)
        self.assertEqual(loaded.shape[:2], (self.hdr.height, self.hdr.width))

    def test_fusion_cannot_export_hdr(self) -> None:
        with self.assertRaises(HDRMergeError):
            save_result(self.fusion, OUTPUT / "_test_bad.hdr")

    @classmethod
    def tearDownClass(cls) -> None:
        for name in ("_test_result.jpg", "_test_result.png", "_test_result.tif", "_test_result.hdr"):
            try:
                (OUTPUT / name).unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    unittest.main()
