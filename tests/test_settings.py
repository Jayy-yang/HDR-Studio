"""Tests for the small persistent preferences store."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hdrstudio.settings as settings_module  # noqa: E402
from hdrstudio.settings import (  # noqa: E402
    DEFAULT_OUTPUT_SIZE,
    AppSettings,
    config_path,
    initial_output_size,
    load_app_settings,
    save_app_settings,
)

SETTINGS_FILE = Path(__file__).resolve().parent / "_test_settings.json"
SETTINGS_BLOCKER = Path(__file__).resolve().parent / "_not_a_directory"


class SettingsTests(unittest.TestCase):
    def tearDown(self) -> None:
        for path in (
            SETTINGS_FILE,
            SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp"),
            SETTINGS_BLOCKER,
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def test_defaults_when_missing(self) -> None:
        settings = load_app_settings(SETTINGS_FILE)
        self.assertTrue(settings.remember_size)
        self.assertEqual(settings.output_size, DEFAULT_OUTPUT_SIZE)
        self.assertEqual(initial_output_size(settings), DEFAULT_OUTPUT_SIZE)

    def test_roundtrip_remembered_size(self) -> None:
        save_app_settings(AppSettings(remember_size=True, output_size=3200), SETTINGS_FILE)
        loaded = load_app_settings(SETTINGS_FILE)
        self.assertTrue(loaded.remember_size)
        self.assertEqual(loaded.output_size, 3200)
        self.assertEqual(initial_output_size(loaded), 3200)

    def test_disabled_memory_starts_at_default(self) -> None:
        save_app_settings(AppSettings(remember_size=False, output_size=3200), SETTINGS_FILE)
        loaded = load_app_settings(SETTINGS_FILE)
        self.assertFalse(loaded.remember_size)
        self.assertEqual(initial_output_size(loaded), DEFAULT_OUTPUT_SIZE)

    def test_invalid_json_falls_back(self) -> None:
        SETTINGS_FILE.write_text("{broken json", encoding="utf-8")
        loaded = load_app_settings(SETTINGS_FILE)
        self.assertEqual(loaded.output_size, DEFAULT_OUTPUT_SIZE)
        self.assertTrue(loaded.remember_size)

    def test_invalid_size_falls_back(self) -> None:
        SETTINGS_FILE.write_text(
            json.dumps({"remember_size": True, "output_size": 9999}),
            encoding="utf-8",
        )
        loaded = load_app_settings(SETTINGS_FILE)
        self.assertEqual(loaded.output_size, DEFAULT_OUTPUT_SIZE)

    def test_atomic_write_leaves_no_temp(self) -> None:
        save_app_settings(AppSettings(remember_size=True, output_size=2400), SETTINGS_FILE)
        self.assertTrue(SETTINGS_FILE.is_file())
        self.assertFalse(SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp").exists())

    def test_fallback_when_appdata_is_blocked(self) -> None:
        SETTINGS_BLOCKER.write_text("not a directory", encoding="utf-8")
        primary = SETTINGS_BLOCKER / "settings.json"
        with patch.object(settings_module, "config_path", return_value=primary), patch.object(
            settings_module, "fallback_config_path", return_value=SETTINGS_FILE
        ):
            written = save_app_settings(
                AppSettings(remember_size=True, output_size=3200)
            )
            self.assertEqual(written, SETTINGS_FILE)
            loaded = load_app_settings()
        self.assertTrue(loaded.remember_size)
        self.assertEqual(loaded.output_size, 3200)

    def test_config_path_override(self) -> None:
        target = str(SETTINGS_FILE.resolve())
        with patch.dict(os.environ, {"HDRSTUDIO_CONFIG": target}):
            self.assertEqual(config_path(), SETTINGS_FILE.resolve())


if __name__ == "__main__":
    unittest.main()
