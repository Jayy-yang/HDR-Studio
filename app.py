#!/usr/bin/env python3
"""Launch HDR Studio.

Double-click 启动HDR工具.bat on Windows, or run:
    python app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR
SELF_TEST = "--self-test" in sys.argv


def _ensure_windows_admin() -> None:
    """Ask Windows for elevation before creating the GUI.

    Double-clicking the .bat also self-elevates, but this guard keeps direct
    ``python app.py`` launches consistent.
    """
    if os.name != "nt":
        return
    import ctypes

    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        return

    import subprocess

    if getattr(sys, "frozen", False):
        executable = sys.executable
        parameters = ""
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = str(pythonw if pythonw.exists() else Path(sys.executable))
        parameters = subprocess.list2cmdline([str(ROOT / "app.py")])
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            str(ROOT),
            1,
        )
    except Exception:
        result = 0
    if result <= 32:
        try:
            import tkinter as tk
            from tkinter import messagebox

            window = tk.Tk()
            window.withdraw()
            messagebox.showwarning(
                "需要管理员权限",
                "HDR Studio 需要管理员权限才能启动。\n\n"
                "请在弹出的 UAC 提示中选择“是”；如果取消，程序将退出。",
                parent=window,
            )
            window.destroy()
        except Exception:
            pass
    raise SystemExit(0)


if not SELF_TEST:
    _ensure_windows_admin()

# A bundled runtime folder lets the app run on machines where pip could not be
# used; normal installations simply fall back to site-packages.
VENDOR = ROOT / ".vendor"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))

try:
    import cv2  # noqa: F401
    from PIL import Image  # noqa: F401
except ModuleNotFoundError:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "缺少图像依赖",
        "HDR Studio 需要 OpenCV 和 Pillow。\n\n"
        "请在项目目录中运行：\n"
        "  pip install -r requirements.txt\n\n"
        "或双击「启动HDR工具.bat」完成自动准备。",
        parent=root,
    )
    root.destroy()
    raise SystemExit(1)

from hdrstudio.gui import ASSETS, main  # noqa: E402


def _run_self_test() -> None:
    """Verify the frozen bundle can start without opening the full UI."""
    import tkinter as tk

    required = ("logo.ico", "logo.png", "empty_list.png", "empty_preview.png")
    missing = [name for name in required if not (ASSETS / name).is_file()]
    if missing:
        raise RuntimeError(f"missing bundled assets: {', '.join(missing)}")

    probe = tk.Tk()
    probe.withdraw()
    probe.update_idletasks()
    probe.destroy()

    marker = APP_DIR / "hdrstudio_self_test.txt"
    marker.write_text(
        "HDR Studio self-test OK\n"
        f"frozen={getattr(sys, 'frozen', False)}\n"
        f"assets={ASSETS}\n"
        f"python={sys.version}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    if SELF_TEST:
        try:
            _run_self_test()
        except Exception:
            import traceback

            details = traceback.format_exc()
            try:
                (APP_DIR / "hdrstudio_self_test_error.log").write_text(
                    details, encoding="utf-8"
                )
            except OSError:
                pass
            raise
        raise SystemExit(0)

    try:
        main()
    except Exception:
        import traceback

        details = traceback.format_exc()
        try:
            (ROOT / "hdrstudio_error.log").write_text(details, encoding="utf-8")
        except OSError:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox

            window = tk.Tk()
            window.withdraw()
            last_line = details.splitlines()[-1] if details.splitlines() else "Unknown error"
            messagebox.showerror(
                "HDR Studio 启动失败",
                "程序遇到了一个未处理的错误。\n\n"
                "详细信息已写入 hdrstudio_error.log。\n\n"
                + last_line,
                parent=window,
            )
            window.destroy()
        except Exception:
            pass
        raise
