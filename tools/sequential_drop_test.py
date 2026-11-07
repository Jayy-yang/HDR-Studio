import ctypes
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, ".vendor")
sys.path.insert(0, ".")

from hdrstudio.drop_target import WM_DROPFILES
from hdrstudio.gui import HDRStudioApp
from tests.test_drop_target import make_hdrop

files = [str(p.resolve()) for p in sorted(Path("照片对齐训练用例").glob("*.jpg"))]
root = tk.Tk()
app = HDRStudioApp(root)
root.update()


def drop(paths):
    hdrop = make_hdrop(paths)
    ctypes.windll.user32.SendMessageW(
        wintypes.HWND(app.drop_canvas.winfo_id()), WM_DROPFILES, hdrop, 0
    )


def wait(n, timeout=10):
    end = time.time() + timeout
    while time.time() < end and (app._importing or len(app.items) < n):
        root.update()
        time.sleep(0.01)


drop(files[:3])
wait(3)
print("after 3:", len(app.items), app._importing)
drop(files[:2] + files[2:5])
wait(5)
print("after 5:", len(app.items), app.status_label.cget("text"))
drop(files[5:])
root.update()
print("6th:", len(app.items), app.status_label.cget("text"))
app._closed = True
root.destroy()
print("ok")
