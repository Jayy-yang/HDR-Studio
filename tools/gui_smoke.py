"""Non-interactive GUI behavior checks."""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, r".vendor")
sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui_screenshot import add_samples
from hdrstudio.gui import HDRStudioApp, MODE_HDR
from hdrstudio.widgets import ScrollFrame, show_message

ROOT = Path(__file__).resolve().parent.parent


def pump(root: tk.Tk, seconds: float = 0.2) -> None:
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def main() -> None:
    root = tk.Tk()
    app = HDRStudioApp(root)
    add_samples(app)
    pump(root)

    assert len(app.items) == 3, len(app.items)
    assert app.merge_button.enabled
    print("items", [item.path.name for item in app.items])

    # Sorting by exposure should be dark -> bright.
    app._sort_by_exposure()
    pump(root)
    print("sorted", [item.exposure_text for item in app.items])

    # Toggling HDR should show the tone controls.
    app._set_mode(MODE_HDR)
    pump(root)
    assert app.tone_section.winfo_ismapped(), "tone section should be visible"
    assert app.tone_switch.enabled
    print("hdr mode tone visible")

    # Right settings should be scrollable even over child widgets.
    settings = app.settings_scroll
    inner = settings.inner.winfo_children()[0]
    child = inner.winfo_children()[0]
    before = settings.canvas.yview()
    settings.canvas.yview_moveto(1.0)
    root.update()
    after = settings.canvas.yview()
    print("settings scroll", before, after)

    # Merge in HDR mode.
    app._start_merge()
    deadline = time.time() + 60
    while time.time() < deadline and app.result is None:
        root.update()
        time.sleep(0.03)
    assert app.result is not None
    print("merge", app.result.method_label, app.result.width, app.result.height)
    assert app.save_button.enabled
    assert app.result.radiance is not None
    assert max(app._preview_base_ldr.shape[:2]) <= 900, "preview should be <=900px"
    assert app._export_directory().is_dir()

    # Live finishing controls update the preview immediately, while the full
    # image is only re-rendered when exporting.
    before_mean = float(app.result.image.mean())
    app.brightness_var.set(1.22)
    app._on_slider_changed(1.22)
    pump(root, 0.25)
    assert app._preview_adjusted is not None, "live preview was not rendered"
    assert abs(float(app.result.image.mean()) - before_mean) < 0.5
    app._flush_live_adjustments()
    assert float(app.result.image.mean()) > before_mean + 1.0
    print("live detail preview + full-resolution flush ok")

    # Reference toggle.
    app._on_preview_mode("reference")
    pump(root)
    app._on_preview_mode("result")
    pump(root)
    print("preview toggle ok")

    # Export to both formats.
    from hdrstudio.core import save_result

    jpg = save_result(app.result, ROOT / "docs" / "smoke_export.jpg")
    hdr = save_result(app.result, ROOT / "docs" / "smoke_export.hdr")
    print("export", jpg.exists(), jpg.stat().st_size, hdr.exists(), hdr.stat().st_size)

    # Help dialog can be opened and closed.
    root.after(400, lambda: [w.destroy() for w in root.winfo_children() if isinstance(w, tk.Toplevel)])
    app._show_help()
    pump(root, 0.2)
    print("help dialog closed")

    # A warning dialog should also settle.
    root.after(300, lambda: [w.destroy() for w in root.winfo_children() if isinstance(w, tk.Toplevel)])
    show_message(root, "测试", "这是一个测试提示。", kind="warning")
    pump(root, 0.2)
    print("message dialog closed")

    # Remove one image and check result invalidation.
    app._select_item(1)
    app._remove_selected()
    pump(root)
    assert len(app.items) == 2
    assert app.result is None
    assert app.merge_button.enabled, "two-photo merge should be enabled"
    print("removed to two photos; merge enabled")

    # A two-photo bracket must merge too.
    app._start_merge()
    deadline = time.time() + 60
    while time.time() < deadline and app.result is None:
        root.update()
        time.sleep(0.03)
    assert app.result is not None
    print("two-photo merge", app.result.method_label, app.result.width, app.result.height)

    root.destroy()
    print("GUI SMOKE OK")


if __name__ == "__main__":
    main()
