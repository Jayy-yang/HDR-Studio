"""Reusable dark-theme widgets for HDR Studio."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Sequence

from . import theme


def _parent_bg(widget: tk.Misc) -> str:
    try:
        return str(widget.cget("bg"))
    except tk.TclError:
        return theme.BG


# ---------------------------------------------------------------------------
# Buttons and small indicators


class RoundedButton(tk.Canvas):
    _KINDS = {
        "primary": {
            "fill": theme.ACCENT,
            "hover": theme.ACCENT_HOVER,
            "press": theme.ACCENT_PRESS,
            "text": theme.ACCENT_INK,
            "border": theme.ACCENT,
        },
        "secondary": {
            "fill": theme.SURFACE_2,
            "hover": theme.SURFACE_3,
            "press": "#111821",
            "text": theme.TEXT,
            "border": theme.BORDER,
        },
        "ghost": {
            "fill": theme.SURFACE,
            "hover": theme.SURFACE_2,
            "press": theme.SURFACE_3,
            "text": theme.TEXT_DIM,
            "border": theme.SURFACE,
        },
        "danger": {
            "fill": theme.DANGER_SOFT,
            "hover": "#3B2024",
            "press": "#241316",
            "text": theme.DANGER,
            "border": "#4B2A2E",
        },
        "outline": {
            "fill": theme.SURFACE_2,
            "hover": theme.ACCENT_SOFT,
            "press": "#201A12",
            "text": theme.ACCENT,
            "border": theme.ACCENT,
        },
    }

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None] | None = None,
        *,
        kind: str = "primary",
        height: int = 42,
        radius: int = 12,
        font=None,
        width: int = 160,
        enabled: bool = True,
        on_press: Callable[[], None] | None = None,
        on_release: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            width=width,
            bg=_parent_bg(parent),
            highlightthickness=0,
            bd=0,
            takefocus=1,
            cursor="hand2",
        )
        self._text = text
        self._command = command
        self._kind = kind if kind in self._KINDS else "primary"
        self._radius = radius
        self._font = font or theme.FONT_BUTTON
        self._enabled = enabled
        self._hover = False
        self._pressed = False
        self._on_press = on_press
        self._on_release = on_release
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Key-space>", self._keyboard_activate)
        self.bind("<Return>", self._keyboard_activate)
        self.bind("<FocusIn>", lambda _event: self._draw())
        self.bind("<FocusOut>", lambda _event: self._draw())
        self._draw()

    # -- public ---------------------------------------------------------
    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        if not enabled:
            self._hover = False
            self._pressed = False
        self._draw()

    def set_kind(self, kind: str) -> None:
        if kind in self._KINDS:
            self._kind = kind
            self._draw()

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- events ---------------------------------------------------------
    def _enter(self, _event) -> None:
        if self._enabled:
            self._hover = True
            self._draw()

    def _leave(self, _event) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _press(self, _event) -> None:
        if not self._enabled:
            return
        self.focus_set()
        self._pressed = True
        self._draw()
        if self._on_press:
            self._on_press()

    def _release(self, event) -> None:
        if not self._enabled or not self._pressed:
            return
        self._pressed = False
        self._draw()
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        if inside:
            if self._on_release:
                self._on_release()
            if self._command:
                self._command()

    def _keyboard_activate(self, _event) -> None:
        if self._enabled and self._command:
            self._command()

    # -- painting -------------------------------------------------------
    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 2 or height <= 2:
            return
        palette = self._KINDS[self._kind]
        if not self._enabled:
            fill, border, text = theme.SURFACE_2, theme.BORDER_SOFT, theme.FAINT
        else:
            fill = palette["press"] if self._pressed else palette["hover"] if self._hover else palette["fill"]
            border = palette["border"]
            text = palette["text"]
        if self.focus_get() is self and self._enabled:
            border = theme.ACCENT_HOVER
        theme.create_round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            self._radius,
            fill=fill,
            outline=border,
            width=1,
        )
        self.create_text(
            width / 2,
            height / 2 - (1 if self._pressed else 0),
            text=self._text,
            fill=text,
            font=self._font,
        )


class Pill(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        *,
        width: int = 50,
        height: int = 22,
        background: str = theme.SURFACE_2,
        foreground: str = theme.ACCENT,
        border: str | None = None,
        font=None,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=_parent_bg(parent),
            highlightthickness=0,
            bd=0,
        )
        self._text = text
        self._background = background
        self._foreground = foreground
        self._border = border
        self._font = font or theme.FONT_TINY
        self.bind("<Configure>", lambda _event: self._draw())
        self._draw()

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 2:
            return
        theme.create_round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            height / 2,
            fill=self._background,
            outline=self._border or self._background,
            width=1,
        )
        self.create_text(
            width / 2,
            height / 2,
            text=self._text,
            fill=self._foreground,
            font=self._font,
        )


class StatusIndicator(tk.Canvas):
    """A calm idle dot that turns into a small rotating arc while busy."""

    def __init__(self, parent: tk.Misc, size: int = 18) -> None:
        super().__init__(
            parent,
            width=size,
            height=size,
            bg=_parent_bg(parent),
            highlightthickness=0,
            bd=0,
        )
        self._size = size
        self._busy = False
        self._angle = 0
        self._color = theme.MUTED
        self._after_id: str | None = None
        self._draw_idle()

    def set_idle(self, color: str = theme.MUTED) -> None:
        self._busy = False
        self._color = color
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        self._draw_idle()

    def set_busy(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._angle = 0
        self._tick()

    def _draw_idle(self) -> None:
        self.delete("all")
        margin = 5
        self.create_oval(
            margin,
            margin,
            self._size - margin,
            self._size - margin,
            fill=self._color,
            outline="",
        )

    def _tick(self) -> None:
        if not self._busy:
            return
        self.delete("all")
        pad = 2
        self.create_arc(
            pad,
            pad,
            self._size - pad,
            self._size - pad,
            start=self._angle,
            extent=250,
            style="arc",
            outline=theme.ACCENT,
            width=2,
        )
        self._angle = (self._angle + 32) % 360
        self._after_id = self.after(55, self._tick)


# ---------------------------------------------------------------------------
# Toggle / segmented options


class ToggleSwitch(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        variable: tk.BooleanVar,
        command: Callable[[bool], None] | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            parent,
            width=42,
            height=24,
            bg=_parent_bg(parent),
            highlightthickness=0,
            bd=0,
            cursor="hand2" if enabled else "arrow",
        )
        self._var = variable
        self._command = command
        self._enabled = enabled
        self._hover = False
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._draw()

    def _enter(self, _event) -> None:
        self._hover = True
        self._draw()

    def _leave(self, _event) -> None:
        self._hover = False
        self._draw()

    def _toggle(self, _event) -> None:
        if not self._enabled:
            return
        self._var.set(not self._var.get())
        self._draw()
        if self._command:
            self._command(bool(self._var.get()))

    def refresh(self) -> None:
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        on = bool(self._var.get())
        track = theme.ACCENT if on else theme.SURFACE_3
        if not self._enabled:
            track = theme.SURFACE_2
        if on and self._hover and self._enabled:
            track = theme.ACCENT_HOVER
        theme.create_round_rect(
            self,
            1,
            3,
            41,
            21,
            9,
            fill=track,
            outline=theme.ACCENT if on and self._hover else track,
            width=1,
        )
        cx = 32 if on else 10
        self.create_oval(
            cx - 7,
            5,
            cx + 7,
            19,
            fill=theme.TEXT if on else theme.MUTED,
            outline="",
        )


class SegmentedControl(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        options: Sequence[tuple[str, str]],
        variable: tk.StringVar,
        command: Callable[[str], None] | None = None,
        *,
        height: int = 34,
        width: int = 180,
        font=None,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            width=width,
            bg=_parent_bg(parent),
            highlightthickness=0,
            bd=0,
            cursor="hand2" if enabled else "arrow",
        )
        self._segments = list(options)
        self._var = variable
        self._command = command
        self._height = height
        self._font = font or theme.FONT_BUTTON_SMALL
        self._enabled = enabled
        self._hover_index = -1
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _event: self._set_hover(-1))
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def refresh(self) -> None:
        self._draw()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _index_at(self, x: float) -> int:
        width = self.winfo_width()
        if width <= 8:
            return -1
        segment = (width - 8) / max(1, len(self._segments))
        index = int((x - 4) // segment)
        return index if 0 <= index < len(self._segments) else -1

    def _motion(self, event) -> None:
        self._set_hover(self._index_at(event.x) if self._enabled else -1)

    def _set_hover(self, index: int) -> None:
        if self._hover_index != index:
            self._hover_index = index
            self._draw()

    def _click(self, event) -> None:
        if not self._enabled:
            return
        index = self._index_at(event.x)
        if index < 0:
            return
        value = self._segments[index][1]
        if value != self._var.get():
            self._var.set(value)
            self._draw()
            if self._command:
                self._command(value)

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self._height
        if width <= 8:
            return
        theme.create_round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            10,
            fill=theme.SURFACE_2,
            outline=theme.BORDER_SOFT,
            width=1,
        )
        segment = (width - 8) / max(1, len(self._segments))
        selected = self._var.get()
        for index, (label, value) in enumerate(self._segments):
            x0 = 4 + segment * index
            x1 = x0 + segment - 2
            is_selected = value == selected
            if is_selected:
                theme.create_round_rect(
                    self,
                    x0 + 1,
                    4,
                    x1,
                    height - 4,
                    8,
                    fill=theme.ACCENT_SOFT,
                    outline=theme.ACCENT if self._enabled else theme.FAINT,
                    width=1,
                )
            elif self._hover_index == index and self._enabled:
                theme.create_round_rect(
                    self,
                    x0 + 1,
                    4,
                    x1,
                    height - 4,
                    8,
                    fill=theme.SURFACE_3,
                    outline=theme.SURFACE_3,
                    width=1,
                )
            color = (
                theme.ACCENT
                if is_selected and self._enabled
                else theme.TEXT_DIM
                if self._enabled
                else theme.FAINT
            )
            self.create_text(
                (x0 + x1) / 2,
                height / 2,
                text=label,
                fill=color,
                font=self._font,
            )


class ModeCard(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str,
        *,
        height: int = 64,
        selected: bool = False,
        command: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            bg=_parent_bg(parent),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._title = title
        self._subtitle = subtitle
        self._height = height
        self._selected = selected
        self._command = command
        self._hover = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._draw()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._draw()

    def _click(self, _event) -> None:
        if self._command:
            self._command()

    def _enter(self, _event) -> None:
        self._hover = True
        self._draw()

    def _leave(self, _event) -> None:
        self._hover = False
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self._height
        if width <= 8:
            return
        fill = theme.ACCENT_SOFT if self._selected else theme.SURFACE_2
        if self._hover and not self._selected:
            fill = theme.SURFACE_3
        border = theme.ACCENT if self._selected else theme.BORDER
        if self._hover and not self._selected:
            border = theme.MUTED
        theme.create_round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            12,
            fill=fill,
            outline=border,
            width=1,
        )
        cx, cy = 20, height / 2
        self.create_oval(
            cx - 7,
            cy - 7,
            cx + 7,
            cy + 7,
            outline=theme.ACCENT if self._selected else theme.MUTED,
            width=1,
        )
        if self._selected:
            self.create_oval(
                cx - 3.5,
                cy - 3.5,
                cx + 3.5,
                cy + 3.5,
                fill=theme.ACCENT,
                outline="",
            )
        self.create_text(
            40,
            21,
            text=self._title,
            anchor="w",
            fill=theme.TEXT,
            font=(theme.FONT_FAMILY, 10, "bold"),
        )
        self.create_text(
            40,
            41,
            text=self._subtitle,
            anchor="w",
            fill=theme.MUTED if not self._selected else theme.TEXT_DIM,
            font=theme.FONT_SMALL,
        )


# ---------------------------------------------------------------------------
# Sliders


class CanvasSlider(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        variable: tk.DoubleVar,
        from_: float,
        to: float,
        command: Callable[[float], None] | None = None,
        *,
        height: int = 26,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            bg=_parent_bg(parent),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self._var = variable
        self._from = from_
        self._to = to
        self._command = command
        self._height = height
        self._hover = False
        self._dragging = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._start)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._end)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Left>", lambda _event: self._nudge(-0.01))
        self.bind("<Right>", lambda _event: self._nudge(0.01))
        self._draw()

    def _track_bounds(self) -> tuple[float, float]:
        return 5.0, max(6.0, self.winfo_width() - 5.0)

    def _value_to_x(self, value: float) -> float:
        x0, x1 = self._track_bounds()
        ratio = (value - self._from) / (self._to - self._from)
        return x0 + (x1 - x0) * max(0.0, min(1.0, ratio))

    def _x_to_value(self, x: float) -> float:
        x0, x1 = self._track_bounds()
        ratio = (x - x0) / max(1e-6, x1 - x0)
        return self._from + (self._to - self._from) * max(0.0, min(1.0, ratio))

    def _apply(self, value: float) -> None:
        old = float(self._var.get())
        value = round(value, 3)
        if abs(value - old) < 1e-4:
            return
        self._var.set(value)
        self._draw()
        if self._command:
            self._command(value)

    def _start(self, event) -> None:
        self.focus_set()
        self._dragging = True
        self._apply(self._x_to_value(event.x))
        self._draw()

    def _drag(self, event) -> None:
        if self._dragging:
            self._apply(self._x_to_value(event.x))

    def _end(self, _event) -> None:
        self._dragging = False
        self._draw()

    def _enter(self, _event) -> None:
        self._hover = True
        self._draw()

    def _leave(self, _event) -> None:
        self._hover = False
        self._draw()

    def _nudge(self, amount: float) -> None:
        self._apply(float(self._var.get()) + amount * (self._to - self._from))

    def refresh(self) -> None:
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self._height
        if width <= 10:
            return
        y = height / 2
        x0, x1 = self._track_bounds()
        x = self._value_to_x(float(self._var.get()))
        self.create_line(x0, y, x1, y, fill=theme.SURFACE_3, width=4, capstyle="round")
        self.create_line(x0, y, x, y, fill=theme.ACCENT, width=4, capstyle="round")
        r = 7
        if self._dragging:
            self.create_oval(
                x - r - 3,
                y - r - 3,
                x + r + 3,
                y + r + 3,
                fill="",
                outline=theme.ACCENT_PRESS,
                width=1,
            )
        self.create_oval(
            x - r,
            y - r,
            x + r,
            y + r,
            fill=theme.ACCENT if (self._hover or self._dragging) else theme.TEXT,
            outline=theme.SURFACE,
            width=2,
        )


class SliderRow(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.DoubleVar,
        from_: float,
        to: float,
        formatter: Callable[[float], str],
        command: Callable[[float], None] | None = None,
        *,
        height: int = 52,
    ) -> None:
        super().__init__(parent, bg=_parent_bg(parent), height=height)
        self.pack_propagate(False)
        self._formatter = formatter
        header = tk.Frame(self, bg=self.cget("bg"))
        header.pack(fill="x")
        tk.Label(
            header,
            text=label,
            bg=self.cget("bg"),
            fg=theme.TEXT_DIM,
            font=theme.FONT_SMALL,
        ).pack(side="left")
        self._value_label = tk.Label(
            header,
            text=formatter(float(variable.get())),
            bg=self.cget("bg"),
            fg=theme.TEXT,
            font=theme.FONT_MONO,
        )
        self._value_label.pack(side="right")
        self._slider = CanvasSlider(
            self,
            variable,
            from_,
            to,
            command=self._changed,
            height=24,
        )
        self._slider.pack(fill="x", pady=(1, 0))
        self._variable = variable
        self._external_command = command

    def _changed(self, value: float) -> None:
        self._value_label.configure(text=self._formatter(value))
        if self._external_command:
            self._external_command(value)

    def set_value(self, value: float) -> None:
        self._variable.set(value)
        self._value_label.configure(text=self._formatter(float(value)))
        self._slider.refresh()


# ---------------------------------------------------------------------------
# Scrolling and cards


class ScrollFrame(tk.Frame):
    _instances: list["ScrollFrame"] = []
    _bound_roots: set[str] = set()

    def __init__(self, parent: tk.Misc, *, bg: str = theme.SURFACE) -> None:
        super().__init__(parent, bg=bg)
        self._bg = bg
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self,
            bg=bg,
            highlightthickness=0,
            bd=0,
            yscrollincrement=24,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self._scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style="Slim.Vertical.TScrollbar",
        )
        self.canvas.configure(yscrollcommand=self._scrollbar.set)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._scrollbar_visible = False
        ScrollFrame._instances.append(self)
        root = self.winfo_toplevel()
        root_key = str(root)
        if root_key not in ScrollFrame._bound_roots:
            root.bind_all("<MouseWheel>", ScrollFrame._dispatch, add="+")
            ScrollFrame._bound_roots.add(root_key)

    def _on_inner_configure(self, _event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._update_scrollbar()

    def _update_scrollbar(self) -> None:
        content_height = self.inner.winfo_reqheight()
        canvas_height = self.canvas.winfo_height()
        needed = content_height > canvas_height + 2
        if needed and not self._scrollbar_visible:
            self._scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
            self._scrollbar_visible = True
        elif not needed and self._scrollbar_visible:
            self._scrollbar.grid_remove()
            self._scrollbar_visible = False

    @classmethod
    def _dispatch(cls, event) -> None:
        if not cls._instances:
            return
        widget = event.widget
        if not isinstance(widget, tk.Misc):
            widget = None
        for frame in reversed(cls._instances):
            try:
                if not frame.winfo_exists():
                    continue
            except tk.TclError:
                continue
            node = widget
            while node is not None:
                if node is frame:
                    frame._on_wheel(event)
                    return
                try:
                    node = node.master
                except (AttributeError, tk.TclError):
                    node = None

    def _on_wheel(self, event) -> None:
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height() + 2:
            return
        if not event.delta:
            return
        steps = max(1, int(abs(event.delta) / 120))
        self.canvas.yview_scroll(-steps if event.delta > 0 else steps, "units")

    def destroy(self) -> None:
        try:
            ScrollFrame._instances.remove(self)
        except ValueError:
            pass
        super().destroy()

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)

    def scroll_to_bottom(self) -> None:
        self.canvas.yview_moveto(1.0)


class ImageListCard(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        index: int,
        name: str,
        exposure_text: str,
        source_text: str,
        thumbnail,
        selected: bool,
        command: Callable[[], None],
        remove_command: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            bg=theme.CARD_SELECTED if selected else theme.CARD,
            height=78,
            highlightthickness=1,
            highlightbackground=theme.ACCENT if selected else theme.BORDER_SOFT,
            highlightcolor=theme.ACCENT,
            cursor="hand2",
        )
        self.pack_propagate(False)
        self._selected = selected
        self._command = command
        self._remove_command = remove_command
        self._thumbnail = thumbnail

        self._bar = tk.Frame(
            self,
            width=3,
            bg=theme.ACCENT if selected else theme.CARD,
        )
        self._bar.pack(side="left", fill="y")
        self._bar.pack_propagate(False)

        self._number = tk.Label(
            self,
            text=f"{index:02d}",
            bg=self.cget("bg"),
            fg=theme.ACCENT if selected else theme.FAINT,
            font=theme.FONT_MONO,
            width=3,
        )
        self._number.pack(side="left", padx=(7, 0))

        self._thumb = tk.Label(
            self,
            image=thumbnail,
            bg=self.cget("bg"),
            bd=0,
            padx=0,
            pady=0,
        )
        self._thumb.pack(side="left", padx=(2, 10), pady=10)

        self._remove = tk.Label(
            self,
            text="×",
            bg=self.cget("bg"),
            fg=theme.MUTED,
            font=(theme.FONT_FAMILY, 14),
            cursor="hand2",
            width=2,
        )
        self._remove.pack(side="right", padx=(0, 3))
        self._remove.bind("<Button-1>", self._remove_clicked)
        self._remove.bind("<Enter>", lambda _e: self._remove.configure(fg=theme.DANGER))
        self._remove.bind("<Leave>", lambda _e: self._remove.configure(fg=theme.MUTED))

        self._info = tk.Frame(self, bg=self.cget("bg"))
        self._info.pack(side="left", fill="both", expand=True, pady=(12, 10))
        self._name = tk.Label(
            self._info,
            text=name,
            bg=self.cget("bg"),
            fg=theme.TEXT,
            font=theme.FONT_BODY,
            anchor="w",
            justify="left",
        )
        self._name.pack(fill="x")
        meta = tk.Frame(self._info, bg=self.cget("bg"))
        meta.pack(fill="x", pady=(7, 0))
        self._exposure = tk.Label(
            meta,
            text=exposure_text,
            bg=theme.ACCENT_SOFT if selected else theme.SURFACE_2,
            fg=theme.ACCENT,
            font=theme.FONT_TINY,
            padx=7,
            pady=2,
        )
        self._exposure.pack(side="left")
        self._source = tk.Label(
            meta,
            text=source_text,
            bg=self.cget("bg"),
            fg=theme.MUTED,
            font=theme.FONT_TINY,
        )
        self._source.pack(side="left", padx=(7, 0))

        widgets = [self, self._bar, self._number, self._thumb, self._info, self._name]
        for widget in widgets:
            widget.bind("<Button-1>", lambda _event: self._command())
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _remove_clicked(self, _event) -> None:
        self._remove_command()
        return "break"

    def _enter(self, _event) -> None:
        if not self._selected:
            self.configure(highlightbackground=theme.MUTED)

    def _leave(self, _event) -> None:
        if not self._selected:
            self.configure(highlightbackground=theme.BORDER_SOFT)


# ---------------------------------------------------------------------------
# Modal dialogs


class ModalDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        body: str,
        *,
        kind: str = "info",
        confirm: bool = False,
        primary: str = "知道了",
        secondary: str = "取消",
        width: int = 470,
    ) -> None:
        super().__init__(parent)
        self.result = False
        self.overrideredirect(True)
        self.configure(bg=theme.BORDER)
        self.transient(parent)
        self.resizable(False, False)
        self._parent = parent
        self._drag_offset = (0, 0)
        self._width = width

        shell = tk.Frame(self, bg=theme.SURFACE)
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        title_bar = tk.Frame(shell, bg=theme.SURFACE, height=50)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        accent = theme.DANGER if kind == "error" else theme.WARNING if kind == "warning" else theme.ACCENT
        tk.Frame(title_bar, bg=accent, width=4).pack(side="left", fill="y", padx=(18, 12), pady=14)
        tk.Label(
            title_bar,
            text=title,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        ).pack(side="left", fill="both", expand=True)
        close = tk.Label(
            title_bar,
            text="×",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=(theme.FONT_FAMILY, 15),
            cursor="hand2",
            padx=16,
        )
        close.pack(side="right", fill="y")
        close.bind("<Button-1>", lambda _event: self._close(False))
        close.bind("<Enter>", lambda _e: close.configure(fg=theme.TEXT))
        close.bind("<Leave>", lambda _e: close.configure(fg=theme.MUTED))

        content = tk.Frame(shell, bg=theme.SURFACE)
        content.pack(fill="both", expand=True, padx=24, pady=(4, 6))
        tk.Label(
            content,
            text=body,
            bg=theme.SURFACE,
            fg=theme.TEXT_DIM,
            font=theme.FONT_BODY,
            justify="left",
            anchor="w",
            wraplength=width - 52,
        ).pack(fill="x", anchor="w", pady=(0, 18))

        actions = tk.Frame(shell, bg=theme.SURFACE)
        actions.pack(fill="x", padx=24, pady=(2, 20))
        if confirm:
            RoundedButton(
                actions,
                secondary,
                lambda: self._close(False),
                kind="secondary",
                height=38,
                width=104,
                font=theme.FONT_BUTTON_SMALL,
            ).pack(side="right", padx=(10, 0))
        RoundedButton(
            actions,
            primary,
            lambda: self._close(True),
            kind="primary",
            height=38,
            width=104,
            font=theme.FONT_BUTTON_SMALL,
        ).pack(side="right")

        for widget in (title_bar, shell):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
        self.bind("<Escape>", lambda _event: self._close(False))

        self.update_idletasks()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        req_w = width
        req_h = self.winfo_reqheight()
        x = parent_x + max(20, (parent_w - req_w) // 2)
        y = parent_y + max(30, (parent_h - req_h) // 2)
        self.geometry(f"{req_w}x{req_h}+{x}+{y}")
        self.update_idletasks()
        self.deiconify()
        self.lift()
        self.focus_force()
        self.grab_set()
        self.wait_window(self)

    def _start_drag(self, event) -> None:
        self._drag_offset = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag(self, event) -> None:
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.geometry(f"+{x}+{y}")

    def _close(self, result: bool) -> None:
        self.result = result
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def show_message(
    parent: tk.Misc,
    title: str,
    body: str,
    *,
    kind: str = "info",
    confirm: bool = False,
    primary: str = "知道了",
    width: int = 470,
) -> bool:
    dialog = ModalDialog(
        parent,
        title,
        body,
        kind=kind,
        confirm=confirm,
        primary=primary,
        width=width,
    )
    return bool(dialog.result)
