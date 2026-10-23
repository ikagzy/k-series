import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

import psutil

from k_optimizer import classifier, cli, monitor, probalance, ramclean, theme, throttle, winutil
from k_optimizer.cleaner import Cleaner
from k_optimizer.models import Snapshot

_INTERVAL_MS = 1500
_FRAME_MS = 33
_THEME_POLL_MS = 2000
_ICON = Path(__file__).parent / "assets" / "klauncher.ico"

_START, _SWEEP = 225, 270  # speedtest-style dial: bottom-left, clockwise over the top
_W, _H = 940, 640
_CARD_W, _CARD_H, _CARD_GAP, _CARD_TOP = 280, 400, 20, 104
_DIAL_R, _DIAL_W = 100, 14
_SEGMENTS = 54


def _gb(n: int) -> str:
    return f"{n / 1024**3:.1f} GB"


def summarize(snap: Snapshot) -> dict[str, tuple[float | None, str]]:
    """Per gauge: (percent or None when unavailable, sub-label)."""
    ram = snap.ram_used_bytes / snap.ram_total_bytes * 100 if snap.ram_total_bytes else 0.0
    out = {
        "cpu": (snap.cpu_percent, f"{psutil.cpu_count()} çekirdek"),
        "ram": (ram, f"{_gb(snap.ram_used_bytes)} / {_gb(snap.ram_total_bytes)}"),
        "gpu": (None, "okunamıyor"),
    }
    if snap.adapters:
        busiest = max(snap.adapters, key=lambda a: a.utilization)
        main = max(snap.adapters, key=lambda a: a.dedicated_used_bytes or 0)
        vram = main.dedicated_used_bytes
        out["gpu"] = (busiest.utilization, f"VRAM {_gb(vram)}" if vram is not None else "VRAM -")
    return out


def round_rect_points(x0, y0, x1, y1, r):
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
            x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


class Gauge:
    """Animated dial state; drawing lives in App so every item shares one canvas."""

    def __init__(self, key: str, label: str):
        self.key, self.label = key, label
        self.sub = ""
        self.available = True
        self.target = 0.0
        self.shown = 0.0

    def set(self, pct: float | None, sub: str):
        self.available = pct is not None
        self.target = max(0.0, min(100.0, pct or 0.0))
        self.sub = sub

    def tick(self, motion: float):
        if motion <= 0 or abs(self.target - self.shown) < 0.2:
            self.shown = self.target
        else:
            self.shown += (self.target - self.shown) * min(1.0, 0.25 / motion)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("K-Optimizer")
        self.resizable(False, False)
        try:
            self.iconbitmap(str(_ICON))
        except tk.TclError:
            pass
        families = set(tkfont.families())
        self._ui_font = next((f for f in theme.UI_FONTS if f in families), "Segoe UI")
        self._display_font = next((f for f in theme.DISPLAY_FONTS if f in families), "Segoe UI")
        self.pal = theme.load()
        self._motion = theme.motion_scale()

        self.canvas = tk.Canvas(self, width=_W, height=_H, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        self._regions: list[tuple[str, tuple[float, float, float, float]]] = []
        self._hover: str | None = None

        self._known = classifier.default_known_apps()
        self._classify = cli.make_classify(self._known)
        self._cleaner = Cleaner(cli.session_path(), self._classify)
        self._throttler = throttle.Throttler(cli.session_path().with_name("throttle.json"))
        self._own = cli.own_pids()
        self._last_fg: int | None = None
        self._ramcleaner = ramclean.RamCleaner()
        self._balancer = probalance.ProBalance(self._throttler, self._classify, self._own)
        self._auto_balance = False
        self._last_tick_snap: Snapshot | None = None
        self._is_admin = self._ramcleaner._ops.is_admin()
        self._ram_busy = False
        self._ram_again = False
        self._done: queue.SimpleQueue = queue.SimpleQueue()
        self._snap: Snapshot | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._result = ""
        self._result_ok = False
        self._undo_ready = False
        self._gauges = {k: Gauge(k, k.upper()) for k in ("ram", "gpu", "cpu")}
        self._refresh_undo()
        self._apply_window_theme()

        threading.Thread(target=self._worker, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(300, self._poll)
        self.after(200, self._track_foreground)
        self.after(_THEME_POLL_MS, self._follow_theme)
        self.after(_FRAME_MS, self._frame)

    # --- theme --------------------------------------------------------------
    def _follow_theme(self):
        pal = theme.load()
        self._motion = theme.motion_scale()
        if pal != self.pal:
            self.pal = pal
            self._apply_window_theme()
        self.after(_THEME_POLL_MS, self._follow_theme)

    def _apply_window_theme(self):
        """Dark, palette-coloured title bar and rounded corners (Windows 11); fails soft elsewhere."""
        p = self.pal
        self.configure(bg=p.background)
        self.canvas.configure(bg=p.background)
        try:
            self.update_idletasks()
            dwm = ctypes.windll.dwmapi
            user32 = ctypes.windll.user32
            user32.GetParent.restype = ctypes.c_void_p
            hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()

            def colorref(c: str) -> ctypes.c_uint:
                r, g, b = theme._rgb(c)
                return ctypes.c_uint(r | g << 8 | b << 16)

            for attr, value in ((20, ctypes.c_int(1)), (33, ctypes.c_int(2)),
                                (35, colorref(p.background)), (34, colorref(p.outline)),
                                (36, colorref(theme.TEXT))):
                dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            pass

    # --- drawing ---------------------------------------------------------------
    def _font(self, size, bold=False, display=False):
        return (self._display_font if display else self._ui_font, size, "bold" if bold else "normal")

    def _frame(self):
        while True:
            try:
                parts = self._done.get_nowait()
            except queue.Empty:
                break
            self._ram_done(parts)
        for g in self._gauges.values():
            g.tick(self._motion)
        self._draw()
        self.after(_FRAME_MS, self._frame)

    def _draw(self):
        c, p = self.canvas, self.pal
        c.delete("all")
        self._regions = []
        c.create_text(32, 38, anchor="w", text="K-OPTIMIZER", fill=p.primary, font=self._font(24, True, True))
        c.create_text(32, 76, anchor="w", text="Windows'un gereksiz yükünü temizle", fill=theme.TEXT_MUTED,
                      font=self._font(10))
        total = 3 * _CARD_W + 2 * _CARD_GAP
        left = (_W - total) / 2
        for i, key in enumerate(("ram", "gpu", "cpu")):
            self._draw_card(self._gauges[key], left + i * (_CARD_W + _CARD_GAP))
        y = _CARD_TOP + _CARD_H + 24
        color = p.primary if self._result_ok else theme.TEXT_MUTED
        c.create_text(left, y, anchor="nw", text=self._result, fill=color, width=total, font=self._font(10))
        fy = _H - 30
        if not self._is_admin:
            self._link("admin", left, fy, "🛡  Yönetici olarak aç", p.primary, "w")
        self._link("undo", left + total, fy, "↶  Geri Al", p.primary if self._undo_ready else theme.TEXT_FAINT, "e")

    def _link(self, name, x, y, text, color, anchor):
        font = self._font(10, True, True)
        if self._hover == name:
            color = theme.blend(color, "#FFFFFF", 0.25)
        item = self.canvas.create_text(x, y, anchor=anchor, text=text, fill=color, font=font)
        x0, y0, x1, y1 = self.canvas.bbox(item)
        self._regions.append((name, (x0 - 6, y0 - 6, x1 + 6, y1 + 6)))

    def _draw_card(self, g: Gauge, x0: float):
        c, p = self.canvas, self.pal
        y0, x1, y1 = _CARD_TOP, x0 + _CARD_W, _CARD_TOP + _CARD_H
        c.create_polygon(round_rect_points(x0, y0, x1, y1, theme.RADIUS[3]), smooth=True,
                         fill=p.card, outline=p.outline, width=1)
        cx, cy = (x0 + x1) / 2, y0 + 150
        box = (cx - _DIAL_R, cy - _DIAL_R, cx + _DIAL_R, cy + _DIAL_R)
        c.create_arc(*box, start=_START, extent=-_SWEEP, style="arc", outline=p.control, width=_DIAL_W)
        frac = g.shown / 100 if g.available else 0.0
        step = _SWEEP / _SEGMENTS
        colors = theme.arc_colors(frac, p, _SEGMENTS)
        if frac > 0 and colors:
            c.create_arc(*box, start=_START, extent=-step * len(colors), style="arc",
                         outline=theme.accent_soft(p), width=_DIAL_W + 10)
            for i, col in enumerate(colors):
                c.create_arc(*box, start=_START - i * step, extent=-(step + 0.6), style="arc",
                             outline=col, width=_DIAL_W)
        c.create_text(cx, cy - 8, text=f"{g.shown:.0f}" if g.available else "—",
                      fill=theme.TEXT if g.available else theme.TEXT_FAINT, font=self._font(46, True, True))
        if g.available:
            c.create_text(cx, cy + 40, text="%", fill=p.secondary, font=self._font(13, True, True))
        c.create_text(cx, y0 + 282, text=g.label, fill=theme.TEXT, font=self._font(15, True, True))
        c.create_text(cx, y0 + 304, text=g.sub, fill=theme.TEXT_MUTED, font=self._font(10))
        self._draw_button(g.key, cx, y1 - 36, active=g.key == "cpu" and self._auto_balance)

    def _draw_button(self, key: str, cx: float, cy: float, active: bool = False):
        c, p = self.canvas, self.pal
        r = 26
        hover = self._hover == key
        fill = theme.blend(p.background, p.primary, 0.45 if active else 0.30 if hover else 0.14)
        if active:  # toggle is on: soft halo in the secondary colour
            c.create_oval(cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6, outline=p.secondary, width=2)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=p.primary, width=2)
        ox, oy = cx - 32, cy - 32  # broom drawn in a 64x64 box
        c.create_line(ox + 44, oy + 14, ox + 31, oy + 33, fill=theme.TEXT, width=4, capstyle="round")
        c.create_polygon(ox + 21, oy + 32, ox + 35, oy + 30, ox + 42, oy + 36, ox + 36, oy + 52,
                         ox + 16, oy + 50, fill=p.primary, outline=p.primary)
        for a, b in ((24, 21), (29, 27), (34, 33)):
            c.create_line(ox + a, oy + 38, ox + b, oy + 49, fill=p.background, width=2)
        self._regions.append((key, (cx - r, cy - r, cx + r, cy + r)))

    def _hit(self, x, y) -> str | None:
        for name, (x0, y0, x1, y1) in self._regions:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return None

    def _set_hover(self, name):
        self._hover = name
        self.canvas.configure(cursor="hand2" if name else "")

    def _on_motion(self, e):
        self._set_hover(self._hit(e.x, e.y))

    def _on_click(self, e):
        if os.environ.get("K_OPTIMIZER_PREVIEW"):
            return  # preview mode (screenshots/demos): look but never act on the user's system
        name = self._hit(e.x, e.y)
        if name in ("ram", "gpu", "cpu"):
            self._clean(name)
        elif name == "undo":
            self._restore()
        elif name == "admin":
            self._relaunch_as_admin()

    # --- data -------------------------------------------------------------
    def _worker(self):
        while not self._stop.is_set():
            try:
                snap = monitor.snapshot_after(0.5)
            except Exception:  # keep the dials alive if one sample fails
                snap = None
            if snap is not None:
                with self._lock:
                    self._snap = snap
            self._stop.wait(_INTERVAL_MS / 1000)

    def _poll(self):
        with self._lock:
            snap = self._snap
        if snap is not None:
            for key, (pct, sub) in summarize(snap).items():
                if key == "cpu" and self._auto_balance:
                    held = len(self._throttler.pending_pids("cpu"))
                    sub += f" · oto denge açık" + (f" · {held} yavaşlatıldı" if held else "")
                self._gauges[key].set(pct, sub)
            if self._auto_balance and snap is not self._last_tick_snap:
                self._last_tick_snap = snap
                self._balance(snap)
        self.after(_INTERVAL_MS, self._poll)

    def _foreground_group(self) -> frozenset[int]:
        return throttle.related_pids(self._last_fg) if self._last_fg else frozenset()

    def _balance(self, snap: Snapshot):
        report = self._balancer.tick(time.monotonic(), snap, self._foreground_group())
        if report.restrained:
            names = ", ".join(sorted({p.name for p in report.restrained}))
            self._result, self._result_ok = f"Otomatik denge: {names} arka planda yavaşlatıldı", True
        elif report.released:
            self._result, self._result_ok = "Otomatik denge: öncelikler eski haline getirildi", False
        if report.restrained or report.released:
            self._refresh_undo()

    def _track_foreground(self):
        # Remember the last app the user was in that is not us, so a game they alt-tabbed from stays untouched.
        fg = throttle.foreground_pid()
        if fg and fg not in self._own:
            self._last_fg = fg
        self.after(400, self._track_foreground)

    # --- actions ------------------------------------------------------------
    def _clean(self, resource: str):
        if resource == "ram":
            return self._clean_ram()
        if resource == "cpu":
            return self._toggle_auto_balance()
        with self._lock:
            snap = self._snap
        if snap is None:
            return
        self._show(self._close_safe(snap, resource) + self._throttle(snap, resource))

    def _toggle_auto_balance(self):
        if self._auto_balance:
            self._auto_balance = False
            n = self._balancer.release_all()
            self._show([f"Otomatik CPU dengeleme kapatıldı · {n} sürecin önceliği eski haline getirildi"])
            self._result_ok = False
            return
        self._auto_balance = True
        with self._lock:
            snap = self._snap
        parts = self._close_safe(snap, "cpu") if snap is not None else []
        parts.insert(0, "Otomatik CPU dengeleme açıldı: sistem yüklenince arka planda CPU yiyenler yavaşlatılır, "
                        "ön plandaki uygulamaya dokunulmaz")
        self._show(parts)

    def _close_safe(self, snap: Snapshot, resource: str) -> list[str]:
        parts = []
        targets = classifier.safe_targets(
            snap.processes, self._known, cli.own_pids(), resource, winutil.visible_window_pids()
        )
        if targets:
            r = self._cleaner.close(targets)
            if r.closed:
                names = ", ".join(sorted({p.name for p in r.closed}))
                parts.append(f"Windows bileşeni kapatıldı: {names}")
            if any(why == "yetki gerekir" for _, why in r.skipped):
                parts.append("bazıları için yönetici yetkisi gerekir")
        return parts

    def _show(self, parts: list[str]):
        self._result_ok = bool(parts)
        self._result = " · ".join(parts) if parts else "Düşürülecek veya kapatılacak gereksiz yük yok."
        self._refresh_undo()

    # RAM cleaning runs off the UI thread so the button never freezes or needs a cooldown.
    # Clicks while a run is in flight are not dropped: one more run is queued right after it.
    def _clean_ram(self):
        if self._ram_busy:
            self._ram_again = True
            return
        with self._lock:
            snap = self._snap
        if snap is None:
            return
        self._ram_busy = True
        threading.Thread(target=self._ram_job, args=(snap,), daemon=True).start()

    def _ram_job(self, snap: Snapshot):
        try:
            parts = self._close_safe(snap, "ram")
            exclude = throttle.related_pids(self._last_fg) if self._last_fg else frozenset()
            report = self._ramcleaner.clean(ramclean.cold_pids(snap.processes, exclude, self._own))
            parts.insert(0, report.summary())
        except Exception as e:  # never let a failed step kill the worker silently
            parts = [f"RAM temizliği hata verdi: {e}"]
        self._done.put(parts)

    def _ram_done(self, parts: list[str]):
        self._ram_busy = False
        self._show(parts)
        if self._ram_again:
            self._ram_again = False
            self._clean_ram()

    def _throttle(self, snap: Snapshot, kind: str) -> list[str]:
        exclude = throttle.related_pids(self._last_fg) if self._last_fg else frozenset()
        picked = throttle.pick_background(snap.processes, self._classify, self._own, exclude, kind)
        if not picked:
            return []
        r = self._throttler.apply(picked, kind)
        if not r.applied:
            return []
        names = ", ".join(sorted({p.name for p in r.applied}))
        what = "CPU önceliği" if kind == "cpu" else "GPU önceliği"
        return [f"Arka plan {what} düşürüldü: {names}"]

    def _restore(self):
        if not self._cleaner.pending() and not self._throttler.pending():
            return
        self._auto_balance = False
        r = self._cleaner.restore()
        n = self._throttler.restore()
        text = f"Geri açıldı: {', '.join(r.started) or '-'}"
        if n:
            text += f" · {n} sürecin önceliği eski haline getirildi"
        if r.failed:
            text += " · açılamadı: " + ", ".join(name for name, _ in r.failed)
        self._result, self._result_ok = text, False
        self._refresh_undo()

    def _relaunch_as_admin(self):
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, ""
        else:
            exe, params = sys.executable, "-m k_optimizer"
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32:
            self._close()  # the elevated copy takes over; declining the UAC prompt keeps this one open

    def _refresh_undo(self):
        self._undo_ready = bool(self._cleaner.pending() or self._throttler.pending())

    def _close(self):
        self._stop.set()
        self._balancer.release_all()  # never leave processes slowed down after we exit
        self.destroy()


def run() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp rendering on scaled displays
    except (AttributeError, OSError):
        pass
    App().mainloop()
