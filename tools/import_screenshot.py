"""Import five real 12 MP photos through the GUI and capture the result."""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, r".vendor")
sys.path.insert(0, ".")

from PIL import ImageGrab

from hdrstudio.gui import HDRStudioApp

ROOT = Path(__file__).resolve().parent.parent
DATASET = sorted((ROOT / "照片对齐训练用例").glob("*.jpg"))


def main() -> None:
    root = tk.Tk()
    app = HDRStudioApp(root)
    root.update()
    started = time.perf_counter()
    app._add_file_paths(DATASET)
    deadline = time.time() + 30
    while time.time() < deadline and (app._importing or len(app.items) < 5):
        root.update()
        time.sleep(0.01)
    for _ in range(20):
        root.update()
        time.sleep(0.01)
    elapsed = time.perf_counter() - started
    print("items", len(app.items), "elapsed", round(elapsed, 2))
    print("status", app.status_label.cget("text"))
    print("importing", app._importing, "queue", app._import_queue)
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    time.sleep(0.4)
    out = ROOT / "docs" / "gui_import_5.png"
    ImageGrab.grab(window=root.winfo_id()).save(out)
    print("saved", out)
    root.destroy()


if __name__ == "__main__":
    main()
