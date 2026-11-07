"""Populate the app with the synthetic bracket, merge, and capture a screenshot."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, r".vendor")
sys.path.insert(0, ".")

import tkinter as tk
from PIL import ImageGrab

from hdrstudio.gui import HDRStudioApp

ROOT = Path(__file__).resolve().parent.parent


def add_samples(app: HDRStudioApp, paths: list[Path] | None = None) -> None:
    """Add samples through the real async import path and wait for it."""
    selected_paths = paths or sorted((ROOT / "samples").glob("bracket_*.jpg"))
    before = len(app.items)
    app._add_file_paths([str(path) for path in selected_paths])
    deadline = time.time() + 15
    while time.time() < deadline and (
        app._importing or len(app.items) < before + len(selected_paths)
    ):
        app.root.update()
        time.sleep(0.01)
    app.root.update()


def main() -> None:
    root = tk.Tk()
    app = HDRStudioApp(root)
    samples = sorted((ROOT / "samples").glob("bracket_*.jpg"))
    add_samples(app, [samples[0], samples[-1]])
    root.update_idletasks()
    root.update()
    app._start_merge()

    deadline = time.time() + 60
    while time.time() < deadline and app.result is None:
        root.update()
        time.sleep(0.05)
    if app.result is None:
        print("merge did not finish")
        root.destroy()
        return
    # Let idle animations and layout settle.
    for _ in range(12):
        root.update()
        time.sleep(0.03)
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    time.sleep(0.35)
    root.update()
    hwnd = root.winfo_id()
    print("window", hwnd, root.winfo_geometry())
    try:
        image = ImageGrab.grab(window=hwnd)
    except Exception as exc:
        print("window grab failed:", exc)
        x = root.winfo_rootx()
        y = root.winfo_rooty()
        w = root.winfo_width()
        h = root.winfo_height()
        image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    out = ROOT / "docs" / "gui_screenshot.png"
    out.parent.mkdir(exist_ok=True)
    image.save(out)
    print("saved", out, image.size)
    root.destroy()


if __name__ == "__main__":
    main()
