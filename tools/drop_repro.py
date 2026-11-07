"""Reproduce the native drop path and measure UI responsiveness."""

from __future__ import annotations

import ctypes
import faulthandler
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".vendor"))
sys.path.insert(0, str(ROOT))

from hdrstudio.drop_target import WM_DROPFILES  # noqa: E402
from hdrstudio.gui import HDRStudioApp  # noqa: E402
from tests.test_drop_target import make_hdrop  # noqa: E402

faulthandler.enable()


def main() -> None:
    root = tk.Tk()
    app = HDRStudioApp(root)
    root.update()
    for _ in range(10):
        root.update()
        time.sleep(0.01)
    files = [str(p.resolve()) for p in sorted((ROOT / "照片对齐训练用例").glob("*.jpg"))]
    hdrop = make_hdrop(files)
    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    print("sending WM_DROPFILES", flush=True)
    user32.SendMessageW(
        wintypes.HWND(app.drop_canvas.winfo_id()), WM_DROPFILES, hdrop, 0
    )
    print("returned from SendMessage", flush=True)
    deadline = time.time() + 10
    last = time.perf_counter()
    max_gap = 0.0
    while time.time() < deadline and len(app.items) < 5:
        root.update()
        now = time.perf_counter()
        max_gap = max(max_gap, now - last)
        last = now
        time.sleep(0.01)
    print("items", len(app.items), "max event-loop gap", round(max_gap, 3), flush=True)
    for item in app.items:
        print(item.path.name, item.info.width, item.info.height, flush=True)
    print("importing", app._importing, "busy", app._busy, flush=True)
    root.destroy()


if __name__ == "__main__":
    main()
