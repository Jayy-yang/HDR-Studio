"""Tiny persisted preferences for HDR Studio.

Only the output-size memory is stored here.  The file lives in the user's
configuration directory, with a project-local fallback for sandboxed or
read-only installs.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OUTPUT_SIZE = 2400
VALID_OUTPUT_SIZES = (2400, 3200, 0)
DEFAULT_REMEMBER_SIZE = True
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class AppSettings:
    remember_size: bool = DEFAULT_REMEMBER_SIZE
    output_size: int = DEFAULT_OUTPUT_SIZE


def config_path() -> Path:
    """Return the user-level settings path.

    ``HDRSTUDIO_CONFIG`` can override it for tests or portable deployments.
    """
    override = os.environ.get("HDRSTUDIO_CONFIG")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "HDRStudio" / "settings.json"


def fallback_config_path() -> Path:
    """Project-local config used when the system config folder is not writable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "hdrstudio_settings.json"
    return PROJECT_ROOT / "hdrstudio_settings.json"


def _valid_size(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value in VALID_OUTPUT_SIZES:
        return value
    if isinstance(value, str):
        try:
            number = int(value)
        except ValueError:
            return None
        if number in VALID_OUTPUT_SIZES:
            return number
    return None


def load_app_settings(path: str | Path | None = None) -> AppSettings:
    """Load preferences, falling back to safe defaults on any problem."""
    defaults = AppSettings()
    candidates = (
        [Path(path)]
        if path is not None
        else [config_path(), fallback_config_path()]
    )
    for target in candidates:
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        remember = data.get("remember_size", defaults.remember_size)
        if not isinstance(remember, bool):
            remember = defaults.remember_size
        size = _valid_size(data.get("output_size"))
        if size is None:
            size = defaults.output_size
        return AppSettings(remember_size=remember, output_size=size)
    return defaults


def _write_settings(settings: AppSettings, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "remember_size": bool(settings.remember_size),
        "output_size": (
            settings.output_size
            if settings.output_size in VALID_OUTPUT_SIZES
            else DEFAULT_OUTPUT_SIZE
        ),
    }
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def save_app_settings(
    settings: AppSettings, path: str | Path | None = None
) -> Path:
    """Write preferences atomically and return the path actually used.

    If the user-level config folder is blocked, a project-local
    ``hdrstudio_settings.json`` is used instead.
    """
    if path is not None:
        target = Path(path)
        _write_settings(settings, target)
        return target

    primary = config_path()
    try:
        _write_settings(settings, primary)
        return primary
    except OSError as primary_error:
        fallback = fallback_config_path()
        if fallback == primary:
            raise
        try:
            _write_settings(settings, fallback)
            return fallback
        except OSError:
            raise primary_error


def initial_output_size(settings: AppSettings) -> int:
    """The size to use at startup, honouring the remember switch."""
    if settings.remember_size and settings.output_size in VALID_OUTPUT_SIZES:
        return settings.output_size
    return DEFAULT_OUTPUT_SIZE
