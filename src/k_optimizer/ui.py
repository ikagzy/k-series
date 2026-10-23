import threading
import time
import tkinter as tk
from pathlib import Path

import psutil

from k_optimizer import classifier, cli, monitor, throttle, trimmer, winutil
from k_optimizer.cleaner import Cleaner
from k_optimizer.models import Snapshot

# K-Launcher default theme (App.xaml)
BG = "#101014"
PANEL = "#14141A"
PANEL_EDGE = "#143822"
NEON = "#00FF66"
NEON_HOVER = "#183C2A"
TEXT = "#F1F1F1"
MUTED = "#7F858C"
TRACK = "#1B1B24"
WARN = "#FFB020"
HOT = "#FF4D4D"

_INTERVAL_MS = 1500
_FRAME_MS = 33
_ICON = Path(__file__).parent / "assets" / "klauncher.ico"
_FONT = "Segoe UI"

_START, _SWEEP = 225, 270  # speedtest-style dial: bottom-left, clockwise over the top


def gauge_color(pct: float) -> str:
    return HOT if pct >= 90 else WARN if pct >= 70 else NEON


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


class Gauge(tk.Frame):
    """Dial with a centre readout and a round broom button underneath."""

    SIZE = 250

    def __init__(self, master, label: str, on_clean):
        super().__init__(master, bg=PANEL, highlightbackground=PANEL_EDGE, highlightthickness=1)
        self._target = 0.0
        self._shown = 0.0
        self._available = True
        s = self.SIZE
        self.dial = tk.Canvas(self, width=s, height=s - 20, bg=PANEL, highlightthickness=0)
        self.dial.pack(padx=18, pady=(14, 0))
        self._label = label
        self.sub = tk.Label(self, text="", bg=PANEL, fg=MUTED, font=(_FONT, 10))
        self.sub.pack(pady=(0, 8))
        self.button = tk.Canvas(self, width=64, height=64, bg=PANEL, highlightthickness=0, cursor="hand2")
        self.button.pack(pady=(0, 16))
        self._draw_button(False)
        self.button.bind("<Enter>", lambda e: self._draw_button(True))
        self.button.bind("<Leave>", lambda e: self._draw_button(False))
        self.button.bind("<Button-1>", lambda e: on_clean())
        self._draw_dial()

    def set(self, pct: float | None, sub: str):
        self._available = pct is not None
        self._target = max(0.0, min(100.0, pct or 0.0))
        self.sub.configure(text=sub)

    def tick(self):
        step = (self._target - self._shown) * 0.25
        if abs(step) > 0.05 or not self._available:
            self._shown = self._target if abs(self._target - self._shown) < 0.2 else self._shown + step
        self._draw_dial()

    def _draw_dial(self):
        c, s = self.dial, self.SIZE
        c.delete("all")
        pad, w = 22, 14
        box = (pad, pad, s - pad, s - pad)
        cx, cy = s / 2, s / 2
        c.create_arc(*box, start=_START, extent=-_SWEEP, style="arc", outline=TRACK, width=w)
        frac = self._shown / 100
        if self._available and frac > 0:
            color = gauge_color(self._shown)
            c.create_arc(*box, start=_START, extent=-_SWEEP * frac, style="arc",
                         outline=PANEL_EDGE, width=w + 10)
            c.create_arc(*box, start=_START, extent=-_SWEEP * frac, style="arc",
                         outline=color, width=w)
        else:
            color = MUTED
        value = f"{self._shown:.0f}" if self._available else "—"
        c.create_text(cx, cy - 6, text=value, fill=TEXT if self._available else MUTED,
                      font=(_FONT, 46, "bold"))
        if self._available:
            c.create_text(cx, cy + 44, text="%", fill=color, font=(_FONT, 13, "bold"))
        c.create_text(cx, s - 40, text=self._label, fill=NEON, font=(_FONT, 15, "bold"))

    def _draw_button(self, hover: bool):
        c = self.button
        c.delete("all")
        c.create_oval(3, 3, 61, 61, fill=NEON_HOVER if hover else PANEL, outline=NEON, width=2)
        # broom: diagonal handle, bristle head, bristle strokes
        c.create_line(44, 14, 31, 33, fill=TEXT, width=4, capstyle="round")
        c.create_polygon(21, 32, 35, 30, 42, 36, 36, 52, 16, 50, fill=NEON, outline=NEON)
        for x0, x1 in ((24, 21), (29, 27), (34, 33)):
            c.create_line(x0, 38, x1, 49, fill=BG, width=2)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("K-Optimizer")
        self.configure(bg=BG)
        self.resizable(False, False)
        try:
            self.iconbitmap(str(_ICON))
        except tk.TclError:
            pass
        self._known = classifier.default_known_apps()
        self._classify = cli.make_classify(self._known)
        self._cleaner = Cleaner(cli.session_path(), self._classify)
        self._throttler = throttle.Throttler(cli.session_path().with_name("throttle.json"))
        self._own = cli.own_pids()
        self._last_fg: int | None = None
        self._snap: Snapshot | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

        tk.Label(self, text="K-OPTIMIZER", bg=BG, fg=NEON, font=(_FONT, 20, "bold")).pack(pady=(18, 2))
        tk.Label(self, text="Windows'un gereksiz yükünü temizle", bg=BG, fg=MUTED, font=(_FONT, 10)).pack()

        row = tk.Frame(self, bg=BG)
        row.pack(padx=20, pady=18)
        self._gauges: dict[str, Gauge] = {}
        for key, label in (("ram", "RAM"), ("gpu", "GPU"), ("cpu", "CPU")):
            g = Gauge(row, label, lambda k=key: self._clean(k))
            g.pack(side="left", padx=10)
            self._gauges[key] = g

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=24, pady=(0, 16))
        self._result = tk.Label(foot, text="", bg=BG, fg=MUTED, font=(_FONT, 10), anchor="w", justify="left")
        self._result.pack(side="left", fill="x", expand=True)
        self._undo = tk.Label(foot, text="↶ Geri Al", bg=BG, fg=MUTED, font=(_FONT, 10, "bold"), cursor="hand2")
        self._undo.pack(side="right")
        self._undo.bind("<Button-1>", lambda e: self._restore())
        self._refresh_undo()

        threading.Thread(target=self._worker, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(300, self._poll)
        self.after(200, self._track_foreground)
        self.after(_FRAME_MS, self._frame)

    def _worker(self):
        while not self._stop.is_set():
            try:
                snap = monitor.snapshot_after(0.5)
            except Exception:  # keep the dial alive if one sample fails
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
                self._gauges[key].set(pct, sub)
        self.after(_INTERVAL_MS, self._poll)

    def _track_foreground(self):
        # Remember the last app the user was in that is not us, so a game they alt-tabbed from stays untouched.
        fg = throttle.foreground_pid()
        if fg and fg not in self._own:
            self._last_fg = fg
        self.after(400, self._track_foreground)

    def _frame(self):
        for g in self._gauges.values():
            g.tick()
        self.after(_FRAME_MS, self._frame)

    def _clean(self, resource: str):
        with self._lock:
            snap = self._snap
        if snap is None:
            return
        before = psutil.virtual_memory().available
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
        if resource in ("cpu", "gpu"):
            parts += self._throttle(snap, resource)
        if resource == "ram":
            trimmed = trimmer.trim_all(p.pid for p in snap.processes)
            time.sleep(0.4)
            freed = max(0, psutil.virtual_memory().available - before)
            parts.insert(0, f"~{freed / 1024**2:.0f} MB RAM boşaltıldı ({trimmed} sürecin belleği sıkıştırıldı)")
        if not parts:
            parts = ["Düşürülecek veya kapatılacak gereksiz yük yok."]
            ok = False
        else:
            ok = True
        self._result.configure(text=" · ".join(parts), fg=NEON if ok else MUTED)
        self._refresh_undo()

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
        r = self._cleaner.restore()
        n = self._throttler.restore()
        text = f"Geri açıldı: {', '.join(r.started) or '-'}"
        if n:
            text += f" · {n} sürecin önceliği eski haline getirildi"
        if r.failed:
            text += " · açılamadı: " + ", ".join(n for n, _ in r.failed)
        self._result.configure(text=text, fg=TEXT)
        self._refresh_undo()

    def _refresh_undo(self):
        self._undo.configure(fg=NEON if self._cleaner.pending() or self._throttler.pending() else MUTED)

    def _close(self):
        self._stop.set()
        self.destroy()


def run() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp rendering on scaled displays
    except (AttributeError, OSError):
        pass
    App().mainloop()
