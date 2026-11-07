"""Native Windows file drop target for a Tk widget.

Tkinter has no built-in drag-and-drop support.  This module registers a single
Tk widget (a Canvas with no child HWNDs) as a classic ``WM_DROPFILES`` target.
For elevated processes, UIPI normally blocks drops from Explorer; allowing
``WM_DROPFILES``/``WM_COPYGLOBALDATA`` through the window message filter is the
practical bridge, as also used by other elevated desktop tools.
"""

from __future__ import annotations

import ctypes
import queue
import sys
import traceback
from ctypes import wintypes
from typing import Callable

WM_DROPFILES = 0x0233
WM_COPYDATA = 0x004A
WM_COPYGLOBALDATA = 0x0049
WM_NCDESTROY = 0x0082
GWLP_WNDPROC = -4
MSGFLT_ALLOW = 1
MSGFLT_ADD = 1


def _read_drop_files(hdrop: int) -> list[str]:
    shell32 = ctypes.windll.shell32
    shell32.DragQueryFileW.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPWSTR,
        wintypes.UINT,
    ]
    shell32.DragQueryFileW.restype = wintypes.UINT
    count = int(shell32.DragQueryFileW(wintypes.HANDLE(hdrop), 0xFFFFFFFF, None, 0))
    paths: list[str] = []
    for index in range(count):
        length = int(shell32.DragQueryFileW(wintypes.HANDLE(hdrop), index, None, 0))
        if length <= 0:
            continue
        buffer = ctypes.create_unicode_buffer(length + 1)
        copied = int(
            shell32.DragQueryFileW(
                wintypes.HANDLE(hdrop), index, buffer, length + 1
            )
        )
        if copied > 0:
            paths.append(buffer.value)
    return paths


def _allow_message(hwnd: int, message: int) -> None:
    user32 = ctypes.windll.user32
    try:
        filter_ex = user32.ChangeWindowMessageFilterEx
        filter_ex.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        filter_ex.restype = wintypes.BOOL
        filter_ex(wintypes.HWND(hwnd), message, MSGFLT_ALLOW, None)
    except Exception:
        pass


def enable_file_drop(
    widget,
    callback: Callable[[list[str]], None],
) -> bool:
    """Install a WM_DROPFILES handler on a Tk widget.

    The widget should be a Canvas with no child native windows, so Explorer's
    drop lands on its HWND directly.  Returns ``True`` on success.
    """
    if sys.platform != "win32":
        return False
    if getattr(widget, "_hdr_drop_enabled", False):
        return True
    try:
        hwnd = int(widget.winfo_id())
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32

        for message in (WM_DROPFILES, WM_COPYDATA, WM_COPYGLOBALDATA):
            _allow_message(hwnd, message)

        # Process-wide filter as well; harmless on modern Windows and helps
        # with some shell versions.
        try:
            user32.ChangeWindowMessageFilter.argtypes = [
                wintypes.UINT,
                wintypes.DWORD,
            ]
            user32.ChangeWindowMessageFilter.restype = wintypes.BOOL
            user32.ChangeWindowMessageFilter(WM_DROPFILES, MSGFLT_ADD)
            user32.ChangeWindowMessageFilter(WM_COPYGLOBALDATA, MSGFLT_ADD)
        except Exception:
            pass

        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell32.DragAcceptFiles.restype = None
        shell32.DragAcceptFiles(wintypes.HWND(hwnd), True)

        shell32.DragFinish.argtypes = [wintypes.HANDLE]
        shell32.DragFinish.restype = None

        # Never call Tk from inside a native WNDPROC.  Explorer can re-enter the
        # message loop while the drop is being dispatched; invoking Python/Tk
        # there is a common source of hard crashes.  Queue the paths and let a
        # normal Tk timer drain them.
        pending: queue.SimpleQueue[list[str]] = queue.SimpleQueue()
        pump_state = {"after_id": "", "stopped": False}

        def _schedule_pump() -> None:
            if pump_state["stopped"]:
                return
            try:
                if not widget.winfo_exists():
                    return
                pump_state["after_id"] = widget.after(30, _pump)
            except Exception:
                pump_state["stopped"] = True

        def _pump() -> None:
            pump_state["after_id"] = ""
            if pump_state["stopped"]:
                return
            try:
                if not widget.winfo_exists():
                    pump_state["stopped"] = True
                    return
                try:
                    paths = pending.get_nowait()
                except queue.Empty:
                    pass
                else:
                    try:
                        callback(paths)
                    except Exception:
                        traceback.print_exc()
            except Exception:
                pump_state["stopped"] = True
                return
            _schedule_pump()

        def _stop_pump(_event=None) -> None:
            pump_state["stopped"] = True
            after_id = pump_state["after_id"]
            pump_state["after_id"] = ""
            if after_id:
                try:
                    widget.after_cancel(after_id)
                except Exception:
                    pass

        # Cancel the timer before Tk tears down the widget.  Otherwise the
        # pending "after" script points at a deleted Tcl command and Tk prints
        # ``invalid command name ..._pump`` during shutdown.
        try:
            widget.bind("<Destroy>", _stop_pump, add="+")
        except Exception:
            pass
        _schedule_pump()

        wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )

        try:
            get_long = user32.GetWindowLongPtrW
        except AttributeError:
            get_long = user32.GetWindowLongW
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_void_p
        old_proc = get_long(wintypes.HWND(hwnd), GWLP_WNDPROC)
        if not old_proc:
            raise OSError("GetWindowLongPtrW failed")

        try:
            set_long = user32.SetWindowLongPtrW
        except AttributeError:
            set_long = user32.SetWindowLongW
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_long.restype = ctypes.c_void_p

        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        user32.CallWindowProcW.restype = ctypes.c_ssize_t

        def _wndproc(win_hwnd, message, wparam, lparam):
            try:
                if message == WM_DROPFILES:
                    paths: list[str] = []
                    try:
                        paths = _read_drop_files(int(wparam))
                    finally:
                        try:
                            shell32.DragFinish(wintypes.HANDLE(wparam))
                        except Exception:
                            pass
                    if paths:
                        pending.put_nowait(paths)
                    return 0
                if message == WM_NCDESTROY:
                    try:
                        set_long(
                            wintypes.HWND(win_hwnd),
                            GWLP_WNDPROC,
                            ctypes.c_void_p(old_proc),
                        )
                    except Exception:
                        pass
                return user32.CallWindowProcW(
                    ctypes.c_void_p(old_proc),
                    wintypes.HWND(win_hwnd),
                    message,
                    wparam,
                    lparam,
                )
            except Exception:
                return user32.CallWindowProcW(
                    ctypes.c_void_p(old_proc),
                    wintypes.HWND(win_hwnd),
                    message,
                    wparam,
                    lparam,
                )

        proc = wndproc_type(_wndproc)
        set_long(
            wintypes.HWND(hwnd),
            GWLP_WNDPROC,
            ctypes.cast(proc, ctypes.c_void_p),
        )
        widget._hdr_drop_enabled = True
        widget._hdr_drop_hwnd = hwnd
        widget._hdr_drop_old_proc = old_proc
        widget._hdr_drop_proc = proc
        return True
    except Exception:
        return False
