import threading
from tkinter import ttk

import customtkinter as ctk

from k_optimizer import classifier, cli, monitor
from k_optimizer.cleaner import Cleaner
from k_optimizer.models import Level, ProcInfo, Snapshot

_INTERVAL_MS = 2000


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.0f} MB"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("K-Optimizer")
        self.geometry("900x620")
        self._known = classifier.default_known_apps()
        self._classify = cli.make_classify(self._known)
        self._cleaner = Cleaner(cli.session_path(), self._classify)
        self._snap: Snapshot | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._status = ctk.StringVar(value="Ölçülüyor…")

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self._build_live(tabs.add("Canlı Yük"))
        self._build_boost(tabs.add("Rahatlat"))
        ctk.CTkLabel(self, textvariable=self._status, anchor="w").pack(fill="x", padx=12, pady=6)

        threading.Thread(target=self._worker, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(500, self._poll)
        self._refresh_undo()

    # --- tabs -----------------------------------------------------------
    def _build_live(self, tab):
        self._totals = ctk.CTkLabel(tab, text="", anchor="w", justify="left")
        self._totals.pack(fill="x", pady=(4, 8))
        cols = ("ad", "cpu", "ram", "gpu", "vram", "seviye")
        self._tree = ttk.Treeview(tab, columns=cols, show="headings", height=18)
        for c, w in zip(cols, (260, 70, 90, 70, 90, 90)):
            self._tree.heading(c, text=c.upper())
            self._tree.column(c, width=w, anchor="w" if c == "ad" else "e")
        self._tree.pack(fill="both", expand=True)

    def _build_boost(self, tab):
        ctk.CTkLabel(
            tab,
            text="Bilinen gereksiz arka plan uygulamalarını tek tuşla kapatır.\nSistem ve bilinmeyen süreçlere dokunmaz.",
            justify="center",
        ).pack(pady=(40, 20))
        self._boost = ctk.CTkButton(
            tab, text="RAHATLAT", width=260, height=90,
            font=ctk.CTkFont(size=26, weight="bold"), command=self._do_boost,
        )
        self._boost.pack(pady=10)
        self._result = ctk.CTkLabel(tab, text="", justify="center")
        self._result.pack(pady=16)
        self._undo = ctk.CTkButton(tab, text="Geri Al", width=120, command=self._do_restore)
        self._undo.pack()

    # --- data -----------------------------------------------------------
    def _worker(self):
        while not self._stop.is_set():
            snap = monitor.snapshot_after(0.5)
            with self._lock:
                self._snap = snap
            self._stop.wait(_INTERVAL_MS / 1000)

    def _poll(self):
        with self._lock:
            snap = self._snap
        if snap is not None:
            self._render(snap)
        self.after(_INTERVAL_MS, self._poll)

    def _visible(self, snap: Snapshot) -> list[tuple[ProcInfo, Level]]:
        rows = [(p, self._classify(p)) for p in snap.processes]
        rows = [(p, lv) for p, lv in rows if lv is not Level.PROTECTED]
        return sorted(rows, key=lambda t: t[0].rss_bytes, reverse=True)

    def _render(self, snap: Snapshot):
        lines = [
            f"CPU {snap.cpu_percent:.0f}%    RAM {_mb(snap.ram_used_bytes)} / {_mb(snap.ram_total_bytes)}"
        ]
        for i, a in enumerate(snap.adapters, 1):
            vram = "-" if a.dedicated_used_bytes is None else _mb(a.dedicated_used_bytes)
            lines.append(f"GPU {i}: {a.utilization:.0f}%    VRAM {vram}")
        self._totals.configure(text="\n".join(lines))
        self._tree.delete(*self._tree.get_children())
        for p, lv in self._visible(snap)[:200]:
            gpu = "-" if p.gpu_percent is None else f"{p.gpu_percent:.0f}%"
            vram = "-" if p.vram_bytes is None else _mb(p.vram_bytes)
            self._tree.insert("", "end", values=(p.name, f"{p.cpu_percent:.1f}%", _mb(p.rss_bytes), gpu, vram, lv.value))
        self._status.set("GPU okunamıyor" if not snap.adapters else "Hazır")

    def _do_boost(self):
        with self._lock:
            snap = self._snap
        if snap is None:
            return
        targets = classifier.safe_targets(snap.processes, self._known, cli.own_pids())
        if not targets:
            self._result.configure(text="Kapatılacak gereksiz uygulama yok.")
            return
        r = self._cleaner.close(targets)
        freed = sum(p.rss_bytes for p in r.closed)
        text = f"{len(r.closed)} süreç kapatıldı, ~{_mb(freed)} RAM boşaldı."
        if any(why == "yetki gerekir" for _, why in r.skipped):
            text += "\nBazıları için yönetici yetkisi gerekir."
        self._result.configure(text=text)
        self._refresh_undo()

    def _do_restore(self):
        r = self._cleaner.restore()
        msg = f"Geri açılan: {', '.join(r.started) or '-'}"
        if r.failed:
            msg += "\nAçılamadı:\n" + "\n".join(f"{n}: {e}" for n, e in r.failed)
        self._result.configure(text=msg)
        self._refresh_undo()

    def _refresh_undo(self):
        self._undo.configure(state="normal" if self._cleaner.pending() else "disabled")

    def _close(self):
        self._stop.set()
        self.destroy()


def run() -> None:
    ctk.set_appearance_mode("system")
    App().mainloop()
