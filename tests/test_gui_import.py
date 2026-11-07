"""GUI import path tests: async loading and duplicate handling."""

from __future__ import annotations

import time
import tkinter as tk
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".vendor"))
sys.path.insert(0, str(ROOT))

from hdrstudio.gui import HDRStudioApp  # noqa: E402

SAMPLES = sorted((ROOT / "samples").glob("bracket_*.jpg"))


class GuiImportTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()
        self.app = HDRStudioApp(self.root)
        self.root.update()

    def tearDown(self) -> None:
        if getattr(self, "app", None) is not None:
            self.app._closed = True
        if getattr(self, "root", None) is not None:
            self.root.destroy()

    def _pump_until(self, predicate, timeout: float = 8.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("timed out waiting for the GUI import worker")

    def test_import_is_async_and_completes(self) -> None:
        self.app._add_file_paths([str(SAMPLES[0]), str(SAMPLES[1])])
        self.assertTrue(self.app._importing)
        self._pump_until(
            lambda: not self.app._importing and len(self.app.items) == 2
        )
        self.assertEqual(len(self.app.items), 2)
        self.assertIsNone(self.app._import_queue)
        self.assertFalse(self.app._busy)
        self.assertEqual(self.app.items[0].info.width, 1800)
        self.assertEqual(self.app.items[0].photo.width(), 78)
        self.assertIn("2 张曝光已就绪", self.app.status_label.cget("text"))

    def test_duplicate_is_skipped_without_touching_list(self) -> None:
        self.app._add_file_paths([str(SAMPLES[0]), str(SAMPLES[1])])
        self._pump_until(
            lambda: not self.app._importing and len(self.app.items) == 2
        )
        before = [item.path for item in self.app.items]
        self.app._add_file_paths([str(SAMPLES[0])])
        self.root.update()
        self.assertEqual([item.path for item in self.app.items], before)
        self.assertIn("已经在曝光序列中", self.app.status_label.cget("text"))


if __name__ == "__main__":
    unittest.main()
