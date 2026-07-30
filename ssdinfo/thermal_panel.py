"""Thermal / fan-curve panel for the main Tk UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog

from .fan_control import get_controller
from .gui_theme import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_SOFT,
    BAD,
    BG,
    CARD,
    CAUTION,
    FONT,
    FONT_DISPLAY,
    GOOD,
    LINE,
    MUTED,
    SURFACE,
    SURFACE_HOVER,
    TEXT,
)
from .models import FanCurvePoint, FanProfile, ThermalSnapshot
from .profiles import delete_profile, load_profiles, upsert_profile


class _Btn(tk.Label):
    def __init__(self, parent, text, command, *, primary: bool = False) -> None:
        self._command = command
        bg = ACCENT if primary else SURFACE
        fg = "#FFFFFF" if primary else TEXT
        super().__init__(
            parent,
            text=f"  {text}  ",
            bg=bg,
            fg=fg,
            font=(FONT, 11, "bold" if primary else "normal"),
            padx=10,
            pady=8,
            highlightthickness=0 if primary else 1,
            highlightbackground=LINE,
        )
        self._bg = bg
        self._hover = ACCENT_HOVER if primary else SURFACE_HOVER
        self.bind("<Enter>", lambda _e: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda _e: self.configure(bg=self._bg))
        self.bind("<Button-1>", lambda _e: self._command())


class ThermalPanel(tk.Frame):
    def __init__(self, parent: tk.Misc, *, set_status) -> None:
        super().__init__(parent, bg=BG)
        self._set_status = set_status
        self._profiles = load_profiles()
        self._current = self._profiles[1] if len(self._profiles) > 1 else self._profiles[0]
        self._points = [FanCurvePoint(p.temp_c, p.duty_pct) for p in self._current.points]
        self._snapshot: ThermalSnapshot | None = None
        self._drag_idx: int | None = None
        self._ctrl = get_controller()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build()

    def _build(self) -> None:
        hero = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        hero.grid(row=0, column=0, sticky="ew")
        inner = tk.Frame(hero, bg=CARD)
        inner.pack(fill="x", padx=20, pady=16)
        inner.columnconfigure(0, weight=1)

        self.title_var = tk.StringVar(value="Thermal")
        self.mode_var = tk.StringVar(value="Auto")
        tk.Label(inner, textvariable=self.title_var, bg=CARD, fg=TEXT, font=(FONT_DISPLAY, 22, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.mode_pill = tk.Label(
            inner, textvariable=self.mode_var, bg=ACCENT_SOFT, fg=GOOD, font=(FONT, 12, "bold"), padx=12, pady=6
        )
        self.mode_pill.grid(row=0, column=1, sticky="e")
        self.sub_var = tk.StringVar(value="Apple Silicon sensors and fan curve")
        tk.Label(inner, textvariable=self.sub_var, bg=CARD, fg=MUTED, font=(FONT, 11)).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        tiles = tk.Frame(self, bg=BG)
        tiles.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.tile_vars = {
            "cpu": tk.StringVar(value="—"),
            "gpu": tk.StringVar(value="—"),
            "hot": tk.StringVar(value="—"),
            "rpm": tk.StringVar(value="—"),
        }
        for i, (key, label) in enumerate(
            [("cpu", "CPU"), ("gpu", "GPU"), ("hot", "Hottest"), ("rpm", "Fan RPM")]
        ):
            cell = tk.Frame(tiles, bg=CARD, highlightthickness=1, highlightbackground=LINE)
            cell.grid(row=0, column=i, sticky="nsew", padx=4)
            tiles.columnconfigure(i, weight=1)
            tk.Label(cell, text=label.upper(), bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w", padx=14, pady=(12, 0))
            tk.Label(cell, textvariable=self.tile_vars[key], bg=CARD, fg=TEXT, font=(FONT_DISPLAY, 18, "bold")).pack(
                anchor="w", padx=14, pady=(6, 12)
            )

        body = tk.Frame(self, bg=BG)
        body.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        tk.Label(left, text="FAN CURVE", bg=CARD, fg=MUTED, font=(FONT, 9, "bold")).pack(
            anchor="w", padx=14, pady=(12, 4)
        )
        self.canvas = tk.Canvas(left, bg=SURFACE, highlightthickness=0, height=280)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.canvas.bind("<Configure>", lambda _e: self._draw_curve())
        self.canvas.bind("<Button-1>", self._on_canvas_down)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_up)

        tip = tk.Label(
            left,
            text="X = temperature °C · Y = fan duty % · drag points to edit",
            bg=CARD,
            fg=MUTED,
            font=(FONT, 10),
        )
        tip.pack(anchor="w", padx=14, pady=(0, 10))

        right = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        right.grid(row=0, column=1, sticky="nsew")
        tk.Label(right, text="PROFILES", bg=CARD, fg=MUTED, font=(FONT, 9, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6)
        )

        self.profile_var = tk.StringVar(value=self._current.name)
        self.profile_menu = tk.OptionMenu(right, self.profile_var, *[p.name for p in self._profiles], command=self._on_profile)
        self.profile_menu.configure(bg=SURFACE, fg=TEXT, font=(FONT, 11), highlightthickness=1, highlightbackground=LINE)
        self.profile_menu.pack(fill="x", padx=14, pady=(0, 8))

        btns = tk.Frame(right, bg=CARD)
        btns.pack(fill="x", padx=14, pady=(0, 8))
        self._mk_btn(btns, "Apply Manual", self._apply, primary=True).pack(fill="x", pady=2)
        self._mk_btn(btns, "Stop → Auto", self._stop).pack(fill="x", pady=2)
        self._mk_btn(btns, "Save Profile", self._save).pack(fill="x", pady=2)
        self._mk_btn(btns, "Save As…", self._save_as).pack(fill="x", pady=2)
        self._mk_btn(btns, "Delete Profile", self._delete).pack(fill="x", pady=2)

        self.warn_var = tk.StringVar(
            value="Apply Manual asks for password once. Stop returns to Auto without another prompt."
        )
        tk.Label(right, textvariable=self.warn_var, bg=CARD, fg=MUTED, font=(FONT, 10), wraplength=260, justify="left").pack(
            anchor="w", padx=14, pady=(4, 12)
        )

        detail = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        detail.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        tk.Label(detail, text="SENSORS", bg=CARD, fg=MUTED, font=(FONT, 9, "bold")).pack(
            anchor="w", padx=14, pady=(10, 4)
        )
        self.sensor_host = tk.Frame(detail, bg=CARD)
        self.sensor_host.pack(fill="x", padx=8, pady=(0, 10))

    def _mk_btn(self, parent, text, command, primary: bool = False):
        return _Btn(parent, text, command, primary=primary)

    def update_snapshot(self, snap: ThermalSnapshot) -> None:
        self._snapshot = snap
        if snap.error:
            self.sub_var.set(snap.error)
            return
        if not snap.apple_silicon:
            self.sub_var.set("Thermal control is Apple Silicon only")
            self.warn_var.set("This Mac is not Apple Silicon.")
            return
        if snap.fanless:
            self.sub_var.set("Fanless Mac — monitoring only")
            self.warn_var.set("No fans detected. Curve Apply is disabled.")
        else:
            mode = "Manual" if self._ctrl.active else "Auto"
            self.mode_var.set(mode)
            self.mode_pill.configure(
                bg=CAUTION if self._ctrl.active else ACCENT_SOFT,
                fg=TEXT if self._ctrl.active else GOOD,
            )
            self.sub_var.set(f"{snap.fan_count} fan(s) · {len(snap.sensors)} sensors")

        self.tile_vars["cpu"].set(f"{snap.cpu_c:.1f} °C" if snap.cpu_c is not None else "—")
        self.tile_vars["gpu"].set(f"{snap.gpu_c:.1f} °C" if snap.gpu_c is not None else "—")
        self.tile_vars["hot"].set(f"{snap.hottest_c:.1f} °C" if snap.hottest_c is not None else "—")
        if snap.fans and snap.fans[0].rpm is not None:
            self.tile_vars["rpm"].set(f"{snap.fans[0].rpm:.0f}")
        else:
            self.tile_vars["rpm"].set("—")

        for child in self.sensor_host.winfo_children():
            child.destroy()
        for i, s in enumerate(snap.sensors[:12]):
            row = tk.Frame(self.sensor_host, bg=SURFACE if i % 2 == 0 else CARD)
            row.pack(fill="x")
            tk.Label(row, text=s.label, bg=row["bg"], fg=MUTED, font=(FONT, 11), width=16, anchor="w").pack(
                side="left", padx=(10, 6), pady=5
            )
            tk.Label(row, text=f"{s.celsius:.1f} °C", bg=row["bg"], fg=TEXT, font=(FONT, 11), anchor="w").pack(
                side="left", pady=5
            )

        self._draw_curve()

    def _refresh_menu(self) -> None:
        menu = self.profile_menu["menu"]
        menu.delete(0, "end")
        for p in self._profiles:
            menu.add_command(label=p.name, command=lambda n=p.name: self._on_profile(n))

    def _on_profile(self, name: str) -> None:
        self.profile_var.set(name)
        for p in self._profiles:
            if p.name == name:
                self._current = p
                self._points = [FanCurvePoint(x.temp_c, x.duty_pct) for x in p.points]
                self._draw_curve()
                break

    def _current_profile_obj(self) -> FanProfile:
        return FanProfile(
            name=self._current.name,
            points=[FanCurvePoint(p.temp_c, p.duty_pct) for p in self._points],
            builtin=self._current.builtin,
            emergency_c=self._current.emergency_c,
        )

    def _apply(self) -> None:
        snap = self._snapshot
        if snap is None or not snap.apple_silicon:
            messagebox.showinfo("Thermal", "Apple Silicon only.")
            return
        if snap.fanless:
            messagebox.showinfo("Thermal", "No fans on this Mac.")
            return
        prof = self._current_profile_obj()
        ok, msg = self._ctrl.apply(prof)
        if ok:
            self.mode_var.set("Manual")
            self.mode_pill.configure(bg=CAUTION, fg=TEXT)
            self._set_status(msg, pulse=True)
        else:
            messagebox.showerror("Fan control", msg)

    def _stop(self) -> None:
        ok, msg = self._ctrl.stop()
        self.mode_var.set("Auto")
        self.mode_pill.configure(bg=ACCENT_SOFT, fg=GOOD)
        self._set_status(msg, pulse=True)
        if not ok:
            messagebox.showwarning("Fan control", msg)

    def _save(self) -> None:
        prof = self._current_profile_obj()
        if prof.builtin:
            messagebox.showinfo("Profiles", "Built-in profiles are read-only. Use Save As…")
            return
        self._profiles = upsert_profile(self._profiles, prof)
        self._refresh_menu()
        self._set_status(f"Saved profile {prof.name}", pulse=True)

    def _save_as(self) -> None:
        name = simpledialog.askstring("Save profile", "Profile name:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if any(p.name == name and p.builtin for p in self._profiles):
            messagebox.showinfo("Profiles", "That name is reserved for a built-in profile.")
            return
        prof = FanProfile(
            name=name,
            points=[FanCurvePoint(p.temp_c, p.duty_pct) for p in self._points],
            builtin=False,
            emergency_c=self._current.emergency_c,
        )
        self._profiles = upsert_profile(self._profiles, prof)
        self._current = prof
        self.profile_var.set(name)
        self._refresh_menu()
        self._set_status(f"Saved profile {name}", pulse=True)

    def _delete(self) -> None:
        if self._current.builtin:
            messagebox.showinfo("Profiles", "Cannot delete built-in profiles.")
            return
        if not messagebox.askyesno("Delete", f"Delete profile “{self._current.name}”?"):
            return
        self._profiles = delete_profile(self._profiles, self._current.name)
        self._current = self._profiles[1] if len(self._profiles) > 1 else self._profiles[0]
        self._points = [FanCurvePoint(p.temp_c, p.duty_pct) for p in self._current.points]
        self.profile_var.set(self._current.name)
        self._refresh_menu()
        self._draw_curve()

    def _plot_map(self, w: int, h: int):
        pad_l, pad_r, pad_t, pad_b = 40, 16, 16, 28
        return pad_l, pad_r, pad_t, pad_b, w - pad_l - pad_r, h - pad_t - pad_b

    def _temp_to_x(self, temp: float, pad_l: int, plot_w: int) -> float:
        return pad_l + (max(30, min(100, temp)) - 30) / 70.0 * plot_w

    def _duty_to_y(self, duty: float, pad_t: int, plot_h: int) -> float:
        return pad_t + (1.0 - max(0, min(100, duty)) / 100.0) * plot_h

    def _xy_to_point(self, x: float, y: float, pad_l: int, pad_t: int, plot_w: int, plot_h: int):
        temp = 30 + (x - pad_l) / max(1, plot_w) * 70.0
        duty = (1.0 - (y - pad_t) / max(1, plot_h)) * 100.0
        return max(30.0, min(100.0, temp)), max(0.0, min(100.0, duty))

    def _draw_curve(self) -> None:
        c = self.canvas
        c.delete("all")
        w = max(c.winfo_width(), 100)
        h = max(c.winfo_height(), 100)
        pad_l, pad_r, pad_t, pad_b, plot_w, plot_h = self._plot_map(w, h)

        # grid
        for t in (40, 55, 70, 85, 100):
            x = self._temp_to_x(t, pad_l, plot_w)
            c.create_line(x, pad_t, x, pad_t + plot_h, fill=LINE)
            c.create_text(x, pad_t + plot_h + 12, text=f"{t}°", fill=MUTED, font=(FONT, 9))
        for d in (0, 25, 50, 75, 100):
            y = self._duty_to_y(d, pad_t, plot_h)
            c.create_line(pad_l, y, pad_l + plot_w, y, fill=LINE)
            c.create_text(pad_l - 16, y, text=f"{d}", fill=MUTED, font=(FONT, 9))

        pts = sorted(self._points, key=lambda p: p.temp_c)
        if len(pts) >= 2:
            coords = []
            for p in pts:
                coords.extend(
                    [self._temp_to_x(p.temp_c, pad_l, plot_w), self._duty_to_y(p.duty_pct, pad_t, plot_h)]
                )
            c.create_line(*coords, fill=ACCENT, width=2, smooth=False)

        for i, p in enumerate(pts):
            x = self._temp_to_x(p.temp_c, pad_l, plot_w)
            y = self._duty_to_y(p.duty_pct, pad_t, plot_h)
            r = 6
            c.create_oval(x - r, y - r, x + r, y + r, fill=ACCENT, outline=CARD, width=2, tags=("pt", f"i{i}"))

        snap = self._snapshot
        if snap and snap.hottest_c is not None:
            x = self._temp_to_x(snap.hottest_c, pad_l, plot_w)
            c.create_line(x, pad_t, x, pad_t + plot_h, fill=BAD, dash=(4, 3), width=2)
            c.create_text(x + 4, pad_t + 10, text="now", anchor="w", fill=BAD, font=(FONT, 9, "bold"))

        self._points = pts

    def _hit_point(self, x: float, y: float) -> int | None:
        w = max(self.canvas.winfo_width(), 100)
        h = max(self.canvas.winfo_height(), 100)
        pad_l, _, pad_t, _, plot_w, plot_h = self._plot_map(w, h)
        for i, p in enumerate(self._points):
            px = self._temp_to_x(p.temp_c, pad_l, plot_w)
            py = self._duty_to_y(p.duty_pct, pad_t, plot_h)
            if (px - x) ** 2 + (py - y) ** 2 <= 12**2:
                return i
        return None

    def _on_canvas_down(self, event) -> None:
        self._drag_idx = self._hit_point(event.x, event.y)

    def _on_canvas_drag(self, event) -> None:
        if self._drag_idx is None:
            return
        w = max(self.canvas.winfo_width(), 100)
        h = max(self.canvas.winfo_height(), 100)
        pad_l, _, pad_t, _, plot_w, plot_h = self._plot_map(w, h)
        temp, duty = self._xy_to_point(event.x, event.y, pad_l, pad_t, plot_w, plot_h)
        # lock endpoints somewhat on temp axis edges
        self._points[self._drag_idx] = FanCurvePoint(temp, duty)
        self._draw_curve()

    def _on_canvas_up(self, _event) -> None:
        self._drag_idx = None
        self._points = sorted(self._points, key=lambda p: p.temp_c)
        self._draw_curve()
