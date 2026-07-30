from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from . import __version__
from .app_prefs import load_prefs, save_prefs
from .battery import scan_battery
from .export import export_html, export_json
from .fan_control import get_controller
from .macos_services import (
    MenuBarController,
    is_login_item_enabled,
    set_activation_policy_menu_bar_only,
    set_open_at_login,
)
from .models import BatteryInfo, DriveInfo, HealthStatus
from .resources import app_bundle_path, find_asset
from .scanner import scan_drives
from .thermal import scan_thermal
from .thermal_panel import ThermalPanel
from .models import ThermalSnapshot


# Soft daylight palette — not black, not purple
BG = "#E8EEF5"
SURFACE = "#F7FAFC"
SURFACE_HOVER = "#EEF3F8"
CARD = "#FFFFFF"
TEXT = "#152033"
MUTED = "#5B6B7C"
LINE = "#D5DEE8"
FOCUS_RING = "#7EB8A0"
ACCENT = "#0B6E4F"
ACCENT_HOVER = "#095C42"
ACCENT_PRESS = "#084C37"
ACCENT_SOFT = "#D8F0E6"
ACCENT_SOFT_HOVER = "#C5E8D9"
GOOD = "#0B6E4F"
CAUTION = "#B86E00"
BAD = "#C81E1E"
UNKNOWN = "#7A8796"
SOFT_UNKNOWN = "#EEF2F6"
SOFT_CAUTION = "#F8E8C8"
SOFT_BAD = "#F8D6D6"
SKELETON = "#DDE5EE"
FONT = "Helvetica Neue"
FONT_DISPLAY = "Helvetica Neue"

HEALTH_COLORS = {
    HealthStatus.GOOD: GOOD,
    HealthStatus.CAUTION: CAUTION,
    HealthStatus.BAD: BAD,
    HealthStatus.UNKNOWN: UNKNOWN,
}

HEALTH_SOFT = {
    HealthStatus.GOOD: ACCENT_SOFT,
    HealthStatus.CAUTION: SOFT_CAUTION,
    HealthStatus.BAD: SOFT_BAD,
    HealthStatus.UNKNOWN: SOFT_UNKNOWN,
}

STORAGE_PRIMARY = [
    ("health_left", "Health Remaining"),
    ("temp", "Temperature"),
    ("spare", "Available Spare"),
    ("capacity", "Capacity"),
]

STORAGE_SECONDARY_KEYS = [
    ("used", "Percentage Used"),
    ("read_tb", "Data Read"),
    ("written_tb", "Data Written"),
    ("power_on", "Power-On Hours"),
    ("cycles", "Power Cycles"),
    ("unsafe", "Unsafe Shutdowns"),
    ("media", "Media Errors"),
    ("critical", "Critical Warning"),
]

BATTERY_SECONDARY = [
    ("cycles", "Charge Cycles"),
    ("design_cycles", "Design Cycles"),
    ("temp", "Temperature"),
    ("amperage", "Amperage"),
    ("condition", "Condition"),
    ("source", "Power Source"),
    ("time_left", "Time Remaining"),
    ("voltage", "Voltage"),
    ("serial", "Serial"),
    ("manufacturer", "Manufacturer"),
]


def _bind_clickable(widgets: list[tk.Misc], on_click) -> None:
    for w in widgets:
        w.bind("<Button-1>", lambda _e, fn=on_click: fn())


class Pressable(tk.Label):
    """Button with hover / press / focus. System cursor (no hand)."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        primary: bool = False,
        padx: int = 12,
        pady: int = 8,
        font_size: int = 11,
        bold: bool = False,
    ) -> None:
        self._command = command
        self._primary = primary
        self._pressed = False
        self._hovered = False
        self._focused = False
        weight = "bold" if (bold or primary) else "normal"
        if primary:
            self._bg = ACCENT
            self._fg = "#FFFFFF"
            self._hover_bg = ACCENT_HOVER
            self._press_bg = ACCENT_PRESS
            self._border = ACCENT
        else:
            self._bg = SURFACE
            self._fg = TEXT
            self._hover_bg = SURFACE_HOVER
            self._press_bg = LINE
            self._border = LINE
        super().__init__(
            parent,
            text=f"  {text}  ",
            bg=self._bg,
            fg=self._fg,
            font=(FONT, font_size, weight),
            padx=padx,
            pady=pady,
            takefocus=1,
            highlightthickness=2,
            highlightbackground=parent.cget("bg") if hasattr(parent, "cget") else CARD,
            highlightcolor=FOCUS_RING,
        )
        self._apply_border()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Return>", lambda _e: self._command())
        self.bind("<space>", lambda _e: self._command())

    def _apply_border(self) -> None:
        # Always 2px so focus doesn't reflow; tint ring when focused.
        idle = (
            FOCUS_RING
            if self._focused
            else (self.master.cget("bg") if self._primary else self._border)
        )
        self.configure(
            highlightthickness=2,
            highlightbackground=idle,
            highlightcolor=FOCUS_RING,
        )

    def _paint(self) -> None:
        if self._pressed:
            bg = self._press_bg
        elif self._hovered:
            bg = self._hover_bg
        else:
            bg = self._bg
        self.configure(bg=bg)
        self._apply_border()

    def _on_enter(self, _e=None) -> None:
        self._hovered = True
        self._paint()

    def _on_leave(self, _e=None) -> None:
        self._hovered = False
        self._pressed = False
        self._paint()

    def _on_press(self, _e=None) -> None:
        self._pressed = True
        self.focus_set()
        self._paint()

    def _on_release(self, _e=None) -> None:
        was = self._pressed
        self._pressed = False
        self._paint()
        if was and self._hovered:
            self._command()

    def _on_focus_in(self, _e=None) -> None:
        self._focused = True
        self._paint()

    def _on_focus_out(self, _e=None) -> None:
        self._focused = False
        self._paint()

    def set_toggle(self, on: bool, on_text: str, off_text: str) -> None:
        if on:
            self._bg = ACCENT_SOFT
            self._fg = ACCENT
            self._hover_bg = ACCENT_SOFT_HOVER
            self._press_bg = "#B5DFCB"
            self._border = ACCENT
            self._primary = False
            self.configure(text=f"  {on_text}  ", fg=self._fg)
        else:
            self._bg = SURFACE
            self._fg = TEXT
            self._hover_bg = SURFACE_HOVER
            self._press_bg = LINE
            self._border = LINE
            self._primary = False
            self.configure(text=f"  {off_text}  ", fg=self._fg)
        self._paint()


class Segment(tk.Label):
    def __init__(self, parent: tk.Misc, text: str, command) -> None:
        self._command = command
        self._active = False
        self._hovered = False
        self._focused = False
        super().__init__(
            parent,
            text=f"  {text}  ",
            bg=SURFACE,
            fg=MUTED,
            font=(FONT, 12),
            padx=14,
            pady=8,
            takefocus=1,
            highlightthickness=2,
            highlightbackground=LINE,
            highlightcolor=FOCUS_RING,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._activate)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)

    def _activate(self, _e=None) -> None:
        self.focus_set()
        self._command()

    def _on_enter(self, _e=None) -> None:
        self._hovered = True
        self._paint()

    def _on_leave(self, _e=None) -> None:
        self._hovered = False
        self._paint()

    def _on_focus_in(self, _e=None) -> None:
        self._focused = True
        self._paint()

    def _on_focus_out(self, _e=None) -> None:
        self._focused = False
        self._paint()

    def _paint(self) -> None:
        if self._active:
            bg, fg, font = CARD, TEXT, (FONT, 12, "bold")
        elif self._hovered:
            bg, fg, font = SURFACE_HOVER, MUTED, (FONT, 12)
        else:
            bg, fg, font = SURFACE, MUTED, (FONT, 12)
        ring = FOCUS_RING if self._focused else LINE
        self.configure(bg=bg, fg=fg, font=font, highlightbackground=ring, highlightcolor=FOCUS_RING)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint()


class StatusPill(tk.Label):
    """Health badge with optional flash on change."""

    def __init__(self, parent: tk.Misc, textvariable: tk.StringVar) -> None:
        super().__init__(
            parent,
            textvariable=textvariable,
            bg=ACCENT_SOFT,
            fg=GOOD,
            font=(FONT, 12, "bold"),
            padx=12,
            pady=6,
        )
        self._flash_job: str | None = None
        self._soft = ACCENT_SOFT
        self._color = GOOD
        self._last_key: str | None = None

    def set_status(self, label: str, health: HealthStatus | None, *, flash: bool = True) -> None:
        color = HEALTH_COLORS.get(health, UNKNOWN) if health is not None else UNKNOWN
        soft = HEALTH_SOFT.get(health, SOFT_UNKNOWN) if health is not None else SOFT_UNKNOWN
        key = f"{label}:{color}"
        changed = key != self._last_key and self._last_key is not None
        self._last_key = key
        self._soft = soft
        self._color = color
        self.configure(bg=soft, fg=color)
        if flash and changed:
            self.flash()

    def flash(self) -> None:
        if self._flash_job is not None:
            try:
                self.after_cancel(self._flash_job)
            except tk.TclError:
                pass
        self.configure(bg=CARD, fg=self._color)
        self._flash_job = self.after(120, self._flash_mid)

    def _flash_mid(self) -> None:
        self.configure(bg=self._color, fg="#FFFFFF")
        self._flash_job = self.after(140, self._flash_end)

    def _flash_end(self) -> None:
        self.configure(bg=self._soft, fg=self._color)
        self._flash_job = None


class ProgressBar(tk.Frame):
    """Animated horizontal progress bar."""

    def __init__(self, parent: tk.Misc, *, height: int = 10) -> None:
        super().__init__(parent, bg=LINE, height=height)
        self.grid_propagate(False)
        self.pack_propagate(False)
        self._fill = tk.Frame(self, bg=ACCENT, height=height)
        self._fill.place(relx=0, rely=0, relwidth=0, relheight=1)
        self._current = 0.0
        self._target = 0.0
        self._job: str | None = None

    def set_percent(self, percent: float, *, animate: bool = True) -> None:
        self._target = max(0.0, min(1.0, percent / 100.0))
        if not animate:
            self._current = self._target
            self._fill.place(relx=0, rely=0, relwidth=self._target, relheight=1)
            return
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
        self._tick()

    def _tick(self) -> None:
        delta = self._target - self._current
        if abs(delta) < 0.008:
            self._current = self._target
            self._fill.place(relx=0, rely=0, relwidth=self._target, relheight=1)
            self._job = None
            return
        self._current += delta * 0.28
        self._fill.place(relx=0, rely=0, relwidth=self._current, relheight=1)
        self._job = self.after(16, self._tick)

    def cancel(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None


class MetricTile(tk.Frame):
    def __init__(self, parent: tk.Misc, label: str, *, large: bool = False) -> None:
        super().__init__(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        inner = tk.Frame(self, bg=CARD)
        pad = 16 if large else 14
        inner.pack(fill="both", expand=True, padx=pad, pady=pad - 2)
        self._label = tk.Label(inner, text=label.upper(), bg=CARD, fg=MUTED, font=(FONT, 9))
        self._label.pack(anchor="w")
        self.value = tk.StringVar(value="—")
        size = 20 if large else 15
        self._value_lbl = tk.Label(
            inner,
            textvariable=self.value,
            bg=CARD,
            fg=TEXT,
            font=(FONT_DISPLAY, size, "bold"),
            wraplength=200 if large else 160,
            justify="left",
        )
        self._value_lbl.pack(anchor="w", pady=(6, 0))
        self._skeleton = tk.Frame(inner, bg=SKELETON, height=size + 4, width=88 if large else 72)
        self._dimmed = False
        self._loading = False
        self._saved: str | None = None
        self._pulse_job: str | None = None
        self._pulse_on = False

    def set_dimmed(self, dimmed: bool) -> None:
        if dimmed == self._dimmed and not self._loading:
            return
        self._dimmed = dimmed
        if not self._loading:
            self._value_lbl.configure(fg=MUTED if dimmed else TEXT)

    def set_loading(self, loading: bool) -> None:
        if loading == self._loading:
            return
        self._loading = loading
        if loading:
            self._saved = self.value.get()
            self.value.set("")
            self._value_lbl.pack_forget()
            self._skeleton.pack(anchor="w", pady=(8, 0))
            self._start_pulse()
        else:
            self._stop_pulse()
            self._skeleton.pack_forget()
            self._value_lbl.pack(anchor="w", pady=(6, 0))
            if self._saved is not None and self.value.get() == "":
                self.value.set(self._saved)
            self._saved = None
            self._value_lbl.configure(fg=MUTED if self._dimmed else TEXT)

    def _start_pulse(self) -> None:
        self._pulse_on = False
        self._pulse()

    def _stop_pulse(self) -> None:
        if self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except tk.TclError:
                pass
            self._pulse_job = None
        self._skeleton.configure(bg=SKELETON)

    def _pulse(self) -> None:
        if not self._loading:
            return
        self._pulse_on = not self._pulse_on
        self._skeleton.configure(bg=LINE if self._pulse_on else SKELETON)
        self._pulse_job = self.after(420, self._pulse)


class DriveRow(tk.Frame):
    def __init__(self, parent: tk.Misc, drive: DriveInfo, on_select) -> None:
        super().__init__(
            parent,
            bg=SURFACE,
            takefocus=1,
            highlightthickness=2,
            highlightbackground=CARD,
            highlightcolor=FOCUS_RING,
        )
        self.drive = drive
        self.on_select = on_select
        self.selected = False
        self._hovered = False
        self._focused = False

        self._accent = tk.Frame(self, bg=SURFACE, width=3)
        self._accent.pack(side="left", fill="y")

        self.dot = tk.Canvas(self, width=10, height=10, bg=SURFACE, highlightthickness=0)
        self.dot.pack(side="left", padx=(10, 8), pady=14)
        self._dot_id = self.dot.create_oval(1, 1, 9, 9, fill=UNKNOWN, outline=UNKNOWN)

        text = tk.Frame(self, bg=SURFACE)
        text.pack(side="left", fill="x", expand=True, pady=10)
        self.title = tk.Label(text, text="", bg=SURFACE, fg=TEXT, font=(FONT, 12, "bold"), anchor="w")
        self.title.pack(fill="x")
        self.sub = tk.Label(text, text="", bg=SURFACE, fg=MUTED, font=(FONT, 10), anchor="w")
        self.sub.pack(fill="x")

        self.health = tk.Label(self, text="", bg=SURFACE, fg=UNKNOWN, font=(FONT, 11, "bold"), padx=12)
        self.health.pack(side="right")

        self._parts = [self, self._accent, text, self.title, self.sub, self.health, self.dot]
        _bind_clickable(self._parts, self._click)
        for w in self._parts:
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Return>", lambda _e: self._click())
        self.bind("<space>", lambda _e: self._click())

        self.update_drive(drive)

    def _click(self) -> None:
        self.focus_set()
        self.on_select(self.drive)

    def _on_enter(self, _e=None) -> None:
        self._hovered = True
        if not self.selected:
            self._apply_bg(SURFACE_HOVER)

    def _on_leave(self, _e=None) -> None:
        self._hovered = False
        if not self.selected:
            self._apply_bg(SURFACE)

    def _on_focus_in(self, _e=None) -> None:
        self._focused = True
        self.configure(highlightbackground=FOCUS_RING)

    def _on_focus_out(self, _e=None) -> None:
        self._focused = False
        self.configure(highlightbackground=CARD)

    def _apply_bg(self, bg: str) -> None:
        for w in self._parts:
            w.configure(bg=bg)
        self.dot.configure(bg=bg)
        accent = ACCENT if self.selected else bg
        self._accent.configure(bg=accent)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        if selected:
            self._apply_bg(ACCENT_SOFT)
        elif self._hovered:
            self._apply_bg(SURFACE_HOVER)
        else:
            self._apply_bg(SURFACE)

    def update_drive(self, drive: DriveInfo) -> None:
        self.drive = drive
        color = HEALTH_COLORS.get(drive.health, UNKNOWN)
        self.dot.itemconfigure(self._dot_id, fill=color, outline=color)
        self.title.configure(text=drive.model)
        kind = "SSD" if drive.is_ssd else "Disk"
        loc = "Internal" if drive.is_internal else "External"
        self.sub.configure(text=f"{drive.device} · {kind} · {loc}")
        self.health.configure(text=drive.health.value, fg=color)


class App(tk.Tk):
    def __init__(self, *, menu_bar_mode: bool | None = None) -> None:
        super().__init__()
        self.title(f"Mac Hardware Info {__version__}")
        self.geometry("1080x720")
        self.minsize(920, 600)
        self.configure(bg=BG)

        prefs = load_prefs()
        self._prefs = prefs
        self._menu_bar_mode = menu_bar_mode if menu_bar_mode is not None else bool(prefs.get("menu_bar_mode"))
        self._menu_bar_controller: MenuBarController | None = None

        self.drives: list[DriveInfo] = []
        self.battery: BatteryInfo | None = None
        self._selected: DriveInfo | None = None
        self._selected_device: str | None = None
        self._section = "storage"
        self._drive_rows: dict[str, DriveRow] = {}
        self.stat_tiles: dict[str, MetricTile] = {}
        self.batt_tiles: dict[str, MetricTile] = {}
        self.batt_cap_tiles: dict[str, MetricTile] = {}
        self._auto_refresh = False
        self._auto_job: str | None = None
        self._refreshing = False
        self._auto_interval_ms = 3000
        self._thermal_interval_ms = 1500
        self._thermal_job: str | None = None
        self._empty_lbl: tk.Label | None = None
        self._status_pulse_job: str | None = None
        self._status_base = "Ready"
        self.charge_bar: ProgressBar | None = None
        self.maxcap_bar: ProgressBar | None = None
        self.thermal: ThermalSnapshot | None = None
        self.thermal_panel: ThermalPanel | None = None

        self._build()
        self._set_window_icon()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(0, self._startup_menu_integration)
        self.after(60, self.refresh)

    def _wants_status_item(self) -> bool:
        return app_bundle_path() is not None or self._menu_bar_mode

    def _should_start_hidden(self) -> bool:
        """Hide on launch only for login-item background startup, not manual opens."""
        return (
            self._menu_bar_mode
            and bool(self._prefs.get("open_at_login"))
            and bool(self._prefs.get("start_hidden", False))
        )

    def _startup_menu_integration(self) -> None:
        if self._wants_status_item():
            self._ensure_status_item()
        if self._menu_bar_mode:
            if not set_activation_policy_menu_bar_only(True):
                messagebox.showwarning(
                    "Menu bar mode",
                    "PyObjC is required for menu bar mode:\n  pip3 install pyobjc-framework-Cocoa",
                )
                self._menu_bar_mode = False
                self._prefs["menu_bar_mode"] = False
                save_prefs(self._prefs)
                self.menu_bar_btn.set_toggle(False, "Menu Bar: On", "Menu Bar: Off")
            else:
                self._prefs["menu_bar_mode"] = True
                save_prefs(self._prefs)
                if self._should_start_hidden():
                    self.withdraw()

    def _set_window_icon(self) -> None:
        for name in ("AppIcon-128.png", "AppIcon.png", "icons/C-settings-tool.png"):
            icon_png = find_asset(name)
            if icon_png is not None:
                try:
                    img = tk.PhotoImage(file=str(icon_png))
                    self.iconphoto(True, img)
                    self._icon_image = img
                    return
                except tk.TclError:
                    continue

    def _build(self) -> None:
        top = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        top.pack(fill="x")
        top_inner = tk.Frame(top, bg=CARD)
        top_inner.pack(fill="x", padx=22, pady=14)

        brand = tk.Frame(top_inner, bg=CARD)
        brand.pack(side="left")
        tk.Label(brand, text="Hardware Info", bg=CARD, fg=TEXT, font=(FONT_DISPLAY, 18, "bold")).pack(anchor="w")
        tk.Label(brand, text="Storage, battery, and thermals", bg=CARD, fg=MUTED, font=(FONT, 11)).pack(anchor="w")

        actions = tk.Frame(top_inner, bg=CARD)
        actions.pack(side="right")
        Pressable(actions, "Refresh", self.refresh, primary=True).pack(side="left", padx=(0, 8))
        self.auto_btn = Pressable(actions, "Auto Refresh: Off", self.toggle_auto_refresh)
        self.auto_btn.pack(side="left", padx=(0, 8))
        self.menu_bar_btn = Pressable(actions, "Menu Bar: Off", self.toggle_menu_bar_mode)
        self.menu_bar_btn.pack(side="left", padx=(0, 8))
        self.login_btn = Pressable(actions, "Login Item: Off", self.toggle_open_at_login)
        self.login_btn.pack(side="left", padx=(0, 8))
        self.menu_bar_btn.set_toggle(self._menu_bar_mode, "Menu Bar: On", "Menu Bar: Off")
        login_on = is_login_item_enabled()
        self.login_btn.set_toggle(login_on, "Login Item: On", "Login Item: Off")
        Pressable(actions, "Export JSON", self.export_json_dialog).pack(side="left", padx=(0, 8))
        Pressable(actions, "Export HTML", self.export_html_dialog).pack(side="left")

        seg_wrap = tk.Frame(self, bg=BG)
        seg_wrap.pack(fill="x", padx=22, pady=(16, 0))
        seg = tk.Frame(seg_wrap, bg=LINE, padx=1, pady=1)
        seg.pack(anchor="w")
        self.seg_storage = Segment(seg, "Storage", lambda: self._show_section("storage"))
        self.seg_storage.pack(side="left")
        self.seg_battery = Segment(seg, "Battery", lambda: self._show_section("battery"))
        self.seg_battery.pack(side="left")
        self.seg_thermal = Segment(seg, "Thermal", lambda: self._show_section("thermal"))
        self.seg_thermal.pack(side="left")
        self.seg_storage.set_active(True)

        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = tk.Label(seg_wrap, textvariable=self.status_var, bg=BG, fg=MUTED, font=(FONT, 10))
        self.status_lbl.pack(side="right")

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=22, pady=16)

        self.storage_frame = tk.Frame(self.body, bg=BG)
        self.battery_frame = tk.Frame(self.body, bg=BG)
        self.thermal_frame = tk.Frame(self.body, bg=BG)
        self._build_storage(self.storage_frame)
        self._build_battery(self.battery_frame)
        self.thermal_panel = ThermalPanel(self.thermal_frame, set_status=self._set_status)
        self.thermal_panel.pack(fill="both", expand=True)
        self.storage_frame.pack(fill="both", expand=True)

    def _build_storage(self, parent: tk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE, width=280)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        left.pack_propagate(False)
        parent.columnconfigure(0, minsize=280)
        tk.Label(left, text="DRIVES", bg=CARD, fg=MUTED, font=(FONT, 9, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6)
        )
        self.drive_list_host = tk.Frame(left, bg=CARD)
        self.drive_list_host.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        right = tk.Frame(parent, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        hero = tk.Frame(right, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        hero.grid(row=0, column=0, sticky="ew")
        hero_inner = tk.Frame(hero, bg=CARD)
        hero_inner.pack(fill="x", padx=20, pady=18)
        hero_inner.columnconfigure(0, weight=1)

        self.model_var = tk.StringVar(value="No drive selected")
        self.health_var = tk.StringVar(value="—")
        self.subtitle_var = tk.StringVar(value="")
        self.reason_var = tk.StringVar(value="")

        tk.Label(
            hero_inner,
            textvariable=self.model_var,
            bg=CARD,
            fg=TEXT,
            font=(FONT_DISPLAY, 22, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.health_pill = StatusPill(hero_inner, self.health_var)
        self.health_pill.grid(row=0, column=1, sticky="e")

        tk.Label(
            hero_inner,
            textvariable=self.subtitle_var,
            bg=CARD,
            fg=MUTED,
            font=(FONT, 11),
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        tk.Label(
            hero_inner,
            textvariable=self.reason_var,
            bg=CARD,
            fg=MUTED,
            font=(FONT, 11),
            wraplength=640,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        metrics = tk.Frame(right, bg=BG)
        metrics.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for i, (key, title) in enumerate(STORAGE_PRIMARY):
            tile = MetricTile(metrics, title, large=True)
            tile.grid(row=0, column=i, sticky="nsew", padx=4, pady=4)
            metrics.columnconfigure(i, weight=1)
            self.stat_tiles[key] = tile

        detail = tk.Frame(right, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        detail.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        tk.Label(detail, text="DETAILS", bg=CARD, fg=MUTED, font=(FONT, 9, "bold")).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self.detail_host = tk.Frame(detail, bg=CARD)
        self.detail_host.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self.detail_canvas = tk.Canvas(self.detail_host, bg=CARD, highlightthickness=0)
        self.detail_scroll = tk.Scrollbar(self.detail_host, orient="vertical", command=self.detail_canvas.yview)
        self.detail_inner = tk.Frame(self.detail_canvas, bg=CARD)
        self.detail_inner.bind(
            "<Configure>",
            lambda e: self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all")),
        )
        self.detail_canvas.create_window((0, 0), window=self.detail_inner, anchor="nw")
        self.detail_canvas.configure(yscrollcommand=self.detail_scroll.set)
        self.detail_canvas.pack(side="left", fill="both", expand=True)
        self.detail_scroll.pack(side="right", fill="y")

    def _build_battery(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        hero = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        hero.pack(fill="x")
        hero_inner = tk.Frame(hero, bg=CARD)
        hero_inner.pack(fill="x", padx=20, pady=18)
        hero_inner.columnconfigure(0, weight=1)

        self.batt_title = tk.StringVar(value="Battery")
        self.batt_health = tk.StringVar(value="—")
        self.batt_sub = tk.StringVar(value="")
        self.batt_reason = tk.StringVar(value="")

        tk.Label(
            hero_inner,
            textvariable=self.batt_title,
            bg=CARD,
            fg=TEXT,
            font=(FONT_DISPLAY, 22, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.batt_pill = StatusPill(hero_inner, self.batt_health)
        self.batt_pill.grid(row=0, column=1, sticky="e")
        tk.Label(hero_inner, textvariable=self.batt_sub, bg=CARD, fg=MUTED, font=(FONT, 11)).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        tk.Label(
            hero_inner,
            textvariable=self.batt_reason,
            bg=CARD,
            fg=MUTED,
            font=(FONT, 11),
            wraplength=760,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        bars = tk.Frame(hero_inner, bg=CARD)
        bars.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        bars.columnconfigure(1, weight=1)
        self.charge_pct_var = tk.StringVar(value="—")
        self.maxcap_pct_var = tk.StringVar(value="—")
        self._bar_row(bars, 0, "Charge", "charge_bar", self.charge_pct_var)
        self._bar_row(bars, 1, "Full charge vs design", "maxcap_bar", self.maxcap_pct_var, pady=(12, 0))

        cap_row = tk.Frame(parent, bg=BG)
        cap_row.pack(fill="x", pady=(12, 0))
        for i, (key, title) in enumerate(
            [
                ("design_mah", "Design Capacity"),
                ("full_mah", "Full Charge Capacity"),
                ("current_mah", "Current Charge"),
            ]
        ):
            tile = MetricTile(cap_row, title, large=True)
            tile.grid(row=0, column=i, sticky="nsew", padx=4, pady=4)
            cap_row.columnconfigure(i, weight=1)
            self.batt_cap_tiles[key] = tile

        metrics = tk.Frame(parent, bg=BG)
        metrics.pack(fill="x", pady=(8, 0))
        for i, (key, title) in enumerate(BATTERY_SECONDARY):
            tile = MetricTile(metrics, title)
            tile.grid(row=i // 5, column=i % 5, sticky="nsew", padx=4, pady=4)
            metrics.columnconfigure(i % 5, weight=1)
            self.batt_tiles[key] = tile

        tip = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        tip.pack(fill="x", pady=(12, 0))
        tk.Label(
            tip,
            text="Design / Full Charge / Current (mAh) are read directly from AppleSmartBattery via IOKit. "
            "Desktop Macs without a battery show as not installed.",
            bg=CARD,
            fg=MUTED,
            font=(FONT, 11),
            wraplength=900,
            justify="left",
            padx=16,
            pady=14,
        ).pack(anchor="w")

    def _bar_row(
        self,
        parent: tk.Frame,
        row: int,
        label: str,
        attr: str,
        pct_var: tk.StringVar,
        pady: tuple[int, int] = (0, 0),
    ) -> None:
        tk.Label(parent, text=label, bg=CARD, fg=MUTED, font=(FONT, 10)).grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=pady
        )
        bar = ProgressBar(parent)
        bar.grid(row=row, column=1, sticky="ew", pady=pady)
        setattr(self, attr, bar)
        tk.Label(parent, textvariable=pct_var, bg=CARD, fg=MUTED, font=(FONT, 11, "bold")).grid(
            row=row, column=2, sticky="e", padx=(12, 0), pady=pady
        )

    def _show_section(self, name: str) -> None:
        if self._section == name:
            return
        self._section = name
        self.storage_frame.pack_forget()
        self.battery_frame.pack_forget()
        self.thermal_frame.pack_forget()
        self.seg_storage.set_active(False)
        self.seg_battery.set_active(False)
        self.seg_thermal.set_active(False)
        if name == "battery":
            self.battery_frame.pack(fill="both", expand=True)
            self.seg_battery.set_active(True)
            if not get_controller().active:
                self._stop_thermal_live()
            else:
                self._cancel_thermal_job()
                self._thermal_job = self.after(self._thermal_interval_ms, self._thermal_tick)
        elif name == "thermal":
            self.thermal_frame.pack(fill="both", expand=True)
            self.seg_thermal.set_active(True)
            self._start_thermal_live()
        else:
            self.storage_frame.pack(fill="both", expand=True)
            self.seg_storage.set_active(True)
            if not get_controller().active:
                self._stop_thermal_live()
            else:
                self._cancel_thermal_job()
                self._thermal_job = self.after(self._thermal_interval_ms, self._thermal_tick)

    def _thermal_live_needed(self) -> bool:
        return self._section == "thermal" or get_controller().active

    def _cancel_thermal_job(self) -> None:
        if self._thermal_job is not None:
            try:
                self.after_cancel(self._thermal_job)
            except tk.TclError:
                pass
            self._thermal_job = None

    def _start_thermal_live(self) -> None:
        self._cancel_thermal_job()
        self._thermal_tick()

    def _stop_thermal_live(self) -> None:
        self._cancel_thermal_job()
        # Keep polling while manual control is active even off-tab
        if get_controller().active:
            self._thermal_job = self.after(self._thermal_interval_ms, self._thermal_tick)

    def _thermal_tick(self) -> None:
        self._thermal_job = None
        if not self._thermal_live_needed():
            return

        def worker() -> None:
            snap = scan_thermal()
            self.after(0, lambda s=snap: self._on_thermal_live(s))

        threading.Thread(target=worker, daemon=True).start()

    def _on_thermal_live(self, snap: ThermalSnapshot) -> None:
        self.thermal = snap
        if self.thermal_panel is not None:
            self.thermal_panel.update_snapshot(snap)
        if self._section == "thermal" and snap.hottest_c is not None:
            mode = "Manual" if get_controller().active else "Auto"
            rpm = "—"
            if snap.fans and snap.fans[0].rpm is not None:
                rpm = f"{snap.fans[0].rpm:.0f} RPM"
            self.status_var.set(f"Thermal live · {mode} · {snap.hottest_c:.0f}°C · {rpm}")
        if self._thermal_live_needed():
            self._thermal_job = self.after(self._thermal_interval_ms, self._thermal_tick)

    def toggle_auto_refresh(self) -> None:
        if self._auto_refresh:
            self._stop_auto_refresh()
        else:
            self._start_auto_refresh()

    def _start_auto_refresh(self) -> None:
        self._auto_refresh = True
        self.auto_btn.set_toggle(True, "Auto Refresh: On", "Auto Refresh: Off")
        self._set_status(f"Live updates every {self._auto_interval_ms // 1000}s")
        self._schedule_auto_refresh()

    def _stop_auto_refresh(self) -> None:
        self._auto_refresh = False
        self.auto_btn.set_toggle(False, "Auto Refresh: On", "Auto Refresh: Off")
        if self._auto_job is not None:
            try:
                self.after_cancel(self._auto_job)
            except tk.TclError:
                pass
            self._auto_job = None

    def _schedule_auto_refresh(self) -> None:
        if not self._auto_refresh:
            return
        if self._auto_job is not None:
            try:
                self.after_cancel(self._auto_job)
            except tk.TclError:
                pass
        self._auto_job = self.after(self._auto_interval_ms, self._auto_tick)

    def _auto_tick(self) -> None:
        self._auto_job = None
        if not self._auto_refresh:
            return
        self.refresh(quiet=True)
        self._schedule_auto_refresh()

    def _ensure_status_item(self) -> None:
        if self._menu_bar_controller is not None and self._menu_bar_controller.available:
            return
        login_on = is_login_item_enabled()
        self._menu_bar_controller = MenuBarController(
            on_open=self._show_window,
            on_hide=self._hide_window,
            on_refresh=self.refresh,
            on_toggle_menu_bar=self._set_menu_bar_mode,
            on_toggle_login=self._set_open_at_login,
            on_quit=self._on_quit,
            menu_bar_enabled=self._menu_bar_mode,
            login_enabled=login_on,
        )

    def _apply_menu_bar_policy(self) -> bool:
        if not set_activation_policy_menu_bar_only(True):
            return False
        self._ensure_status_item()
        if self._menu_bar_controller is None or not self._menu_bar_controller.available:
            set_activation_policy_menu_bar_only(False)
            return False
        return True

    def _show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(50, lambda: self.attributes("-topmost", False))

    def _hide_window(self) -> None:
        self.withdraw()

    def _set_menu_bar_mode(self, enabled: bool) -> None:
        if enabled == self._menu_bar_mode:
            return
        if enabled:
            if not self._apply_menu_bar_policy():
                messagebox.showwarning(
                    "Menu bar mode",
                    "PyObjC is required for menu bar mode.\n  pip3 install pyobjc-framework-Cocoa",
                )
                if self._menu_bar_controller is not None:
                    self._menu_bar_controller.set_menu_bar_checked(False)
                return
        else:
            set_activation_policy_menu_bar_only(False)
            self._show_window()
        self._menu_bar_mode = enabled
        self._prefs["menu_bar_mode"] = enabled
        save_prefs(self._prefs)
        self.menu_bar_btn.set_toggle(enabled, "Menu Bar: On", "Menu Bar: Off")
        if self._menu_bar_controller is not None:
            self._menu_bar_controller.set_menu_bar_checked(enabled)

    def toggle_menu_bar_mode(self) -> None:
        self._set_menu_bar_mode(not self._menu_bar_mode)

    def _set_open_at_login(self, enabled: bool) -> None:
        ok, detail = set_open_at_login(enabled)
        actual = is_login_item_enabled()
        self.login_btn.set_toggle(actual, "Login Item: On", "Login Item: Off")
        if self._menu_bar_controller is not None:
            self._menu_bar_controller.set_login_checked(actual)
        if not ok and detail:
            messagebox.showinfo("Open at login", detail)

    def toggle_open_at_login(self) -> None:
        self._set_open_at_login(not is_login_item_enabled())

    def _on_close(self) -> None:
        if self._menu_bar_mode:
            self._hide_window()
            return
        self._on_quit()

    def _on_quit(self) -> None:
        self._stop_auto_refresh()
        self._stop_thermal_live()
        if self._status_pulse_job is not None:
            try:
                self.after_cancel(self._status_pulse_job)
            except tk.TclError:
                pass
        for bar in (self.charge_bar, self.maxcap_bar):
            if bar is not None:
                bar.cancel()
        if self._menu_bar_controller is not None:
            self._menu_bar_controller.remove()
        try:
            get_controller().shutdown()
        except Exception:  # noqa: BLE001
            pass
        self.destroy()

    def _set_status(self, text: str, *, pulse: bool = False) -> None:
        self._status_base = text
        self.status_var.set(text)
        self.status_lbl.configure(fg=MUTED)
        if pulse:
            self._pulse_status()

    def _pulse_status(self) -> None:
        if self._status_pulse_job is not None:
            try:
                self.after_cancel(self._status_pulse_job)
            except tk.TclError:
                pass
        self.status_var.set("Updated just now")
        self.status_lbl.configure(fg=ACCENT)

        def restore() -> None:
            self.status_var.set(self._status_base)
            self.status_lbl.configure(fg=MUTED)
            self._status_pulse_job = None

        self._status_pulse_job = self.after(900, restore)

    def _set_loading(self, loading: bool) -> None:
        for tile in self.stat_tiles.values():
            tile.set_loading(loading)
        for tile in self.batt_cap_tiles.values():
            tile.set_loading(loading)
        for tile in self.batt_tiles.values():
            tile.set_loading(loading)

    def _sync_drive_list(self, drives: list[DriveInfo]) -> None:
        if self._empty_lbl is not None:
            self._empty_lbl.destroy()
            self._empty_lbl = None

        seen = {d.device for d in drives}
        for device, row in list(self._drive_rows.items()):
            if device not in seen:
                row.destroy()
                del self._drive_rows[device]

        if not drives:
            self._empty_lbl = tk.Label(
                self.drive_list_host,
                text="No drives found",
                bg=CARD,
                fg=MUTED,
                font=(FONT, 11),
                pady=24,
            )
            self._empty_lbl.pack(fill="x")
            return

        for drive in drives:
            existing = self._drive_rows.get(drive.device)
            if existing is not None:
                existing.update_drive(drive)
            else:
                row = DriveRow(self.drive_list_host, drive, self._show_drive)
                self._drive_rows[drive.device] = row

        for drive in drives:
            self._drive_rows[drive.device].pack_forget()
        for drive in drives:
            self._drive_rows[drive.device].pack(fill="x", pady=2)

    def refresh(self, quiet: bool = False) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        if not quiet:
            self._set_status("Scanning…")
            self._set_loading(True)

        def worker() -> None:
            err: Exception | None = None
            drives: list[DriveInfo] = []
            battery: BatteryInfo | None = None
            thermal: ThermalSnapshot | None = None
            try:
                drives = scan_drives(ssd_only=False)
                battery = scan_battery()
                thermal = scan_thermal()
            except Exception as exc:  # noqa: BLE001
                err = exc
            self.after(
                0,
                lambda d=drives, b=battery, t=thermal, e=err, q=quiet: self._on_scan_done(
                    d, b, t, e, quiet=q
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(
        self,
        drives: list[DriveInfo],
        battery: BatteryInfo | None,
        thermal: ThermalSnapshot | None,
        err: Exception | None,
        *,
        quiet: bool,
    ) -> None:
        try:
            if err is not None:
                if not quiet:
                    messagebox.showerror("Scan failed", str(err))
                self._set_status("Scan failed")
                return

            self.drives = drives
            self.battery = battery
            self.thermal = thermal
            selected_device = self._selected_device
            self._sync_drive_list(self.drives)
            self._show_battery(self.battery)
            if thermal is not None and self.thermal_panel is not None:
                self.thermal_panel.update_snapshot(thermal)

            batt_note = "battery" if self.battery and self.battery.installed else "no battery"
            thermal_note = ""
            if thermal and thermal.hottest_c is not None:
                thermal_note = f" · {thermal.hottest_c:.0f}°C"
            live = "Live · " if self._auto_refresh else ""
            summary = f"{live}{len(self.drives)} drive(s) · {batt_note}{thermal_note}"
            self._set_status(summary, pulse=True)

            target = None
            if selected_device:
                for drive in self.drives:
                    if drive.device == selected_device:
                        target = drive
                        break
            if target is None and self.drives:
                target = self.drives[0]
            if target is not None:
                self._show_drive(target)
            else:
                self._clear_detail()
        finally:
            self._set_loading(False)
            self._refreshing = False

    def _clear_detail(self) -> None:
        self._selected = None
        self._selected_device = None
        self.model_var.set("No drive selected")
        self.health_var.set("—")
        self.subtitle_var.set("")
        self.reason_var.set("")
        self.health_pill.set_status("—", None, flash=False)
        for tile in self.stat_tiles.values():
            tile.value.set("—")
        for child in self.detail_inner.winfo_children():
            child.destroy()

    def _detail_row(self, name: str, raw: str, index: int) -> None:
        bg = SURFACE if index % 2 == 0 else CARD
        row = tk.Frame(self.detail_inner, bg=bg)
        row.pack(fill="x")
        tk.Label(row, text=name, bg=bg, fg=MUTED, font=(FONT, 11), width=28, anchor="w").pack(
            side="left", padx=(12, 8), pady=7
        )
        tk.Label(row, text=raw, bg=bg, fg=TEXT, font=(FONT, 11), anchor="w").pack(
            side="left", fill="x", expand=True, pady=7
        )

    def _show_drive(self, drive: DriveInfo) -> None:
        self._selected = drive
        self._selected_device = drive.device
        for row in self._drive_rows.values():
            row.set_selected(row.drive.device == drive.device)

        self.model_var.set(drive.model)
        self.health_var.set(f"  {drive.health.value}  ")
        self.health_pill.set_status(drive.health.value, drive.health)

        kind = "SSD" if drive.is_ssd else "Disk"
        loc = "Internal" if drive.is_internal else "External"
        status = drive.macos_smart_status or "Unavailable"
        self.subtitle_var.set(f"{drive.device_node}  ·  {kind}  ·  {loc}  ·  {status}")
        self.reason_var.set(" · ".join(drive.health_reasons) if drive.health_reasons else (drive.error or ""))

        remaining = drive.health_remaining_pct
        primary_values = {
            "temp": f"{drive.temperature_c} °C" if drive.temperature_c is not None else "—",
            "spare": f"{drive.available_spare} %" if drive.available_spare is not None else "—",
            "health_left": f"{remaining} %" if remaining is not None else "—",
            "capacity": drive.capacity_human,
        }
        for key, val in primary_values.items():
            self.stat_tiles[key].value.set(val)

        secondary = {
            "used": f"{drive.percentage_used} %" if drive.percentage_used is not None else "—",
            "read_tb": f"{drive.data_read_tb:.2f} TB" if drive.data_read_tb is not None else "—",
            "written_tb": f"{drive.data_written_tb:.2f} TB" if drive.data_written_tb is not None else "—",
            "power_on": str(drive.power_on_hours) if drive.power_on_hours is not None else "—",
            "cycles": str(drive.power_cycles) if drive.power_cycles is not None else "—",
            "unsafe": str(drive.unsafe_shutdowns) if drive.unsafe_shutdowns is not None else "—",
            "media": str(drive.media_errors) if drive.media_errors is not None else "—",
            "critical": f"0x{drive.critical_warning:02x}" if drive.critical_warning is not None else "—",
        }

        for child in self.detail_inner.winfo_children():
            child.destroy()

        idx = 0
        for key, title in STORAGE_SECONDARY_KEYS:
            self._detail_row(title, secondary[key], idx)
            idx += 1

        if drive.attributes:
            hdr = tk.Frame(self.detail_inner, bg=CARD)
            hdr.pack(fill="x", pady=(10, 2))
            tk.Label(
                hdr,
                text="ATTRIBUTES",
                bg=CARD,
                fg=MUTED,
                font=(FONT, 9, "bold"),
                anchor="w",
            ).pack(anchor="w", padx=12)
            for attr in drive.attributes:
                self._detail_row(attr.name, attr.raw, idx)
                idx += 1

    def _show_battery(self, battery: BatteryInfo | None) -> None:
        if battery is None:
            return

        self.batt_title.set(battery.device_name or "Battery")
        label = battery.health.value if battery.installed else "N/A"
        self.batt_health.set(f"  {label}  ")
        self.batt_pill.set_status(label, battery.health if battery.installed else None)
        self.batt_sub.set(f"{battery.status_label}  ·  {battery.power_source or '—'}")
        self.batt_reason.set(" · ".join(battery.health_reasons) if battery.health_reasons else (battery.error or ""))

        charge = float(battery.charge_percent or 0) if battery.installed else 0.0
        maxcap = float(battery.max_capacity_percent or 0) if battery.installed else 0.0
        assert self.charge_bar is not None and self.maxcap_bar is not None
        self.charge_bar.set_percent(charge)
        self.maxcap_bar.set_percent(maxcap)
        self.charge_pct_var.set(f"{battery.charge_percent}%" if battery.charge_percent is not None else "—")
        self.maxcap_pct_var.set(
            f"{battery.max_capacity_percent}%" if battery.max_capacity_percent is not None else "—"
        )

        self.batt_cap_tiles["design_mah"].value.set(
            f"{battery.design_capacity_mah} mAh" if battery.design_capacity_mah else "—"
        )
        self.batt_cap_tiles["full_mah"].value.set(
            f"{battery.max_capacity_mah} mAh" if battery.max_capacity_mah else "—"
        )
        self.batt_cap_tiles["current_mah"].value.set(
            f"{battery.current_capacity_mah} mAh" if battery.current_capacity_mah else "—"
        )

        self.batt_tiles["cycles"].value.set(str(battery.cycle_count) if battery.cycle_count is not None else "—")
        self.batt_tiles["design_cycles"].value.set(
            str(battery.design_cycle_count) if battery.design_cycle_count is not None else "—"
        )
        self.batt_tiles["temp"].value.set(
            f"{battery.temperature_c} °C" if battery.temperature_c is not None else "—"
        )
        self.batt_tiles["voltage"].value.set(f"{battery.voltage_mv} mV" if battery.voltage_mv else "—")
        if battery.amperage_ma is None:
            self.batt_tiles["amperage"].value.set("—")
        elif battery.amperage_ma > 0:
            self.batt_tiles["amperage"].value.set(f"+{battery.amperage_ma} mA (charging)")
        elif battery.amperage_ma < 0:
            self.batt_tiles["amperage"].value.set(f"{battery.amperage_ma} mA (discharging)")
        else:
            self.batt_tiles["amperage"].value.set("0 mA")
        self.batt_tiles["condition"].value.set(
            battery.condition or ("—" if battery.installed else "Not installed")
        )
        self.batt_tiles["source"].value.set(battery.power_source or "—")
        self.batt_tiles["serial"].value.set(battery.serial or "—")
        self.batt_tiles["manufacturer"].value.set(battery.manufacturer or "—")
        if battery.time_remaining_min is not None and battery.installed:
            mins = battery.time_remaining_min
            self.batt_tiles["time_left"].value.set(f"{mins // 60}h {mins % 60}m")
        else:
            self.batt_tiles["time_left"].value.set("—")

    def _require_data(self) -> bool:
        if not self.drives and not (self.battery and self.battery.installed):
            messagebox.showinfo("Nothing to export", "Scan first.")
            return False
        return True

    def export_json_dialog(self) -> None:
        if not self._require_data():
            return
        path = filedialog.asksaveasfilename(
            title="Export JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialfile="hardware-info.json",
        )
        if not path:
            return
        export_json(self.drives, path, include_raw=False, battery=self.battery)
        self._set_status(f"Exported {Path(path).name}", pulse=True)
        messagebox.showinfo("Exported", f"Saved JSON report to:\n{path}")

    def export_html_dialog(self) -> None:
        if not self._require_data():
            return
        path = filedialog.asksaveasfilename(
            title="Export HTML",
            defaultextension=".html",
            filetypes=[("HTML", "*.html"), ("All files", "*.*")],
            initialfile="hardware-info.html",
        )
        if not path:
            return
        export_html(self.drives, path, battery=self.battery)
        self._set_status(f"Exported {Path(path).name}", pulse=True)
        messagebox.showinfo("Exported", f"Saved HTML report to:\n{path}")


def run(*, menu_bar_mode: bool | None = None) -> None:
    app = App(menu_bar_mode=menu_bar_mode)
    app.mainloop()
