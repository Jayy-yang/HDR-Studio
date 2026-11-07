"""HDR Studio — a local, dark-themed exposure bracket merger."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
from PIL import Image, ImageTk

from . import theme
from .core import (
    MODE_FUSION,
    MODE_HDR,
    SUPPORTED_EXTENSIONS,
    TONE_DETAIL,
    TONE_NATURAL,
    TONE_SOFT,
    HDRMergeError,
    ImageInfo,
    MergeResult,
    MergeSettings,
    format_exposure,
    process_bracket,
    read_image_preview,
    render_adjustments,
    save_result,
)
from .drop_target import enable_file_drop
from .settings import (
    AppSettings,
    initial_output_size,
    load_app_settings,
    save_app_settings,
)
from .widgets import (
    ImageListCard,
    ModalDialog,
    ModeCard,
    Pill,
    RoundedButton,
    ScrollFrame,
    SegmentedControl,
    SliderRow,
    StatusIndicator,
    ToggleSwitch,
    show_message,
)

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    BASE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS = BASE_DIR / "assets"
EXPORT_DIR = APP_DIR / "exports"
PREVIEW_MAX_DIM = 900

SIZE_OPTIONS: list[tuple[str, int]] = [
    ("长边 2400 px · 推荐", 2400),
    ("长边 3200 px · 精细", 3200),
    ("原始尺寸 · 较慢", 0),
]


def size_label_for(value: int) -> str:
    for label, size in SIZE_OPTIONS:
        if size == value:
            return label
    return SIZE_OPTIONS[0][0]


@dataclass
class ExposureItem:
    path: Path
    info: ImageInfo
    photo: ImageTk.PhotoImage
    brightness: float
    exposure_text: str
    source_text: str


class HDRStudioApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.items: list[ExposureItem] = []
        self.selected_index: int | None = None
        self.result: MergeResult | None = None
        self.result_settings: MergeSettings | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._busy = False
        self._closed = False
        self._job_token = 0
        self._queue: queue.Queue[tuple[Any, ...]] | None = None
        self._importing = False
        self._import_token = 0
        self._import_queue: queue.Queue[tuple[Any, ...]] | None = None
        self._import_after_id: str | None = None
        self._import_added = 0
        self._import_failed: list[str] = []
        self._import_duplicate_count = 0
        self._import_overflow_count = 0
        self._settings_dirty = False
        self._settings_changed_during_merge = False
        self._live_after_id: str | None = None
        self._preview_base_ldr: np.ndarray | None = None
        self._preview_adjusted: np.ndarray | None = None
        self._live_preview_dirty = False
        self.drop_supported = False
        self._drop_hover = False
        self.app_settings: AppSettings = load_app_settings()

        self._load_assets()
        self._configure_window()
        self._build_variables()
        self._build_ui()
        self._bind_shortcuts()
        self._refresh_all()
        # The native drop target is installed after the window is mapped.  Keep
        # the timer id so closing the window immediately cannot leave a pending
        # Tcl callback pointing at a destroyed widget.
        self._drop_after_id: str | None = self.root.after(120, self._enable_native_drop)
        self.root.bind("<Destroy>", self._on_root_destroy, add="+")

    # ------------------------------------------------------------------
    # Window / assets

    def _load_assets(self) -> None:
        self._icon_photo: ImageTk.PhotoImage | None = None
        self._logo_photo: ImageTk.PhotoImage | None = None
        self._empty_preview_photo: ImageTk.PhotoImage | None = None
        self._empty_list_photo: ImageTk.PhotoImage | None = None
        try:
            logo = Image.open(ASSETS / "logo.png").convert("RGBA")
            self._logo_photo = ImageTk.PhotoImage(
                logo.resize((46, 46), Image.Resampling.LANCZOS)
            )
            self._icon_photo = ImageTk.PhotoImage(
                logo.resize((64, 64), Image.Resampling.LANCZOS)
            )
        except Exception:
            pass
        try:
            empty_list = Image.open(ASSETS / "empty_list.png").convert("RGBA")
            self._empty_list_photo = ImageTk.PhotoImage(
                empty_list.resize((182, 123), Image.Resampling.LANCZOS)
            )
        except Exception:
            pass
        try:
            empty_preview = Image.open(ASSETS / "empty_preview.png").convert("RGBA")
            self._empty_preview_photo = ImageTk.PhotoImage(
                empty_preview.resize((258, 172), Image.Resampling.LANCZOS)
            )
        except Exception:
            pass

    def _configure_window(self) -> None:
        self.root.title("HDR Studio · 多曝光合成")
        self.root.configure(bg=theme.BG)
        if self._icon_photo:
            try:
                self.root.iconphoto(True, self._icon_photo)
            except tk.TclError:
                pass
        try:
            self.root.iconbitmap(default=str(ASSETS / "logo.ico"))
        except tk.TclError:
            pass
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1380, max(1180, screen_w - 120))
        height = min(880, max(760, screen_h - 140))
        x = max(20, (screen_w - width) // 2)
        y = max(20, (screen_h - height) // 2 - 18)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(1180, 760)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        theme.apply_ttk_styles(self.root)

    def _build_variables(self) -> None:
        self.mode_var = tk.StringVar(value=MODE_FUSION)
        self.tone_var = tk.StringVar(value=TONE_NATURAL)
        self.preview_var = tk.StringVar(value="result")
        self.align_var = tk.BooleanVar(value=True)
        self.deghost_var = tk.BooleanVar(value=False)
        initial_size = initial_output_size(self.app_settings)
        self.size_var = tk.StringVar(value=size_label_for(initial_size))
        self.remember_size_var = tk.BooleanVar(value=self.app_settings.remember_size)
        self.brightness_var = tk.DoubleVar(value=1.02)
        self.saturation_var = tk.DoubleVar(value=1.06)
        self.detail_var = tk.DoubleVar(value=1.0)

    # ------------------------------------------------------------------
    # UI construction

    def _build_ui(self) -> None:
        self._build_header()
        body = tk.Frame(self.root, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 0))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=326)
        body.grid_columnconfigure(1, weight=1, minsize=400)
        body.grid_columnconfigure(2, minsize=318)

        self.left_panel = self._make_panel(body)
        self.left_panel.configure(width=326)
        self.left_panel.pack_propagate(False)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.center_panel = self._make_panel(body)
        self.center_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 14))
        self.right_panel = self._make_panel(body)
        self.right_panel.configure(width=318)
        self.right_panel.pack_propagate(False)
        self.right_panel.grid(row=0, column=2, sticky="nsew")

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()
        self._build_footer()

    @staticmethod
    def _make_panel(parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=theme.SURFACE,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=theme.BG, height=86)
        header.pack(fill="x", padx=28, pady=(16, 4))
        header.pack_propagate(False)

        logo = tk.Label(header, bg=theme.BG, image=self._logo_photo)
        logo.pack(side="left", padx=(0, 14))
        brand = tk.Frame(header, bg=theme.BG)
        brand.pack(side="left", fill="y")
        brand_row = tk.Frame(brand, bg=theme.BG)
        brand_row.pack(anchor="w", pady=(9, 0))
        tk.Label(
            brand_row,
            text="HDR",
            bg=theme.BG,
            fg=theme.TEXT,
            font=theme.FONT_BRAND,
        ).pack(side="left")
        tk.Label(
            brand_row,
            text=" STUDIO",
            bg=theme.BG,
            fg=theme.ACCENT,
            font=theme.FONT_BRAND,
        ).pack(side="left")
        tk.Label(
            brand_row,
            text="  v1.0",
            bg=theme.BG,
            fg=theme.FAINT,
            font=theme.FONT_TINY,
        ).pack(side="left", padx=(8, 0), pady=(8, 0))
        tk.Label(
            brand,
            text="多曝光合成 · 把光留在画面里",
            bg=theme.BG,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
            anchor="w",
        ).pack(anchor="w", pady=(1, 0))

        right = tk.Frame(header, bg=theme.BG)
        right.pack(side="right", fill="y", pady=(12, 0))
        Pill(
            right,
            "●  本地处理 · 原片不上传",
            width=178,
            height=28,
            background=theme.SURFACE,
            foreground=theme.MUTED,
            border=theme.BORDER_SOFT,
            font=theme.FONT_TINY,
        ).pack(side="left", padx=(0, 10))
        self.help_button = RoundedButton(
            right,
            "?  使用指南",
            self._show_help,
            kind="ghost",
            height=34,
            width=108,
            font=theme.FONT_SMALL,
        )
        self.help_button.pack(side="left")

    def _panel_heading(
        self,
        panel: tk.Frame,
        number: str,
        title: str,
        subtitle: str,
    ) -> tk.Frame:
        wrap = tk.Frame(panel, bg=theme.SURFACE)
        wrap.pack(fill="x", padx=18, pady=(15, 10))
        row = tk.Frame(wrap, bg=theme.SURFACE)
        row.pack(fill="x")
        tk.Label(
            row,
            text=number,
            bg=theme.SURFACE,
            fg=theme.ACCENT,
            font=theme.FONT_MONO,
        ).pack(side="left", padx=(0, 8), pady=(2, 0))
        tk.Label(
            row,
            text=title,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=theme.FONT_TITLE,
        ).pack(side="left")
        tk.Label(
            wrap,
            text=subtitle,
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
            anchor="w",
        ).pack(anchor="w", padx=(28, 0), pady=(4, 0))
        tk.Frame(panel, bg=theme.BORDER_SOFT, height=1).pack(fill="x")
        return wrap

    def _build_left_panel(self) -> None:
        heading_row = self._panel_heading(
            self.left_panel,
            "01",
            "曝光序列",
            "添加 2–5 张不同曝光的照片，顺序不限",
        )
        self.count_pill = Pill(
            heading_row,
            "0 / 5",
            width=52,
            height=24,
            background=theme.ACCENT_SOFT,
            foreground=theme.ACCENT,
            font=theme.FONT_MONO,
        )
        self.count_pill.pack(side="right", pady=(1, 0))

        self.drop_canvas = tk.Canvas(
            self.left_panel,
            height=80,
            bg=theme.SURFACE_2,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.drop_canvas.pack(fill="x", padx=12, pady=(8, 2))
        self.drop_canvas.bind("<Configure>", lambda _event: self._draw_drop_zone())
        self.drop_canvas.bind("<Button-1>", lambda _event: self._add_images())
        self.drop_canvas.bind("<Enter>", self._drop_enter)
        self.drop_canvas.bind("<Leave>", self._drop_leave)

        self.list_scroll = ScrollFrame(self.left_panel, bg=theme.SURFACE)
        self.list_scroll.pack(fill="both", expand=True, padx=(8, 8), pady=(4, 2))
        self.list_inner = self.list_scroll.inner

        footer = tk.Frame(self.left_panel, bg=theme.SURFACE)
        footer.pack(fill="x", padx=16, pady=(8, 14))
        self.add_button = RoundedButton(
            footer,
            "＋  添加曝光照片",
            self._add_images,
            kind="primary",
            height=44,
            font=theme.FONT_BUTTON,
        )
        self.add_button.pack(fill="x")
        row = tk.Frame(footer, bg=theme.SURFACE)
        row.pack(fill="x", pady=(8, 0))
        self.sort_button = RoundedButton(
            row,
            "按曝光排序",
            self._sort_by_exposure,
            kind="secondary",
            height=32,
            font=theme.FONT_BUTTON_SMALL,
        )
        self.sort_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.clear_button = RoundedButton(
            row,
            "清空",
            self._clear_images,
            kind="ghost",
            height=32,
            width=66,
            font=theme.FONT_BUTTON_SMALL,
        )
        self.clear_button.pack(side="right", fill="x", padx=(4, 0))
        self.left_hint = tk.Label(
            footer,
            text="小提示：手持拍摄请保持稳定，曝光间隔 1–2 EV 效果更好。",
            bg=theme.SURFACE,
            fg=theme.FAINT,
            font=theme.FONT_TINY,
            justify="left",
            anchor="w",
            wraplength=282,
        )
        self.left_hint.pack(fill="x", pady=(9, 0))

    def _build_center_panel(self) -> None:
        heading_row = self._panel_heading(
            self.center_panel,
            "02",
            "合成预览",
            "查看合成结果，或切换回中间曝光参考",
        )
        self.preview_switch = SegmentedControl(
            heading_row,
            [("合成", "result"), ("参考", "reference")],
            self.preview_var,
            self._on_preview_mode,
            height=32,
            width=126,
            font=theme.FONT_BUTTON_SMALL,
            enabled=False,
        )
        self.preview_switch.pack(side="right")

        self.preview_holder = tk.Frame(self.center_panel, bg=theme.VIEW_BG)
        self.preview_holder.pack(fill="both", expand=True, padx=12, pady=(10, 0))
        self.preview_canvas = tk.Canvas(
            self.preview_holder,
            bg=theme.VIEW_BG,
            highlightthickness=0,
            bd=0,
        )
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.bind("<Configure>", lambda _event: self._render_preview())

        self.placeholder = tk.Frame(self.preview_holder, bg=theme.VIEW_BG)
        self.placeholder.place(relx=0.5, rely=0.46, anchor="center")
        if self._empty_preview_photo:
            tk.Label(
                self.placeholder,
                bg=theme.VIEW_BG,
                image=self._empty_preview_photo,
            ).pack()
        tk.Label(
            self.placeholder,
            text="等待曝光合成",
            bg=theme.VIEW_BG,
            fg=theme.TEXT,
            font=(theme.FONT_FAMILY, 12, "bold"),
        ).pack(pady=(8, 4))
        tk.Label(
            self.placeholder,
            text="添加 2–5 张照片，点击「开始合成」\n结果会显示在这里",
            bg=theme.VIEW_BG,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
            justify="center",
        ).pack()

        tk.Frame(self.center_panel, bg=theme.BORDER_SOFT, height=1).pack(
            fill="x", padx=12, pady=(10, 0)
        )
        info_bar = tk.Frame(self.center_panel, bg=theme.SURFACE, height=43)
        info_bar.pack(fill="x", padx=16)
        info_bar.pack_propagate(False)
        self.preview_info = tk.Label(
            info_bar,
            text="尚未合成",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
            anchor="w",
        )
        self.preview_info.pack(side="left", fill="y")
        self.preview_meta = tk.Label(
            info_bar,
            text="至少需要 2 张曝光照片",
            bg=theme.SURFACE,
            fg=theme.FAINT,
            font=theme.FONT_TINY,
            anchor="e",
        )
        self.preview_meta.pack(side="right", fill="y")
        self.warning_label = tk.Label(
            info_bar,
            text="",
            bg=theme.SURFACE,
            fg=theme.WARNING,
            font=theme.FONT_TINY,
            cursor="hand2",
        )
        self.warning_label.pack(side="right", fill="y", padx=(0, 12))
        self.warning_label.bind("<Button-1>", lambda _event: self._show_warnings())
        self.warning_label.pack_forget()

    def _build_right_panel(self) -> None:
        heading_row = self._panel_heading(
            self.right_panel,
            "03",
            "合成设置",
            "选择引擎、色调与处理精度",
        )
        self.reset_label = tk.Label(
            heading_row,
            text="重置",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
            cursor="hand2",
        )
        self.reset_label.pack(side="right", pady=(3, 0))
        self.reset_label.bind("<Button-1>", lambda _event: self._reset_settings())
        self.reset_label.bind("<Enter>", lambda _e: self.reset_label.configure(fg=theme.ACCENT))
        self.reset_label.bind("<Leave>", lambda _e: self.reset_label.configure(fg=theme.MUTED))

        # Pin the action below the scrollable settings so it is always visible.
        action = tk.Frame(self.right_panel, bg=theme.SURFACE)
        action.pack(side="bottom", fill="x", padx=18, pady=(4, 10))
        self.merge_button = RoundedButton(
            action,
            "开始合成",
            self._start_merge,
            kind="primary",
            height=44,
            font=(theme.FONT_FAMILY, 11, "bold"),
        )
        self.merge_button.pack(fill="x")
        tk.Label(
            action,
            text="全部处理均在本机完成 · 不上传任何照片",
            bg=theme.SURFACE,
            fg=theme.FAINT,
            font=theme.FONT_TINY,
        ).pack(pady=(4, 0))

        shell = tk.Frame(self.right_panel, bg=theme.SURFACE)
        shell.pack(fill="both", expand=True)
        self.settings_scroll = ScrollFrame(shell, bg=theme.SURFACE)
        self.settings_scroll.pack(fill="both", expand=True)
        content = tk.Frame(self.settings_scroll.inner, bg=theme.SURFACE)
        content.pack(fill="both", expand=True, padx=18, pady=(7, 4))

        self._section_label(content, "合成方式")
        self.fusion_card = ModeCard(
            content,
            "自然融合",
            "逐像素融合 · 保留现场光影",
            height=53,
            selected=True,
            command=lambda: self._set_mode(MODE_FUSION),
        )
        self.fusion_card.pack(fill="x", pady=(5, 3))
        self.hdr_card = ModeCard(
            content,
            "真实 HDR",
            "32 位亮度合成 · 可导 .hdr",
            height=53,
            selected=False,
            command=lambda: self._set_mode(MODE_HDR),
        )
        self.hdr_card.pack(fill="x")

        self.tone_section = tk.Frame(content, bg=theme.SURFACE)
        self.tone_section.pack(fill="x", pady=(9, 0))
        self._section_label(self.tone_section, "色调风格")
        self.tone_switch = SegmentedControl(
            self.tone_section,
            [("自然", TONE_NATURAL), ("细节", TONE_DETAIL), ("柔和", TONE_SOFT)],
            self.tone_var,
            self._on_tone_changed,
            height=31,
            font=theme.FONT_BUTTON_SMALL,
            enabled=False,
        )
        self.tone_switch.pack(fill="x", pady=(5, 0))
        self.tone_hint = tk.Label(
            self.tone_section,
            text="切换到真实 HDR 后可调整",
            bg=theme.SURFACE,
            fg=theme.FAINT,
            font=theme.FONT_TINY,
            anchor="w",
        )
        # The hint is intentionally not packed: keeping the settings compact
        # means all controls fit at the default window height.

        self._divider(content)
        self._section_label(content, "细节调整（实时）")
        self.brightness_row = SliderRow(
            content,
            "亮度",
            self.brightness_var,
            0.70,
            1.35,
            lambda value: f"{int(round(value * 100))}%",
            self._on_slider_changed,
            height=44,
        )
        self.brightness_row.pack(fill="x", pady=(2, 0))
        self.saturation_row = SliderRow(
            content,
            "饱和度",
            self.saturation_var,
            0.55,
            1.65,
            lambda value: f"{int(round(value * 100))}%",
            self._on_slider_changed,
            height=44,
        )
        self.saturation_row.pack(fill="x")
        self.detail_row = SliderRow(
            content,
            "细节",
            self.detail_var,
            0.50,
            1.60,
            lambda value: f"{int(round(value * 100))}%",
            self._on_slider_changed,
            height=44,
        )
        self.detail_row.pack(fill="x")

        self._divider(content)
        self._section_label(content, "处理选项")

        align_row = tk.Frame(content, bg=theme.SURFACE, height=28)
        align_row.pack(fill="x", pady=(3, 0))
        align_row.pack_propagate(False)
        self._option_text(align_row, "自动对齐").pack(side="left")
        self.align_toggle = ToggleSwitch(
            align_row, self.align_var, self._on_toggle_changed
        )
        self.align_toggle.pack(side="right")

        ghost_row = tk.Frame(content, bg=theme.SURFACE, height=28)
        ghost_row.pack(fill="x", pady=(1, 0))
        ghost_row.pack_propagate(False)
        self._option_text(ghost_row, "去除移动重影").pack(side="left")
        self.ghost_toggle = ToggleSwitch(
            ghost_row, self.deghost_var, self._on_toggle_changed
        )
        self.ghost_toggle.pack(side="right")

        size_row = tk.Frame(content, bg=theme.SURFACE)
        size_row.pack(fill="x", pady=(4, 0))
        self._option_text(size_row, "处理尺寸").pack(side="left", fill="y")
        self.size_combo = ttk.Combobox(
            size_row,
            textvariable=self.size_var,
            values=[label for label, _ in SIZE_OPTIONS],
            state="readonly",
            style="Dark.TCombobox",
            width=17,
            font=theme.FONT_TINY,
        )
        self.size_combo.pack(side="right")
        self.size_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_size_changed())
        index = [value for _, value in SIZE_OPTIONS].index(initial_output_size(self.app_settings))
        self.size_combo.current(index)

        memory_row = tk.Frame(content, bg=theme.SURFACE, height=28)
        memory_row.pack(fill="x", pady=(2, 0))
        memory_row.pack_propagate(False)
        tk.Label(
            memory_row,
            text="记住输出尺寸",
            bg=theme.SURFACE,
            fg=theme.TEXT_DIM,
            font=theme.FONT_SMALL,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            memory_row,
            text="下次启动沿用",
            bg=theme.SURFACE,
            fg=theme.FAINT,
            font=theme.FONT_TINY,
            anchor="w",
        ).pack(side="left", padx=(8, 0))
        self.remember_toggle = ToggleSwitch(
            memory_row,
            self.remember_size_var,
            self._on_remember_size_changed,
        )
        self.remember_toggle.pack(side="right")

    def _build_footer(self) -> None:
        tk.Frame(self.root, bg=theme.BORDER, height=1).pack(fill="x", pady=(12, 0))
        footer = tk.Frame(self.root, bg=theme.BG, height=64)
        footer.pack(fill="x", padx=28, pady=(10, 12))
        footer.pack_propagate(False)

        left = tk.Frame(footer, bg=theme.BG)
        left.pack(side="left", fill="both", expand=True)
        self.status_indicator = StatusIndicator(left)
        self.status_indicator.pack(side="left", padx=(0, 8))
        self.status_label = tk.Label(
            left,
            text="就绪 · 添加 2–5 张不同曝光的照片",
            bg=theme.BG,
            fg=theme.TEXT_DIM,
            font=theme.FONT_SMALL,
            anchor="w",
        )
        self.status_label.pack(side="left", fill="y")
        self.progress = ttk.Progressbar(
            left,
            style="HDR.Horizontal.TProgressbar",
            length=150,
            mode="determinate",
            maximum=100,
        )
        self.progress_label = tk.Label(
            left,
            text="0%",
            bg=theme.BG,
            fg=theme.ACCENT,
            font=theme.FONT_MONO,
        )

        right = tk.Frame(footer, bg=theme.BG)
        right.pack(side="right", fill="y")
        self.save_button = RoundedButton(
            right,
            "↓  导出图片",
            self._save_image,
            kind="outline",
            height=40,
            width=138,
            font=theme.FONT_BUTTON_SMALL,
            enabled=False,
        )
        self.save_button.pack(side="right")
        tk.Label(
            right,
            text="F5 合成   ·   Ctrl+S 导出",
            bg=theme.BG,
            fg=theme.FAINT,
            font=theme.FONT_TINY,
        ).pack(side="right", padx=(0, 14))

    def _section_label(self, parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=theme.SURFACE,
            fg=theme.TEXT_DIM,
            font=(theme.FONT_FAMILY, 9, "bold"),
            anchor="w",
        ).pack(fill="x")

    @staticmethod
    def _divider(parent: tk.Misc) -> None:
        tk.Frame(parent, bg=theme.BORDER_SOFT, height=1).pack(fill="x", pady=5)

    @staticmethod
    def _option_text(parent: tk.Misc, title: str, hint: str = "") -> tk.Frame:
        frame = tk.Frame(parent, bg=theme.SURFACE)
        tk.Label(
            frame,
            text=title,
            bg=theme.SURFACE,
            fg=theme.TEXT_DIM,
            font=theme.FONT_SMALL,
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))
        if hint:
            tk.Label(
                frame,
                text=hint,
                bg=theme.SURFACE,
                fg=theme.FAINT,
                font=theme.FONT_TINY,
                anchor="w",
            ).pack(anchor="w")
        return frame

    # ------------------------------------------------------------------
    # Keyboard / lifecycle

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self._add_images())
        self.root.bind("<Control-O>", lambda _event: self._add_images())
        self.root.bind("<Control-s>", lambda _event: self._save_image())
        self.root.bind("<Control-S>", lambda _event: self._save_image())
        self.root.bind("<F5>", lambda _event: self._start_merge())
        self.root.bind("<F1>", lambda _event: self._show_help())
        self.root.bind("<Delete>", lambda _event: self._remove_selected())

    def _cancel_drop_after(self) -> None:
        after_id = self._drop_after_id
        self._drop_after_id = None
        if after_id:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass

    def _cancel_import_after(self) -> None:
        after_id = self._import_after_id
        self._import_after_id = None
        if after_id:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass

    def _cancel_pending_timers(self) -> None:
        self._cancel_drop_after()
        self._cancel_import_after()

    def _on_root_destroy(self, event) -> None:
        if event.widget is self.root:
            self._cancel_pending_timers()

    def _on_close(self) -> None:
        if self._busy:
            if not show_message(
                self.root,
                "仍在合成",
                "当前还有合成任务在运行。现在退出会丢失本次处理结果，确定退出吗？",
                kind="warning",
                confirm=True,
                primary="退出",
            ):
                return
        self._closed = True
        self._cancel_pending_timers()
        self.root.destroy()

    # ------------------------------------------------------------------
    # State helpers

    def _refresh_all(self) -> None:
        self._rebuild_list()
        self._refresh_controls()
        self._update_preview_placeholder()

    def _refresh_controls(self) -> None:
        count = len(self.items)
        idle = not self._busy and not self._importing
        self.count_pill.set_text(f"{count} / 5")
        self.add_button.set_enabled(count < 5 and idle)
        self.sort_button.set_enabled(count > 1 and idle)
        self.clear_button.set_enabled(count > 0 and idle)
        self.save_button.set_enabled(self.result is not None and idle)
        self.preview_switch.set_enabled(self.result is not None and not self._importing)
        self.merge_button.set_enabled(2 <= count <= 5 and idle)
        if self._busy:
            self.merge_button.set_text("正在合成…")
        elif self._importing:
            self.merge_button.set_text("正在读取照片…")
        elif self.result is not None:
            self.merge_button.set_text("重新合成")
        else:
            self.merge_button.set_text("开始合成")
        if count == 0:
            self.preview_info.configure(text="尚未合成")
            self.preview_meta.configure(text="至少需要 2 张曝光照片")
        elif count < 2:
            self.preview_info.configure(text=f"还需 {2 - count} 张曝光照片")
            self.preview_meta.configure(text="曝光序列至少 2 张")
        elif self.result is None:
            self.preview_info.configure(text="已准备好合成")
            self.preview_meta.configure(text=f"{count} 张曝光 · 等待开始")
        self._draw_drop_zone()
        self._update_tone_state()

    def _set_status(self, text: str, kind: str = "idle") -> None:
        color = {
            "idle": theme.TEXT_DIM,
            "ok": theme.SUCCESS,
            "warning": theme.WARNING,
            "error": theme.DANGER,
            "busy": theme.TEXT_DIM,
        }.get(kind, theme.TEXT_DIM)
        self.status_label.configure(text=text, fg=color)
        if kind == "ok":
            self.status_indicator.set_idle(theme.SUCCESS)
        elif kind == "warning":
            self.status_indicator.set_idle(theme.WARNING)
        elif kind == "error":
            self.status_indicator.set_idle(theme.DANGER)
        elif kind != "busy":
            self.status_indicator.set_idle(theme.MUTED)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._settings_changed_during_merge = False
        if busy:
            self.progress.configure(value=0)
            self.progress_label.configure(text="0%")
            self.progress.pack(side="left", padx=(16, 8), pady=(0, 1))
            self.progress_label.pack(side="left", pady=(0, 1))
            self.status_indicator.set_busy()
        else:
            self.progress.pack_forget()
            self.progress_label.pack_forget()
        self._refresh_controls()

    def _set_progress(self, message: str, fraction: float) -> None:
        percentage = int(round(max(0.0, min(1.0, fraction)) * 100))
        self.status_label.configure(text=message, fg=theme.TEXT_DIM)
        self.progress.configure(value=percentage)
        self.progress_label.configure(text=f"{percentage}%")

    def _update_tone_state(self) -> None:
        is_hdr = self.mode_var.get() == MODE_HDR
        self.tone_switch.set_enabled(is_hdr)
        self.tone_hint.configure(
            text="可调整 HDR 的明暗压缩风格"
            if is_hdr
            else "切换到真实 HDR 后可调整"
        )
        if is_hdr:
            if not self.tone_section.winfo_ismapped():
                self.tone_section.pack(
                    fill="x", pady=(9, 0), after=self.hdr_card
                )
            self.tone_switch.refresh()
        else:
            self.tone_section.pack_forget()
        if hasattr(self, "settings_scroll"):
            self.root.after_idle(self.settings_scroll._update_scrollbar)

    def _mark_settings_dirty(self) -> None:
        if self._busy:
            self._settings_changed_during_merge = True
            return
        if self.result is not None:
            self._settings_dirty = True
            self.merge_button.set_text("重新合成")
            self._set_status("设置已更改 · 重新合成后生效", "warning")
            self.preview_meta.configure(text="设置已修改，等待重新合成")

    # ------------------------------------------------------------------
    # Exposure list

    def _enable_native_drop(self) -> None:
        self._drop_after_id = None
        if self._closed:
            return
        try:
            self.drop_supported = enable_file_drop(
                self.drop_canvas, self._on_files_dropped
            )
        except Exception:
            self.drop_supported = False
        self._draw_drop_zone()

    def _on_files_dropped(self, paths: list[str]) -> None:
        if self._closed:
            return
        self._add_file_paths(paths)

    def _drop_enter(self, _event) -> None:
        self._drop_hover = True
        self._draw_drop_zone()

    def _drop_leave(self, _event) -> None:
        self._drop_hover = False
        self._draw_drop_zone()

    def _draw_drop_zone(self) -> None:
        canvas = self.drop_canvas
        canvas.delete("all")
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 20 or height < 20:
            return
        active = len(self.items) < 5 and not self._busy and not self._importing
        hover = self._drop_hover and active
        theme.create_round_rect(
            canvas,
            1,
            1,
            width - 1,
            height - 1,
            10,
            fill=theme.SURFACE_3 if hover else theme.SURFACE_2,
            outline=theme.ACCENT if hover else theme.BORDER,
            width=1,
        )
        icon_color = theme.ACCENT if active else theme.FAINT
        canvas.create_text(
            27,
            height / 2 - 3,
            text="↓",
            fill=icon_color,
            font=(theme.FONT_FAMILY, 20, "bold"),
        )
        if self._busy:
            title = "正在合成，暂不能添加"
            subtitle = "完成后再拖入照片"
        elif self._importing:
            title = "正在读取照片…"
            subtitle = "请稍候，界面仍可响应"
        elif len(self.items) >= 5:
            title = "已达 5 张上限"
            subtitle = "移除一张后可继续导入"
        elif self.drop_supported:
            title = "拖入照片到这里"
            subtitle = "或点击选择 · JPG / PNG / TIFF / WEBP"
        else:
            title = "点击添加照片"
            subtitle = "支持 JPG / PNG / TIFF / WEBP"
        canvas.create_text(
            50,
            height / 2 - 11,
            text=title,
            anchor="w",
            fill=theme.TEXT if active else theme.MUTED,
            font=(theme.FONT_FAMILY, 10, "bold"),
        )
        canvas.create_text(
            50,
            height / 2 + 10,
            text=subtitle,
            anchor="w",
            fill=theme.FAINT,
            font=theme.FONT_TINY,
        )

    def _add_images(self) -> None:
        if self._busy or self._importing:
            return
        if len(self.items) >= 5:
            show_message(
                self.root,
                "已达上限",
                "最多支持 5 张曝光照片。请先移除一张，再添加新的照片。",
                kind="warning",
            )
            return
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="选择 2–5 张不同曝光的照片",
            filetypes=[
                (
                    "图片文件",
                    "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp",
                ),
                ("所有文件", "*.*"),
            ],
        )
        if paths:
            self._add_file_paths(paths)

    def _add_file_paths(self, paths: Sequence[str | Path]) -> None:
        if self._busy:
            self._set_status("正在合成，暂不能添加照片", "warning")
            return
        if self._importing:
            self._set_status("正在读取照片，请稍候…", "warning")
            return
        if len(self.items) >= 5:
            self._set_status("最多支持 5 张曝光照片，请先移除一张", "warning")
            return
        raw_paths = [Path(path) for path in paths]
        if not raw_paths:
            return

        existing = {str(item.path.resolve()).lower() for item in self.items}
        room = 5 - len(self.items)
        selected: list[Path] = []
        failed: list[str] = []
        skipped_duplicate = 0
        overflow = 0
        for path in raw_paths:
            key = str(path.resolve()).lower()
            if key in existing:
                skipped_duplicate += 1
                continue
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                failed.append(path.name)
                continue
            if len(selected) >= room:
                overflow += 1
                continue
            selected.append(path)
            existing.add(key)

        if not selected:
            if failed:
                show_message(
                    self.root,
                    "没有添加照片",
                    "以下文件无法读取：\n"
                    + "\n".join(f"· {name}" for name in failed[:6]),
                    kind="error",
                )
            elif skipped_duplicate:
                self._set_status("这些照片已经在曝光序列中", "warning")
            elif overflow:
                self._set_status("最多支持 5 张曝光照片，请先移除一张", "warning")
            return

        # Loading thumbnails and metadata happens on a worker thread.  A
        # 12 MP JPEG can otherwise freeze the Tk event loop for hundreds of
        # milliseconds per photo, which Windows reports as "无响应".
        self._import_token += 1
        token = self._import_token
        self._import_queue = queue.Queue()
        self._import_added = 0
        self._import_failed = failed
        self._import_duplicate_count = skipped_duplicate
        self._import_overflow_count = overflow
        self._set_importing(True)
        self._set_status(f"正在读取 1/{len(selected)} 张照片…", "busy")
        self.root.configure(cursor="watch")
        worker = threading.Thread(
            target=self._import_worker,
            args=(token, selected),
            daemon=True,
            name="hdr-import",
        )
        worker.start()
        self._import_after_id = self.root.after(35, self._poll_import_worker)

    def _set_importing(self, importing: bool) -> None:
        self._importing = importing
        if importing:
            self.progress.configure(value=0)
            self.progress_label.configure(text="0%")
            self.progress.pack(side="left", padx=(16, 8), pady=(0, 1))
            self.progress_label.pack(side="left", pady=(0, 1))
            self.status_indicator.set_busy()
        else:
            self.progress.pack_forget()
            self.progress_label.pack_forget()
        self._refresh_controls()

    def _import_worker(self, token: int, paths: Sequence[Path]) -> None:
        local_queue = self._import_queue
        if local_queue is None:
            return
        total = len(paths)
        try:
            for index, path in enumerate(paths, 1):
                if self._closed:
                    return
                local_queue.put(("progress", token, index, total, path.name))
                try:
                    preview = read_image_preview(path)
                except Exception as exc:
                    local_queue.put(("error", token, path.name, str(exc)))
                    continue
                local_queue.put(("item", token, path, preview))
        finally:
            local_queue.put(("done", token))

    def _poll_import_worker(self) -> None:
        self._import_after_id = None
        if self._closed or self._import_queue is None:
            return
        local_queue = self._import_queue
        token = self._import_token
        done = False
        while True:
            try:
                event = local_queue.get_nowait()
            except queue.Empty:
                break
            if event[1] != token:
                continue
            kind = event[0]
            if kind == "progress":
                _kind, _token, index, total, name = event
                self._set_status(f"正在读取 {index}/{total} · {name}…", "busy")
                self._set_progress(
                    f"正在读取 {index}/{total} · {name}…", index / max(1, total)
                )
            elif kind == "item":
                _kind, _token, path, preview = event
                self._append_import_item(path, preview)
            elif kind == "error":
                _kind, _token, name, message = event
                self._import_failed.append(f"{name}（{message}）")
            elif kind == "done":
                done = True

        if done:
            self._finish_import()
            return
        self._import_after_id = self.root.after(35, self._poll_import_worker)

    def _append_import_item(self, path: Path, preview) -> None:
        if self._closed:
            return
        info = preview.info
        exposure_text = (
            format_exposure(info.exposure_time)
            if info.exposure_time
            else "待估算"
        )
        source_text = "EXIF" if info.exposure_time else "自动"
        try:
            photo = ImageTk.PhotoImage(preview.thumbnail)
        except tk.TclError:
            return
        if self._import_added == 0 and self.result is not None:
            self._invalidate_result("曝光序列已更新")
        self.items.append(
            ExposureItem(
                path=path,
                info=info,
                photo=photo,
                brightness=preview.brightness,
                exposure_text=exposure_text,
                source_text=source_text,
            )
        )
        self._import_added += 1
        self.selected_index = len(self.items) - 1
        # Build the cards once, in _finish_import: rebuilding the whole list for
        # every thumbnail would create unnecessary Tk work between frames.
        self._refresh_controls()

    def _finish_import(self) -> None:
        self._import_queue = None
        self.root.configure(cursor="")
        self._set_importing(False)
        added = self._import_added
        failed = self._import_failed
        duplicate = self._import_duplicate_count
        overflow = self._import_overflow_count

        if added:
            self._invalidate_result("曝光序列已更新")
            self.selected_index = len(self.items) - 1
            self._rebuild_list()
            self.list_scroll.scroll_to_bottom()
        self._refresh_controls()

        details: list[str] = []
        if failed:
            details.append(f"{len(failed)} 个读取失败")
        if duplicate:
            details.append(f"{duplicate} 个重复跳过")
        if overflow:
            details.append(f"{overflow} 个超出上限")
        if added:
            if len(self.items) < 2:
                message = f"已添加 {added} 张 · 还需 {2 - len(self.items)} 张即可合成"
            elif len(self.items) == 5:
                message = "5 张曝光已就绪 · 点击「开始合成」"
            else:
                message = f"{len(self.items)} 张曝光已就绪 · 点击「开始合成」"
            if details:
                message += " · " + "，".join(details)
            self._set_status(message, "warning" if details else "ok")
        elif failed:
            show_message(
                self.root,
                "没有添加照片",
                "以下文件无法读取：\n"
                + "\n".join(f"· {name}" for name in failed[:6]),
                kind="error",
            )
            self._set_status("没有添加照片 · 读取失败", "error")
        elif duplicate:
            self._set_status("这些照片已经在曝光序列中", "warning")
        elif overflow:
            self._set_status("最多支持 5 张曝光照片，请先移除一张", "warning")

    def _remove_selected(self) -> None:
        if self._busy or self._importing or self.selected_index is None:
            return
        if not (0 <= self.selected_index < len(self.items)):
            return
        removed = self.items.pop(self.selected_index)
        if self.items:
            self.selected_index = min(self.selected_index, len(self.items) - 1)
        else:
            self.selected_index = None
        self._invalidate_result(f"已移除 {removed.path.name}")
        self._rebuild_list()
        self._refresh_controls()
        self._set_status(
            f"已移除 {removed.path.name}"
            + (
                f" · 还需 {2 - len(self.items)} 张"
                if len(self.items) < 2
                else ""
            ),
            "idle",
        )

    def _clear_images(self) -> None:
        if self._busy or self._importing or not self.items:
            return
        if not show_message(
            self.root,
            "清空曝光序列",
            f"将移除当前 {len(self.items)} 张照片，已生成的预览也会被清除。",
            kind="warning",
            confirm=True,
            primary="清空",
        ):
            return
        self.items.clear()
        self.selected_index = None
        self._invalidate_result("曝光序列已清空")
        self._rebuild_list()
        self._refresh_controls()
        self._set_status("已清空 · 添加 2–5 张照片开始合成", "idle")

    def _sort_by_exposure(self) -> None:
        if self._busy or self._importing or len(self.items) < 2:
            return
        selected_path = (
            self.items[self.selected_index].path
            if self.selected_index is not None
            and 0 <= self.selected_index < len(self.items)
            else None
        )
        if all(item.info.exposure_time for item in self.items):
            self.items.sort(key=lambda item: float(item.info.exposure_time or 0))
        else:
            self.items.sort(key=lambda item: item.brightness)
        if selected_path is not None:
            for index, item in enumerate(self.items):
                if item.path == selected_path:
                    self.selected_index = index
                    break
        self._invalidate_result("已按曝光排序")
        self._rebuild_list()
        self._refresh_controls()
        self._set_status(
            "已按曝光排序"
            + ("（依据 EXIF）" if all(item.info.exposure_time for item in self.items) else "（依据画面亮度估算）"),
            "ok",
        )

    def _select_item(self, index: int) -> None:
        self.selected_index = index
        self._rebuild_list(preserve_scroll=True)

    def _rebuild_list(self, preserve_scroll: bool = False) -> None:
        position = 0.0
        if preserve_scroll and hasattr(self, "list_scroll"):
            try:
                position = self.list_scroll.canvas.yview()[0]
            except tk.TclError:
                position = 0.0
        for child in self.list_inner.winfo_children():
            child.destroy()

        if not self.items:
            empty = tk.Frame(self.list_inner, bg=theme.SURFACE)
            empty.pack(fill="both", expand=True, pady=(24, 18), padx=10)
            tk.Label(
                empty,
                text="还没有曝光照片",
                bg=theme.SURFACE,
                fg=theme.TEXT,
                font=(theme.FONT_FAMILY, 11, "bold"),
            ).pack(pady=(0, 5))
            tk.Label(
                empty,
                text="将 2–5 张不同曝光的照片\n拖入上方区域，或点击下方按钮",
                bg=theme.SURFACE,
                fg=theme.MUTED,
                font=theme.FONT_SMALL,
                justify="center",
            ).pack()
        else:
            for index, item in enumerate(self.items):
                card = ImageListCard(
                    self.list_inner,
                    index=index + 1,
                    name=theme.truncate_name(item.path.name, 24),
                    exposure_text=item.exposure_text,
                    source_text=item.source_text,
                    thumbnail=item.photo,
                    selected=index == self.selected_index,
                    command=lambda i=index: self._select_item(i),
                    remove_command=lambda i=index: self._remove_index(i),
                )
                card.pack(fill="x", padx=6, pady=3)
        if preserve_scroll:
            self.root.after_idle(lambda: self.list_scroll.canvas.yview_moveto(position))

    def _remove_index(self, index: int) -> None:
        if self._busy or self._importing:
            return
        self.selected_index = index
        self._remove_selected()

    def _invalidate_result(self, message: str) -> None:
        if self._live_after_id is not None:
            try:
                self.root.after_cancel(self._live_after_id)
            except tk.TclError:
                pass
            self._live_after_id = None
        self._preview_base_ldr = None
        self._preview_adjusted = None
        self._live_preview_dirty = False
        if self.result is None and not self._settings_dirty:
            return
        self.result = None
        self.result_settings = None
        self._settings_dirty = False
        self.preview_var.set("result")
        self.preview_switch.refresh()
        self.warning_label.pack_forget()
        self.save_button.set_enabled(False)
        self.preview_switch.set_enabled(False)
        self._update_preview_placeholder()
        self._render_preview()
        self._set_status(message, "idle")

    # ------------------------------------------------------------------
    # Settings callbacks

    def _set_mode(self, mode: str) -> None:
        if self.mode_var.get() == mode:
            return
        self.mode_var.set(mode)
        self.fusion_card.set_selected(mode == MODE_FUSION)
        self.hdr_card.set_selected(mode == MODE_HDR)
        self._update_tone_state()
        self._mark_settings_dirty()

    def _on_tone_changed(self, _value: str) -> None:
        self._mark_settings_dirty()

    @staticmethod
    def _make_preview_base(base_ldr: np.ndarray) -> np.ndarray:
        if max(base_ldr.shape[:2]) <= PREVIEW_MAX_DIM:
            return base_ldr.astype(np.float32, copy=True)
        rgb = np.clip(base_ldr, 0.0, 1.0)
        encoded = np.clip(rgb * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
        image = Image.fromarray(encoded)
        image.thumbnail(
            (PREVIEW_MAX_DIM, PREVIEW_MAX_DIM), Image.Resampling.LANCZOS
        )
        return np.asarray(image, dtype=np.float32) / 255.0

    def _on_slider_changed(self, _value: float) -> None:
        if self.result is None or self._busy:
            if self.result is None and not self._busy:
                self._set_status("细节参数已设置 · 合成后可实时预览", "idle")
            return
        self._live_preview_dirty = True
        if self._live_after_id is not None:
            self.root.after_cancel(self._live_after_id)
        self._live_after_id = self.root.after(55, self._apply_live_adjustments)

    def _apply_live_adjustments(self, show_status: bool = True) -> None:
        self._live_after_id = None
        if self.result is None or self._busy:
            return
        if self._preview_base_ldr is None:
            self._preview_base_ldr = self._make_preview_base(self.result.base_ldr)
        self._preview_adjusted = render_adjustments(
            self._preview_base_ldr,
            brightness=float(self.brightness_var.get()),
            saturation=float(self.saturation_var.get()),
            detail=float(self.detail_var.get()),
        )
        self._live_preview_dirty = True
        if self.result_settings is not None:
            self.result_settings.brightness = float(self.brightness_var.get())
            self.result_settings.saturation = float(self.saturation_var.get())
            self.result_settings.detail = float(self.detail_var.get())
        self._render_preview()
        if show_status:
            if self._settings_dirty:
                self._set_status(
                    "细节调整已实时预览；其他设置仍需重新合成", "warning"
                )
            else:
                self._set_status(
                    "细节调整已实时预览 · 导出时按完整分辨率应用", "ok"
                )

    def _flush_live_adjustments(self) -> None:
        if self._live_after_id is not None:
            try:
                self.root.after_cancel(self._live_after_id)
            except tk.TclError:
                pass
            self._live_after_id = None
        if self.result is None or self._busy:
            return
        if not self._live_preview_dirty:
            return
        self.result.image = render_adjustments(
            self.result.base_ldr,
            brightness=float(self.brightness_var.get()),
            saturation=float(self.saturation_var.get()),
            detail=float(self.detail_var.get()),
        )
        if self.result_settings is not None:
            self.result_settings.brightness = float(self.brightness_var.get())
            self.result_settings.saturation = float(self.saturation_var.get())
            self.result_settings.detail = float(self.detail_var.get())
        if self._preview_base_ldr is not None:
            self._preview_adjusted = render_adjustments(
                self._preview_base_ldr,
                brightness=float(self.brightness_var.get()),
                saturation=float(self.saturation_var.get()),
                detail=float(self.detail_var.get()),
            )
        self._live_preview_dirty = False
        self._render_preview()

    def _on_toggle_changed(self, _value: bool) -> None:
        self._mark_settings_dirty()

    def _current_output_size(self) -> int:
        return dict(SIZE_OPTIONS).get(self.size_var.get(), 2400)

    def _save_size_preferences(self) -> bool:
        self.app_settings.output_size = self._current_output_size()
        try:
            save_app_settings(self.app_settings)
        except OSError as exc:
            self._set_status(f"无法保存尺寸记忆：{exc}", "error")
            return False
        return True

    def _on_size_changed(self) -> None:
        self._mark_settings_dirty()
        if self.remember_size_var.get():
            self._save_size_preferences()

    def _on_remember_size_changed(self, enabled: bool) -> None:
        self.app_settings.remember_size = bool(enabled)
        saved = self._save_size_preferences()
        if not saved:
            return
        if enabled:
            self._set_status(f"已记住输出尺寸 · {self.size_var.get()}", "ok")
        else:
            self._set_status(
                "已关闭尺寸记忆 · 下次启动恢复长边 2400 px", "idle"
            )

    def _reset_settings(self) -> None:
        if self._busy:
            return
        self.mode_var.set(MODE_FUSION)
        self.tone_var.set(TONE_NATURAL)
        self.fusion_card.set_selected(True)
        self.hdr_card.set_selected(False)
        self.brightness_row.set_value(1.02)
        self.saturation_row.set_value(1.06)
        self.detail_row.set_value(1.0)
        self.align_var.set(True)
        self.deghost_var.set(False)
        self.size_var.set(SIZE_OPTIONS[0][0])
        self.size_combo.current(0)
        if self.remember_size_var.get():
            self._save_size_preferences()
        self.align_toggle.refresh()
        self.ghost_toggle.refresh()
        self.tone_switch.refresh()
        self.preview_switch.refresh()
        self._update_tone_state()
        self._settings_dirty = self.result is not None
        if self.result is not None:
            self._set_status("已恢复默认设置 · 重新合成后生效", "warning")
        else:
            self._set_status("已恢复默认设置", "idle")

    # ------------------------------------------------------------------
    # Merge worker

    def _start_merge(self) -> None:
        if self._busy:
            return
        if self._importing:
            self._set_status("正在读取照片，请稍候…", "warning")
            return
        if not 2 <= len(self.items) <= 5:
            show_message(
                self.root,
                "还差几张照片",
                "曝光合成需要 2–5 张不同曝光的照片。\n"
                f"当前已添加 {len(self.items)} 张。",
                kind="warning",
            )
            return
        max_dim = self._current_output_size()
        if max_dim == 0:
            total_pixels = sum(
                item.info.width * item.info.height for item in self.items
            )
            if total_pixels > 80_000_000:
                if not show_message(
                    self.root,
                    "使用原始尺寸？",
                    "所选照片像素总量较大，按原始尺寸处理可能占用较多内存和时间。\n"
                    "建议先使用「长边 2400 px」预览效果，再按需导出。",
                    kind="warning",
                    confirm=True,
                    primary="继续处理",
                ):
                    return
        settings = MergeSettings(
            mode=self.mode_var.get(),
            tone=self.tone_var.get(),
            align=bool(self.align_var.get()),
            deghost=bool(self.deghost_var.get()),
            max_dim=max_dim,
            brightness=float(self.brightness_var.get()),
            saturation=float(self.saturation_var.get()),
            detail=float(self.detail_var.get()),
        )
        if self._live_after_id is not None:
            try:
                self.root.after_cancel(self._live_after_id)
            except tk.TclError:
                pass
            self._live_after_id = None
        paths = [item.path for item in self.items]
        self._job_token += 1
        token = self._job_token
        self._queue = queue.Queue()
        self._settings_dirty = False
        self._settings_changed_during_merge = False
        self._set_busy(True)
        self._set_status("正在准备合成…", "busy")
        self._preview_photo = None
        self.root.configure(cursor="watch")
        worker = threading.Thread(
            target=self._merge_worker,
            args=(token, paths, settings),
            daemon=True,
            name="hdr-merge",
        )
        worker.start()
        self.root.after(60, self._poll_worker)

    def _merge_worker(
        self, token: int, paths: list[Path], settings: MergeSettings
    ) -> None:
        assert self._queue is not None
        local_queue = self._queue
        try:
            result = process_bracket(
                paths,
                settings,
                lambda message, fraction: local_queue.put(
                    ("progress", token, message, fraction)
                ),
            )
            local_queue.put(("done", token, result, settings))
        except Exception as exc:
            local_queue.put(("error", token, exc, traceback.format_exc()))

    def _poll_worker(self) -> None:
        if self._closed:
            return
        if self._queue is None:
            return
        try:
            event = self._queue.get_nowait()
        except queue.Empty:
            self.root.after(70, self._poll_worker)
            return

        kind = event[0]
        token = event[1]
        if token != self._job_token:
            self.root.after(50, self._poll_worker)
            return

        if kind == "progress":
            self._set_progress(str(event[2]), float(event[3]))
            self.root.after(50, self._poll_worker)
            return

        self.root.configure(cursor="")
        if kind == "done":
            result = event[2]
            settings = event[3]
            self._on_merge_done(result, settings)
        else:
            self._on_merge_error(event[2], event[3])
        self._queue = None

    def _on_merge_done(self, result: MergeResult, settings: MergeSettings) -> None:
        self._set_busy(False)
        self.result = result
        self.result_settings = settings
        self._settings_dirty = self._settings_changed_during_merge
        self.preview_var.set("result")
        self.preview_switch.refresh()
        self.preview_switch.set_enabled(True)
        self.save_button.set_enabled(True)
        self._preview_base_ldr = self._make_preview_base(result.base_ldr)
        self._preview_adjusted = render_adjustments(
            self._preview_base_ldr,
            brightness=float(self.brightness_var.get()),
            saturation=float(self.saturation_var.get()),
            detail=float(self.detail_var.get()),
        )
        sliders_changed = (
            abs(float(self.brightness_var.get()) - settings.brightness) > 1e-3
            or abs(float(self.saturation_var.get()) - settings.saturation) > 1e-3
            or abs(float(self.detail_var.get()) - settings.detail) > 1e-3
        )
        self._live_preview_dirty = sliders_changed
        if sliders_changed:
            settings.brightness = float(self.brightness_var.get())
            settings.saturation = float(self.saturation_var.get())
            settings.detail = float(self.detail_var.get())
        self._apply_result_times(result)
        self._update_preview_placeholder()
        self._render_preview()
        self._update_result_info()
        self._refresh_controls()

        if self._settings_changed_during_merge:
            self._settings_dirty = True
            self._set_status(
                f"合成完成 · {result.elapsed:.1f} 秒 · 设置有更新，可重新合成",
                "warning",
            )
        else:
            suffix = " · 有提示" if result.warnings else ""
            self._set_status(
                f"合成完成 · {result.elapsed:.1f} 秒 · 已生成 {result.width} × {result.height}{suffix}",
                "ok",
            )

    def _on_merge_error(self, exc: Exception, trace: str) -> None:
        self._set_busy(False)
        self.root.configure(cursor="")
        self._set_status(f"合成失败：{exc}", "error")
        show_message(
            self.root,
            "合成没有完成",
            f"{exc}\n\n请检查照片是否完整、曝光是否有差异，或尝试降低处理尺寸。",
            kind="error",
        )
        print(trace, file=sys.stderr)

    def _apply_result_times(self, result: MergeResult) -> None:
        estimated = result.time_source == "estimated"
        for index, item in enumerate(self.items[: len(result.times)]):
            seconds = result.times[index]
            item.exposure_text = format_exposure(seconds, estimated=estimated)
            item.source_text = "估算" if estimated else "EXIF"
        self._rebuild_list(preserve_scroll=True)

    def _update_result_info(self) -> None:
        result = self.result
        if result is None:
            return
        self.preview_info.configure(
            text=f"{result.method_label} · {len(self.items)} 张曝光",
            fg=theme.TEXT_DIM,
        )
        bits = [f"{result.width} × {result.height} px", f"{result.elapsed:.1f} s"]
        if result.radiance is not None:
            bits.append("32-bit")
        self.preview_meta.configure(text=" · ".join(bits))
        if result.warnings:
            self.warning_label.configure(text=f"! {len(result.warnings)} 条提示")
            self.warning_label.pack(side="right", fill="y", padx=(0, 12))
        else:
            self.warning_label.pack_forget()
        self._settings_dirty = False

    def _show_warnings(self) -> None:
        if not self.result or not self.result.warnings:
            return
        body = "\n".join(f"·  {warning}" for warning in self.result.warnings)
        show_message(self.root, "合成提示", body, kind="warning")

    # ------------------------------------------------------------------
    # Preview

    def _on_preview_mode(self, mode: str) -> None:
        if self.result is None:
            return
        self.preview_var.set(mode)
        self._render_preview()

    def _update_preview_placeholder(self) -> None:
        if self.result is None:
            self.placeholder.place(relx=0.5, rely=0.46, anchor="center")
        else:
            self.placeholder.place_forget()

    def _render_preview(self) -> None:
        canvas = self.preview_canvas
        try:
            width = canvas.winfo_width()
            height = canvas.winfo_height()
        except tk.TclError:
            return
        canvas.delete("preview")
        self._preview_photo = None
        if self.result is None:
            return
        if width < 60 or height < 60:
            return
        if self.preview_var.get() == "reference":
            source = self.result.reference
        elif self._preview_adjusted is not None:
            source = self._preview_adjusted
        else:
            source = self.result.image
        image = Image.fromarray(source)
        padding = 26
        available_w = max(40, width - padding * 2)
        available_h = max(40, height - padding * 2)
        scale = min(available_w / image.width, available_h / image.height, 1.0)
        display_size = (
            max(1, int(round(image.width * scale))),
            max(1, int(round(image.height * scale))),
        )
        display = image.resize(display_size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(display)
        self._preview_photo = photo
        x0 = (width - display_size[0]) / 2
        y0 = (height - display_size[1]) / 2
        x1 = x0 + display_size[0]
        y1 = y0 + display_size[1]
        canvas.create_rectangle(
            x0 + 4,
            y0 + 5,
            x1 + 4,
            y1 + 5,
            fill="#05070A",
            outline="",
            tags="preview",
        )
        canvas.create_rectangle(
            x0 - 1,
            y0 - 1,
            x1 + 1,
            y1 + 1,
            outline=theme.BORDER,
            width=1,
            tags="preview",
        )
        canvas.create_image(x0, y0, anchor="nw", image=photo, tags="preview")

        if self.preview_var.get() == "reference":
            badge_text = "REFERENCE · 参考图"
            badge_color = theme.TEAL
        elif self.result.mode == MODE_HDR:
            badge_text = "32-BIT HDR"
            badge_color = theme.ACCENT
        else:
            badge_text = "EXPOSURE FUSION"
            badge_color = theme.ACCENT
        badge_w = 108 if len(badge_text) > 12 else 94
        bx0 = x0 + 12
        by0 = y0 + 12
        theme.create_round_rect(
            canvas,
            bx0,
            by0,
            bx0 + badge_w,
            by0 + 22,
            7,
            fill="#0B0F14",
            outline=badge_color,
            width=1,
            tags="preview",
        )
        canvas.create_text(
            bx0 + badge_w / 2,
            by0 + 11,
            text=badge_text,
            fill=badge_color,
            font=theme.FONT_MONO,
            tags="preview",
        )

    # ------------------------------------------------------------------
    # Save / help

    @staticmethod
    def _export_directory() -> Path:
        """Prefer a writable project folder so sandboxed saves still work."""
        try:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            return EXPORT_DIR
        except OSError:
            pictures = Path.home() / "Pictures"
            return pictures if pictures.is_dir() else Path.home()

    def _save_image(self) -> None:
        if self._busy or self.result is None:
            return
        filetypes: list[tuple[str, str]] = [
            ("JPEG 图片", "*.jpg"),
            ("PNG 图片", "*.png"),
            ("16 位 TIFF", "*.tif"),
        ]
        if self.result.radiance is not None:
            filetypes.append(("Radiance HDR", "*.hdr"))
        initial = f"HDR_{datetime.now():%Y%m%d_%H%M%S}.jpg"
        export_dir = self._export_directory()
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出 HDR 合成结果",
            initialdir=str(export_dir),
            initialfile=initial,
            defaultextension=".jpg",
            filetypes=filetypes,
        )
        if not path:
            return
        self._flush_live_adjustments()
        destination = Path(path)
        if destination.suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".png",
            ".tif",
            ".tiff",
            ".hdr",
        }:
            destination = destination.with_suffix(".jpg")
        self.root.configure(cursor="watch")
        fallback_note = ""
        try:
            saved = save_result(self.result, destination)
        except HDRMergeError as exc:
            self.root.configure(cursor="")
            show_message(
                self.root,
                "导出失败",
                f"无法写入文件：\n{exc}",
                kind="error",
            )
            return
        except OSError as exc:
            # A sandboxed or ACL-protected Desktop can be rejected by the OS.
            fallback = export_dir / destination.name
            if fallback == destination:
                self.root.configure(cursor="")
                show_message(
                    self.root,
                    "导出失败",
                    f"无法写入文件：\n{exc}",
                    kind="error",
                )
                return
            try:
                saved = save_result(self.result, fallback)
            except (HDRMergeError, OSError) as second:
                self.root.configure(cursor="")
                show_message(
                    self.root,
                    "导出失败",
                    f"原位置不可写：\n{exc}\n\n自动保存也失败：\n{second}",
                    kind="error",
                )
                return
            fallback_note = "原位置不可写，已自动保存到项目导出目录。\n\n"
        self.root.configure(cursor="")
        self._set_status(f"已导出 · {saved.name}", "ok")
        dialog = ModalDialog(
            self.root,
            "导出完成",
            fallback_note
            + f"文件已保存到：\n{saved}\n\n"
            + (
                "提示：Radiance .hdr 保留 32 位亮度数据，可用于后续调色。"
                if saved.suffix.lower() == ".hdr"
                else "图片已按当前预览的效果导出。"
            ),
            kind="info",
            confirm=True,
            primary="打开文件夹",
            secondary="完成",
            width=500,
        )
        if dialog.result:
            self._open_folder(saved.parent)

    @staticmethod
    def _open_folder(folder: Path) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass

    def _show_help(self) -> None:
        body = """拍摄建议
· 支持 2–5 张照片；建议拍摄 3–5 张，曝光间隔 1–2 EV 效果更好。
· 顺序不限；有 EXIF 时自动读取曝光时间，没有则按画面亮度估算。
· 不要改变光圈和对焦，只调整快门速度，避免景深与清晰度变化。
· 添加或拖入后会在后台读取照片，界面不会因为大图读取而卡住。

合成方式
· 自然融合：最稳妥，直接得到自然、锐利的 8 位结果。
· 真实 HDR：在线性域合成 32 位亮度，再经色调映射；可导出 .hdr。

实时细节调整
· 合成完成后，亮度、饱和度、细节滑杆会实时更新预览；
  导出时会用完整分辨率重新应用当前效果。

处理选项
· 自动对齐：纯平移时无损裁切（亚像素一次 Lanczos）；
  旋转/缩放时用 ORB + RANSAC，并按纹理在相似变换/单应间择优；
  最后用局部网格修正前景/远景视差。
· 去除移动重影：至少需要 3 张照片，适合行人、车辆；流云、水波等大面积变化建议关闭。
· 处理尺寸：长边 2400 px 适合快速预览，原始尺寸最清晰但更慢。

导出格式
· JPG / PNG：8 位显示图；TIFF：16 位显示图。
· .hdr：仅真实 HDR 可用，保留 32 位亮度，方便后续调色。

所有处理都在本机完成，照片不会上传。"""
        show_message(self.root, "使用指南", body, kind="info", width=510)


# ---------------------------------------------------------------------------
# Entry point


def main() -> None:
    root = tk.Tk()
    app = HDRStudioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
