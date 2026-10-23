import ctypes
import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

import psutil

from k_optimizer import (autoram, classifier, cli, icons, monitor, optsettings, probalance, ramclean, theme,
                         throttle, trimmer, winutil)
from k_optimizer.chrome import apply_window_theme, round_rect_points  # noqa: F401  (re-exported)
from k_optimizer.cleaner import Cleaner
from k_optimizer.models import Snapshot

_INTERVAL_MS = 1500
_FRAME_MS = 40
_THEME_POLL_MS = 2000

_START, _SWEEP = 225, 270  # speedtest-style dial: bottom-left, clockwise over the top
_W, _H = 940, 640
_CARD_W, _CARD_H, _CARD_GAP, _CARD_TOP = 280, 400, 20, 104
_DIAL_R, _DIAL_W = 100, 14
_SEGMENTS = 36


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
        if motion <= 0 or abs(self.target - self.shown) < 1.0:  # jitter snaps; only real changes sweep
            self.shown = self.target
        else:
            self.shown += (self.target - self.shown) * min(1.0, 0.25 / motion)


class OptimizerPanel(tk.Frame):
    """The RAM / GPU / CPU gauges. A plain Frame, so it can be the whole app or one page of K-Series."""

    def __init__(self, master, pal_getter, motion_getter, show_header: bool = True,
                 width: int = _W, height: int = _H, relaunch_args: str = "-m k_optimizer"):
        super().__init__(master, bd=0, highlightthickness=0)
        self._relaunch_args = relaunch_args
        self._pal_getter, self._motion_getter, self._show_header = pal_getter, motion_getter, show_header
        families = set(tkfont.families())
        self._ui_font = next((f for f in theme.UI_FONTS if f in families), "Segoe UI")
        self._display_font = next((f for f in theme.DISPLAY_FONTS if f in families), "Segoe UI")

        self.canvas = tk.Canvas(self, width=width, height=height, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
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
        saved = optsettings.load()
        self._auto_ram = saved["auto_ram"]
        self._autoram = autoram.AutoRam(interval=saved["auto_ram_interval"])
        self._last_auto_snap: Snapshot | None = None
        self._ram_busy = False
        self._visible = True  # False while minimised: nothing to show, so nothing to measure
        self._tick = 0
        self._last_sig = None
        self._last_trim = time.monotonic() - 18  # first trim about 2 s after start, then every 20 s
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

        threading.Thread(target=self._worker, daemon=True).start()
        self.after(300, self._poll)
        self.after(200, self._track_foreground)
        self.after(_FRAME_MS, self._frame)

    @property
    def pal(self) -> theme.Palette:
        return self._pal_getter()

    # --- drawing ---------------------------------------------------------------
    def _font(self, size, bold=False, display=False):
        return (self._display_font if display else self._ui_font, size, "bold" if bold else "normal")

    def _is_shown(self) -> bool:
        return bool(self.winfo_ismapped())  # a page nobody is looking at is not painted

    def _check_visible(self) -> bool:
        """False while the window is minimised or hidden (Tk unmaps it): then nothing needs measuring or painting."""
        try:
            return self._is_shown()
        except Exception:
            return True

    def _signature(self):
        """Everything that changes what the panel shows. Equal signature, equal picture."""
        gauges = tuple((round(g.shown), g.available, g.sub) for g in self._gauges.values())  # whole points: finer is invisible
        return (gauges, self._result, self._result_ok, self._undo_ready, self._hover, self._auto_balance,
                self._auto_ram, self._autoram.interval, self._ram_busy, self.pal.id,
                self.canvas.winfo_width(), self.canvas.winfo_height())

    def _maybe_trim(self, now: float):
        """Hand idle memory back to Windows now and then, the way K-Launcher keeps itself at a few MB."""
        if now - self._last_trim >= 20:
            self._last_trim = now
            trimmer.empty_working_set(os.getpid())

    def _frame(self):
        try:
            while True:
                try:
                    parts, freed, auto = self._done.get_nowait()
                except queue.Empty:
                    break
                self._ram_done(parts, freed, auto)
            for g in self._gauges.values():
                g.tick(self._motion_getter())
            self._tick += 1
            if self._tick % 10 == 0:
                self._visible = self._check_visible()
            if self._is_shown():
                sig = self._signature()
                if sig != self._last_sig:  # repainting an unchanged window is pure waste
                    self._last_sig = sig
                    self._draw()
            self._maybe_trim(time.monotonic())
        except Exception:  # one bad frame must never freeze the window for good
            traceback.print_exc()
        finally:
            self.after(_FRAME_MS, self._frame)

    def _layout(self) -> dict:
        w = max(self.canvas.winfo_width(), 420)
        h = max(self.canvas.winfo_height(), 320)
        top, gap = (104 if self._show_header else 24), 20
        card_w = min(280.0, (w - 2 * 32 - 2 * gap) / 3)
        card_h = min(400.0, h - top - 96)
        total = 3 * card_w + 2 * gap
        return {"w": w, "h": h, "top": top, "gap": gap, "card_w": card_w, "card_h": card_h,
                "total": total, "left": (w - total) / 2, "s": max(0.5, min(card_w / 280, card_h / 400))}

    def _draw(self):
        c, p = self.canvas, self.pal
        c.configure(bg=p.background)
        self.configure(bg=p.background)
        c.delete("all")
        self._regions = []
        lay = self._layout()
        if self._show_header:
            c.create_text(32, 38, anchor="w", text="K-OPTIMIZER", fill=p.primary, font=self._font(24, True, True))
            c.create_text(32, 76, anchor="w", text="Windows'un gereksiz yükünü temizle", fill=theme.TEXT_MUTED,
                          font=self._font(10))
        for i, key in enumerate(("ram", "gpu", "cpu")):
            self._draw_card(self._gauges[key], lay["left"] + i * (lay["card_w"] + lay["gap"]), lay)
        y = lay["top"] + lay["card_h"] + 20
        color = p.primary if self._result_ok else theme.TEXT_MUTED
        c.create_text(lay["left"], y, anchor="nw", text=self._result, fill=color, width=lay["total"],
                      font=self._font(10))
        fy = lay["h"] - 26
        if not self._is_admin:
            self._link("admin", lay["left"], fy, "🛡  Yönetici olarak aç", p.primary, "w")
        self._link("undo", lay["left"] + lay["total"], fy, "↶  Geri Al",
                   p.primary if self._undo_ready else theme.TEXT_FAINT, "e")

    def _tiny(self, name, x, y, text, color, anchor):
        if self._hover == name:
            color = theme.blend(color, "#FFFFFF", 0.25)
        item = self.canvas.create_text(x, y, anchor=anchor, text=text, fill=color, font=self._font(9, True, True))
        x0, y0, x1, y1 = self.canvas.bbox(item)
        self._regions.append((name, (x0 - 4, y0 - 4, x1 + 4, y1 + 4)))

    def _link(self, name, x, y, text, color, anchor):
        font = self._font(10, True, True)
        if self._hover == name:
            color = theme.blend(color, "#FFFFFF", 0.25)
        item = self.canvas.create_text(x, y, anchor=anchor, text=text, fill=color, font=font)
        x0, y0, x1, y1 = self.canvas.bbox(item)
        self._regions.append((name, (x0 - 6, y0 - 6, x1 + 6, y1 + 6)))

    def _draw_card(self, g: Gauge, x0: float, lay: dict):
        c, p, sc = self.canvas, self.pal, lay["s"]
        y0, x1, y1 = lay["top"], x0 + lay["card_w"], lay["top"] + lay["card_h"]
        c.create_polygon(round_rect_points(x0, y0, x1, y1, theme.RADIUS[3]), smooth=True,
                         fill=p.card, outline=p.outline, width=1)
        r, dial_w = _DIAL_R * sc, max(8, round(_DIAL_W * sc))
        cx, cy = (x0 + x1) / 2, y0 + 150 * sc
        box = (cx - r, cy - r, cx + r, cy + r)
        c.create_arc(*box, start=_START, extent=-_SWEEP, style="arc", outline=p.control, width=dial_w)
        frac = g.shown / 100 if g.available else 0.0
        step = _SWEEP / _SEGMENTS
        colors = theme.arc_colors(frac, p, _SEGMENTS)
        if frac > 0 and colors:
            c.create_arc(*box, start=_START, extent=-step * len(colors), style="arc",
                         outline=theme.accent_soft(p), width=dial_w + 10)
            for i, col in enumerate(colors):
                c.create_arc(*box, start=_START - i * step, extent=-(step + 0.6), style="arc",
                             outline=col, width=dial_w)
        c.create_text(cx, cy - 8 * sc, text=f"{g.shown:.0f}" if g.available else "—",
                      fill=theme.TEXT if g.available else theme.TEXT_FAINT,
                      font=self._font(round(46 * sc), True, True))
        if g.available:
            c.create_text(cx, cy + 40 * sc, text="%", fill=p.secondary, font=self._font(13, True, True))
        c.create_text(cx, y0 + 282 * sc, text=g.label, fill=theme.TEXT, font=self._font(15, True, True))
        c.create_text(cx, y0 + 304 * sc, text=g.sub, fill=theme.TEXT_MUTED, font=self._font(10))
        if g.key == "ram":
            on = self._auto_ram
            self._tiny("auto-ram", cx - 8, y0 + 326 * sc, ("● " if on else "○ ") + "Otomatik",
                       p.primary if on else theme.TEXT_MUTED, "e")
            self._tiny("auto-int", cx + 8, y0 + 326 * sc, f"her {self._autoram.interval} sn",
                       p.secondary if on else theme.TEXT_FAINT, "w")
        self._draw_button(g.key, cx, y1 - 36 * sc, sc, active=g.key == "cpu" and self._auto_balance)

    def _draw_button(self, key: str, cx: float, cy: float, sc: float = 1.0, active: bool = False):
        c, p = self.canvas, self.pal
        r = 26 * sc
        hover = self._hover == key
        fill = theme.blend(p.background, p.primary, 0.45 if active else 0.30 if hover else 0.14)
        if active:  # toggle is on: soft halo in the secondary colour
            c.create_oval(cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6, outline=p.secondary, width=2)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=p.primary, width=2)
        ox, oy = cx - 32 * sc, cy - 32 * sc  # broom drawn in a 64x64 box
        k = lambda v: v * sc
        c.create_line(ox + k(44), oy + k(14), ox + k(31), oy + k(33), fill=theme.TEXT, width=4, capstyle="round")
        c.create_polygon(ox + k(21), oy + k(32), ox + k(35), oy + k(30), ox + k(42), oy + k(36), ox + k(36),
                         oy + k(52), ox + k(16), oy + k(50), fill=p.primary, outline=p.primary)
        for a, b in ((24, 21), (29, 27), (34, 33)):
            c.create_line(ox + k(a), oy + k(38), ox + k(b), oy + k(49), fill=p.background, width=2)
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
        elif name == "auto-ram":
            self._toggle_auto_ram()
        elif name == "auto-int":
            self._cycle_interval()
        elif name == "undo":
            self._restore()
        elif name == "admin":
            self._relaunch_as_admin()

    # --- data -------------------------------------------------------------
    def _worker(self):
        while not self._stop.is_set():
            snap = None
            if self._visible or self._auto_ram or self._auto_balance:
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
            if self._auto_ram and snap is not self._last_auto_snap:
                self._last_auto_snap = snap  # only act on a live reading, never on a stale one
                if not self._ram_busy and self._autoram.due(time.monotonic()):
                    self._clean_ram(auto=True)
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
    def _clean_ram(self, auto: bool = False):
        if auto and os.environ.get("K_OPTIMIZER_PREVIEW"):
            return  # preview mode is look-only: nothing happens on its own either
        if self._ram_busy:
            if not auto:
                self._ram_again = True
            return
        with self._lock:
            snap = self._snap
        if snap is None:
            return
        self._ram_busy = True
        threading.Thread(target=self._ram_job, args=(snap, auto), daemon=True).start()

    def _ram_job(self, snap: Snapshot, auto: bool = False):
        freed = 0
        try:
            # automatic runs only trim memory; closing Windows components is always the user's own click
            parts = [] if auto else self._close_safe(snap, "ram")
            exclude = throttle.related_pids(self._last_fg) if self._last_fg else frozenset()
            report = self._ramcleaner.clean(ramclean.cold_pids(snap.processes, exclude, self._own))
            freed = report.freed_bytes
            parts.insert(0, ("Otomatik RAM temizliği: " if auto else "") + report.summary())
        except Exception as e:  # never let a failed step kill the worker silently
            parts = [f"RAM temizliği hata verdi: {e}"]
        self._done.put((parts, freed, auto))

    def _ram_done(self, parts: list[str], freed: int = 0, auto: bool = False):
        self._ram_busy = False
        self._autoram.record(time.monotonic())  # manual cleans restart the automatic interval too
        if not (auto and freed < 64 * 1024 * 1024):  # a quiet no-op must not overwrite the user's last message
            self._show(parts)
        if self._ram_again:
            self._ram_again = False
            self._clean_ram()

    def _save_auto_ram(self) -> bool:
        return optsettings.save({"auto_ram": self._auto_ram, "auto_ram_interval": self._autoram.interval})

    def _toggle_auto_ram(self):
        self._auto_ram = not self._auto_ram
        ok = self._save_auto_ram()
        if self._auto_ram:
            text = (f"Otomatik RAM temizliği açık: her {self._autoram.interval} saniyede bir boştaki arka plan "
                    "süreçlerinin belleği sıkıştırılır (hiçbir şey kapatılmaz).")
        else:
            text = "Otomatik RAM temizliği kapatıldı."
        self._result, self._result_ok = text + ("" if ok else " (ayar kaydedilemedi)"), self._auto_ram

    def _cycle_interval(self):
        self._autoram.interval = optsettings.next_interval(self._autoram.interval)
        ok = self._save_auto_ram()
        self._result = (f"Otomatik temizleme aralığı: her {self._autoram.interval} saniye" +
                        ("" if ok else " (ayar kaydedilemedi)"))
        self._result_ok = False

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
            exe, params = sys.executable, self._relaunch_args
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32:
            self.winfo_toplevel().event_generate("<<KSeriesQuit>>")  # the elevated copy takes over

    def _refresh_undo(self):
        self._undo_ready = bool(self._cleaner.pending() or self._throttler.pending())

    def shutdown(self):
        self._stop.set()
        self._balancer.release_all()  # never leave processes slowed down after we exit


class App(tk.Tk):
    """Standalone K-Optimizer window: the panel plus theme following and the window chrome."""

    def __init__(self):
        super().__init__()
        self.title("K-Optimizer")
        self.resizable(False, False)
        self.pal = theme.load()
        icons.apply_window_icon(self, self.pal)  # K-Launcher's own theme icon
        self.motion = theme.motion_scale()
        self.panel = OptimizerPanel(self, lambda: self.pal, lambda: self.motion)
        self.panel.pack(fill="both", expand=True)
        apply_window_theme(self, self.pal)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<<KSeriesQuit>>", lambda e: self._close())
        self.after(_THEME_POLL_MS, self._follow_theme)

    def _follow_theme(self):
        pal = theme.load()
        self.motion = theme.motion_scale()
        if pal != self.pal:
            self.pal = pal
            apply_window_theme(self, pal)
            icons.apply_window_icon(self, pal)
        self.after(_THEME_POLL_MS, self._follow_theme)

    def _close(self):
        self.panel.shutdown()
        self.destroy()


def run() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp rendering on scaled displays
    except (AttributeError, OSError):
        pass
    App().mainloop()
