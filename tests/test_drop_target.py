"""Native WM_DROPFILES smoke test (Windows only)."""

from __future__ import annotations

import ctypes
import sys
import time
import tkinter as tk
import unittest
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hdrstudio.drop_target import WM_DROPFILES, enable_file_drop  # noqa: E402


class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


def make_hdrop(paths: list[str]) -> int:
    data = ("\0".join(paths) + "\0\0").encode("utf-16-le")
    header = ctypes.sizeof(DROPFILES)
    total = header + len(data)
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    handle = kernel32.GlobalAlloc(0x0042, total)
    pointer = kernel32.GlobalLock(handle)
    if not handle or not pointer:
        raise OSError("GlobalAlloc/GlobalLock failed")
    dropfiles = DROPFILES.from_address(pointer)
    dropfiles.pFiles = header
    dropfiles.fWide = True
    ctypes.memmove(pointer + header, data, len(data))
    kernel32.GlobalUnlock(handle)
    return int(handle)


@unittest.skipUnless(sys.platform == "win32", "Windows-only drag and drop")
class DropTargetTests(unittest.TestCase):
    def test_wm_dropfiles_callback(self) -> None:
        try:
            root = tk.Tk()
            root.geometry("300x200")
            canvas = tk.Canvas(root, width=200, height=100)
            canvas.pack()
            root.update()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        received: list[list[str]] = []
        try:
            self.assertTrue(
                enable_file_drop(canvas, lambda paths: received.append(paths))
            )
            files = [
                str((ROOT / "samples" / "bracket_01_dark.jpg").resolve()),
                str((ROOT / "samples" / "bracket_03_bright.jpg").resolve()),
            ]
            hdrop = make_hdrop(files)
            user32 = ctypes.windll.user32
            user32.SendMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            user32.SendMessageW(
                wintypes.HWND(canvas.winfo_id()),
                WM_DROPFILES,
                hdrop,
                0,
            )
            deadline = time.time() + 2.0
            while not received and time.time() < deadline:
                root.update()
                time.sleep(0.02)
            self.assertTrue(received, "drop callback was not invoked")
            self.assertEqual([Path(path).name for path in received[0]], [
                "bracket_01_dark.jpg",
                "bracket_03_bright.jpg",
            ])
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
