"""K-Series: one hub window for the K apps, in the SteelSeries GG mould.

Left sidebar, a home page of detected products, K-Optimizer built in as a page, K-Launcher detected and
launched from here, and settings (theme, motion) shared with K-Launcher through its own settings folder.
"""
import os
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from k_optimizer import theme
from k_optimizer.ui import OptimizerPanel, apply_window_theme, round_rect_points
from k_series import __version__, products, settings, updater

_W, _H = 1120, 720
_SIDEBAR = 232
_FRAME_MS = 33
_THEME_POLL_MS = 2000
_ICON = Path(__file__).resolve().parent.parent / "k_optimizer" / "assets" / "klauncher.ico"
_ITCH = "https://itzkagzy.itch.io/k-launcher"
_NAV = (("home", "Ana Sayfa"), ("optimizer", "K-Optimizer"), ("launcher", "K-Launcher"), ("settings", "Ayarlar"))
_UPDATE_NAMES = {"k-launcher": "K-Launcher", "k-series": "K-Series (K-Optimizer dahil)"}
_CARD_UPDATE = {"k-launcher": "k-launcher", "k-optimizer": "k-series"}  # card id -> update stream
_MOTIONS = (("fast", "Hızlı"), ("normal", "Normal"), ("slow", "Yavaş"), ("off", "Kapalı"))


class KSeriesApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("K-Series")
        self.resizable(False, False)
        self.geometry(f"{_W}x{_H}")
        try:
            self.iconbitmap(str(_ICON))
        except tk.TclError:
            pass
        families = set(tkfont.families())
        self._ui_font = next((f for f in theme.UI_FONTS if f in families), "Segoe UI")
        self._display_font = next((f for f in theme.DISPLAY_FONTS if f in families), "Segoe UI")
        self._preview = bool(os.environ.get("K_OPTIMIZER_PREVIEW"))
        theme.set_launcher_hint(settings.launcher_path())
        self.pal = theme.load()
        self.motion = theme.motion_scale()

        self.canvas = tk.Canvas(self, width=_W, height=_H, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", lambda e: self._set_hover(self._hit(e.x, e.y)))
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        self._regions: list[tuple[tuple[str, str], tuple[float, float, float, float]]] = []
        self._hover: tuple[str, str] | None = None

        self._page = os.environ.get("K_SERIES_PAGE", "home")
        self._products: list[products.Product] = []
        self._scanning = True
        self._scan_q: queue.SimpleQueue = queue.SimpleQueue()
        self._message = ""
        self._tick = 0
        self._motion_now = theme.motion_scale()
        self._updates: dict[str, updater.Status] = {}
        self._upd_q: queue.SimpleQueue = queue.SimpleQueue()
        self._upd_done: queue.SimpleQueue = queue.SimpleQueue()
        self._update_busy = False
        self._check_pending = True
        self._auto_tried: set[str] = set()
        if getattr(sys, 'frozen', False):
            updater.cleanup_old(Path(sys.executable))  # the copy we replaced during the last update

        self.optimizer = OptimizerPanel(self, lambda: self.pal, lambda: self.motion, show_header=False,
                                        width=_W - _SIDEBAR, height=_H, relaunch_args="-m k_series")
        apply_window_theme(self, self.pal)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<<KSeriesQuit>>", lambda e: self._close())
        self._rescan()
        self.after(_FRAME_MS, self._frame)
        self.after(_THEME_POLL_MS, self._follow_theme)

    # --- plumbing ---------------------------------------------------------------
    def _font(self, size, bold=False, display=False):
        return (self._display_font if display else self._ui_font, size, "bold" if bold else "normal")

    def _follow_theme(self):
        pal = theme.load()
        self.motion = theme.motion_scale()
        if pal != self.pal:
            self.pal = pal
            apply_window_theme(self, pal)
        self.after(_THEME_POLL_MS, self._follow_theme)

    def _rescan(self):
        self._scanning = True
        theme.reset_launcher_cache()
        saved = settings.launcher_path()
        threading.Thread(target=lambda: self._scan_q.put(products.detect(saved=saved)), daemon=True).start()

    def _goto(self, page: str):
        self._page = page
        self._message = ""
        if page == "optimizer":
            self.optimizer.place(x=_SIDEBAR, y=0, width=_W - _SIDEBAR, height=_H)
        else:
            self.optimizer.place_forget()

    def _product(self, pid: str) -> products.Product | None:
        return next((p for p in self._products if p.id == pid), None)

    def _frame(self):
        while True:
            try:
                self._products = self._scan_q.get_nowait()
                self._scanning = False
            except queue.Empty:
                break
        if not self._scanning and self._check_pending and not self._preview:
            self._check_pending = False
            if settings.flag("auto_check", True):
                self._check_updates()
        self._drain_updates()
        self._tick += 1
        if self._page == "optimizer" and not self.optimizer.winfo_ismapped():
            self._goto("optimizer")
        self._draw()
        self.after(_FRAME_MS, self._frame)

    # --- updates ------------------------------------------------------------------
    def _local_version(self, upid: str) -> str | None:
        if upid == "k-series":
            return __version__
        prod = self._product("k-launcher")
        return prod.version if prod and prod.installed else None

    def _check_updates(self, announce: bool = False):
        if self._preview or self._update_busy:
            return
        jobs = {upid: (settings.repo(upid), self._local_version(upid)) for upid in ("k-launcher", "k-series")}
        if announce:
            self._message = "Güncellemeler denetleniyor…"

        def work():
            self._upd_q.put(({u: updater.check(u, repo, ver) for u, (repo, ver) in jobs.items()}, announce))

        threading.Thread(target=work, daemon=True).start()

    def _summary(self) -> str:
        parts = []
        for upid, st in self._updates.items():
            name = _UPDATE_NAMES[upid].split(" ")[0]
            if st.state == "available":
                parts.append(f"{name}: yeni sürüm {st.release.tag}")
            elif st.state == "current":
                parts.append(f"{name}: güncel")
            elif st.state == "none":
                parts.append(f"{name}: henüz yayın yok")
            else:
                parts.append(f"{name}: {st.message}")
        return " · ".join(parts)

    def _drain_updates(self):
        while True:
            try:
                results, announce = self._upd_q.get_nowait()
            except queue.Empty:
                break
            self._updates = results
            if announce:
                self._message = self._summary()
            if settings.flag("auto_install", False) and not self._preview:
                for upid, st in results.items():
                    if st.state == "available" and upid not in self._auto_tried:
                        self._auto_tried.add(upid)  # once per session, so a failing update cannot loop
                        self._start_update(upid, ask=False)
                        break
        while True:
            try:
                message, quit_app, rescan = self._upd_done.get_nowait()
            except queue.Empty:
                break
            self._update_busy = False
            self._message = message
            if rescan:
                self.after(15000, self._rescan)
            if quit_app:
                self.after(600, self._close)

    def _start_update(self, upid: str, ask: bool = True):
        st = self._updates.get(upid)
        if self._preview or self._update_busy or st is None or st.state != "available":
            return
        rel, name = st.release, _UPDATE_NAMES[upid]
        if upid == "k-series" and not getattr(sys, "frozen", False):
            self._message = "K-Series yalnızca exe sürümünde güncellenebilir."
            return
        launcher = self._product("k-launcher")
        running = upid == "k-launcher" and launcher is not None and launcher.running
        if running and not ask:
            self._message = "K-Launcher açık olduğu için otomatik güncelleme beklemede; elle güncelleyebilirsin."
            return
        if ask:
            local = self._local_version(upid) or "?"
            text = f"{name}\n{local}  →  {rel.tag}\n\n{rel.notes.strip()[:300]}\n\n"
            text += ("K-Launcher şu an açık; güncelleme için nazikçe kapatılacak.\n\n" if running else "")
            text += "İndirilsin ve kurulsun mu?"
            if not messagebox.askyesno("Güncelleme", text):
                return
        self._update_busy = True
        threading.Thread(target=self._update_job, args=(upid, rel, name), daemon=True).start()

    def _update_job(self, upid: str, rel: updater.Release, name: str):
        dest = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "K-Series" / "updates"

        def progress(done: int, total: int):
            self._message = f"{name} indiriliyor… %{done * 100 // total}" if total else f"{name} indiriliyor…"

        try:
            path = updater.download(rel, dest, progress=progress)
            self._message = f"{name} kuruluyor…"
            if upid == "k-launcher":
                updater.install_launcher(path)
                self._upd_done.put((f"K-Launcher {rel.tag} kuruluyor, birkaç saniye içinde yeniden açılır.", False, True))
            else:
                updater.install_self(path, Path(sys.executable))
                self._upd_done.put((f"K-Series {rel.tag} kuruldu, yeniden başlatılıyor…", True, False))
        except updater.UpdateError as e:
            self._upd_done.put((str(e), False, False))
        except Exception as e:  # never leave the UI stuck in "busy"
            self._upd_done.put((f"Güncelleme beklenmedik bir hatayla durdu: {e}", False, False))

    # --- drawing ------------------------------------------------------------------
    def _draw(self):
        c, p = self.canvas, self.pal
        c.configure(bg=p.background)
        c.delete("all")
        self._regions = []
        self._draw_sidebar()
        page = {"home": self._draw_home, "launcher": self._draw_launcher, "settings": self._draw_settings}
        if self._page in page:  # the optimizer page is a panel laid over the content area
            page[self._page]()
        if self._message:
            c.create_text(_SIDEBAR + 40, _H - 24, anchor="w", text=self._message, fill=p.primary,
                          font=self._font(10), width=_W - _SIDEBAR - 80)

    def _region(self, key: tuple[str, str], box) -> None:
        self._regions.append((key, box))

    def _draw_sidebar(self):
        c, p = self.canvas, self.pal
        c.create_rectangle(0, 0, _SIDEBAR, _H, fill=p.surface, outline="")
        c.create_line(_SIDEBAR, 0, _SIDEBAR, _H, fill=p.outline)
        c.create_text(28, 44, anchor="w", text="K-SERIES", fill=p.primary, font=self._font(24, True, True))
        c.create_text(28, 72, anchor="w", text="Tek çatı, tüm K ürünleri", fill=theme.TEXT_MUTED, font=self._font(9))
        y = 118
        for key, label in _NAV:
            selected = self._page == key
            hover = self._hover == ("nav", key)
            box = (14, y, _SIDEBAR - 14, y + 44)
            if selected or hover:
                c.create_polygon(round_rect_points(*box, theme.RADIUS[1]), smooth=True,
                                 fill=theme.accent_soft(p) if selected else p.control, outline="")
            if selected:
                c.create_rectangle(14, y + 10, 17, y + 34, fill=p.primary, outline="")
            c.create_text(36, y + 22, anchor="w", text=label, fill=p.primary if selected else theme.TEXT,
                          font=self._font(12, True, True))
            self._region(("nav", key), box)
            y += 52
        c.create_text(28, _H - 30, anchor="w", text=f"K-Series v{__version__}", fill=theme.TEXT_FAINT,
                      font=self._font(9))

    def _title(self, text: str, sub: str):
        c, p = self.canvas, self.pal
        c.create_text(_SIDEBAR + 40, 48, anchor="w", text=text, fill=theme.TEXT, font=self._font(24, True, True))
        c.create_text(_SIDEBAR + 40, 82, anchor="w", text=sub, fill=theme.TEXT_MUTED, font=self._font(10))

    def _card(self, x0, y0, x1, y1):
        p = self.pal
        self.canvas.create_polygon(round_rect_points(x0, y0, x1, y1, theme.RADIUS[3]), smooth=True,
                                   fill=p.card, outline=p.outline, width=1)

    def _badge(self, x, y, size, text):
        c, p = self.canvas, self.pal
        c.create_polygon(round_rect_points(x, y, x + size, y + size, theme.RADIUS[2]), smooth=True,
                         fill=theme.accent_soft(p), outline=p.primary, width=2)
        c.create_text(x + size / 2, y + size / 2, text=text, fill=p.primary,
                      font=self._font(round(size * 0.36), True, True))

    def _button(self, key: tuple[str, str], x0, y0, x1, y1, text: str, primary: bool = True, enabled: bool = True):
        c, p = self.canvas, self.pal
        hover = enabled and self._hover == key
        if primary:
            fill = theme.blend(p.primary, "#FFFFFF", 0.18) if hover else p.primary
            c.create_polygon(round_rect_points(x0, y0, x1, y1, theme.RADIUS[1]), smooth=True,
                             fill=fill if enabled else p.control, outline="")
            color = theme.ON_ACCENT if enabled else theme.TEXT_FAINT
        else:
            c.create_polygon(round_rect_points(x0, y0, x1, y1, theme.RADIUS[1]), smooth=True,
                             fill=theme.accent_soft(p) if hover else p.control, outline=p.outline)
            color = theme.TEXT if enabled else theme.TEXT_FAINT
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text, fill=color, font=self._font(11, True, True))
        if enabled:
            self._region(key, (x0, y0, x1, y1))

    def _status(self, x, y, product: products.Product) -> str:
        p = self.pal
        if product.builtin:
            label, color = "Yerleşik modül", p.primary
        elif product.running:
            label, color = "Çalışıyor", p.primary
        elif product.installed:
            label, color = "Kurulu", p.secondary
        else:
            label, color = "Bulunamadı", theme.TEXT_FAINT
        self.canvas.create_oval(x, y - 4, x + 8, y + 4, fill=color, outline="")
        self.canvas.create_text(x + 16, y, anchor="w", text=label, fill=color, font=self._font(10, True))
        return label

    def _draw_home(self):
        c, p = self.canvas, self.pal
        self._title("Ürünler", "Bu bilgisayarda algılanan K ürünleri")
        if self._scanning:
            dots = "." * (1 + (self._tick // 10) % 3)
            c.create_text(_SIDEBAR + 40, 150, anchor="w", text=f"Ürünler aranıyor{dots}", fill=theme.TEXT_MUTED,
                          font=self._font(12))
            return
        x = _SIDEBAR + 40
        card_w, card_h, gap = (_W - _SIDEBAR - 80 - 24) / 2, 232, 24
        for i, prod in enumerate(self._products):
            x0, y0 = x + i * (card_w + gap), 120
            self._card(x0, y0, x0 + card_w, y0 + card_h)
            self._badge(x0 + 24, y0 + 24, 64, "KO" if prod.id == "k-optimizer" else "KL")
            c.create_text(x0 + 108, y0 + 40, anchor="w", text=prod.name, fill=theme.TEXT,
                          font=self._font(18, True, True))
            c.create_text(x0 + 108, y0 + 68, anchor="w", text=prod.tagline, fill=theme.TEXT_MUTED,
                          font=self._font(10))
            self._status(x0 + 24, y0 + 116, prod)
            if prod.version:
                c.create_text(x0 + card_w - 24, y0 + 116, anchor="e", text=f"v{prod.version}",
                              fill=theme.TEXT_MUTED, font=self._font(10))
            upid = _CARD_UPDATE.get(prod.id)
            st = self._updates.get(upid) if upid else None
            has_update = st is not None and st.state == "available"
            if has_update:
                c.create_text(x0 + 24, y0 + 146, anchor="w", text=f"↑ Yeni sürüm: {st.release.tag}",
                              fill=p.secondary, font=self._font(10, True))
            elif st is not None and st.state == "current":
                c.create_text(x0 + 24, y0 + 146, anchor="w", text="Güncel", fill=theme.TEXT_FAINT,
                              font=self._font(9))
            by = y0 + card_h - 56
            bx = x0 + 24
            if prod.builtin:
                self._button(("goto", "optimizer"), bx, by, bx + 120, by + 40, "Aç")
                bx += 130
            else:
                self._button(("open", prod.id), bx, by, bx + 120, by + 40,
                             "Aç" if prod.installed else "Bulunamadı", enabled=prod.installed)
                self._button(("goto", "launcher"), bx + 130, by, bx + 130 + 100, by + 40, "Ayrıntı", primary=False)
                bx += 240
            if has_update:
                busy = self._update_busy
                self._button(("update", upid), bx, by, bx + 120, by + 40, "Güncelle" if not busy else "Bekle…",
                             enabled=not busy)
        self._button(("rescan", ""), x, 380, x + 150, 420, "Yeniden tara", primary=False)
        c.create_text(x + 170, 400, anchor="w", text="Kurulu ürünleri yeniden algılar", fill=theme.TEXT_FAINT,
                      font=self._font(9))

    def _draw_launcher(self):
        c, p = self.canvas, self.pal
        self._title("K-Launcher", "Oyun ve uygulama başlatıcı")
        prod = self._product("k-launcher")
        if self._scanning or prod is None:
            c.create_text(_SIDEBAR + 40, 150, anchor="w", text="Aranıyor...", fill=theme.TEXT_MUTED,
                          font=self._font(12))
            return
        x0, y0, x1, y1 = _SIDEBAR + 40, 120, _W - 40, 120 + 340
        self._card(x0, y0, x1, y1)
        self._badge(x0 + 28, y0 + 28, 80, "KL")
        c.create_text(x0 + 130, y0 + 50, anchor="w", text=prod.name, fill=theme.TEXT, font=self._font(20, True, True))
        self._status(x0 + 130, y0 + 84, prod)
        rows = [("Konum", str(prod.path) if prod.path else "Bulunamadı"),
                ("Sürüm", prod.version or "-"),
                ("Tema", f"{self.pal.name} (K-Series ile ortak)"),
                ("Ayar klasörü", str(theme.data_dirs()[0]))]
        for i, (k, v) in enumerate(rows):
            ry = y0 + 142 + i * 30
            c.create_text(x0 + 28, ry, anchor="w", text=k, fill=theme.TEXT_MUTED, font=self._font(10))
            c.create_text(x0 + 150, ry, anchor="w", text=v, fill=theme.TEXT, font=self._font(10),
                          width=x1 - x0 - 180)
        by = y1 - 68
        self._button(("open", "k-launcher"), x0 + 28, by, x0 + 28 + 190, by + 40, "K-Launcher'ı aç",
                     enabled=prod.installed)
        self._button(("folder", "k-launcher"), x0 + 28 + 202, by, x0 + 28 + 202 + 150, by + 40, "Klasörü aç",
                     primary=False, enabled=prod.installed)
        self._button(("pick", ""), x0 + 28 + 364, by, x0 + 28 + 364 + 150, by + 40, "Konum seç...", primary=False)
        if not prod.installed:
            self._button(("web", ""), x0 + 28 + 526, by, x0 + 28 + 526 + 180, by + 40, "itch.io sayfası", primary=False)

    def _draw_settings(self):
        c, p = self.canvas, self.pal
        self._title("Ayarlar", "Tema ve hareket, K-Launcher ile ortaktır")
        x = _SIDEBAR + 40
        c.create_text(x, 128, anchor="w", text="TEMA", fill=theme.TEXT_MUTED, font=self._font(10, True, True))
        cols, tw, th, gap = 4, 190, 92, 16
        for i, pal in enumerate(theme.PALETTES.values()):
            x0 = x + (i % cols) * (tw + gap)
            y0 = 148 + (i // cols) * (th + gap)
            selected = pal.id == self.pal.id
            hover = self._hover == ("theme", pal.id)
            c.create_polygon(round_rect_points(x0, y0, x0 + tw, y0 + th, theme.RADIUS[2]), smooth=True,
                             fill=pal.card, outline=pal.primary if selected else (pal.secondary if hover else pal.outline),
                             width=2 if selected else 1)
            for j, col in enumerate((pal.primary, pal.secondary)):
                c.create_oval(x0 + 18 + j * 26, y0 + 18, x0 + 38 + j * 26, y0 + 38, fill=col, outline="")
            c.create_text(x0 + 18, y0 + 62, anchor="w", text=pal.name, fill=theme.TEXT, font=self._font(11, True, True))
            if selected:
                c.create_text(x0 + tw - 16, y0 + 24, anchor="e", text="✓", fill=pal.primary, font=self._font(14, True))
            self._region(("theme", pal.id), (x0, y0, x0 + tw, y0 + th))
        my = 148 + 2 * (th + gap) + 20
        c.create_text(x, my, anchor="w", text="HAREKET HIZI", fill=theme.TEXT_MUTED, font=self._font(10, True, True))
        current = next((w for w, m in (("fast", 0.55), ("normal", 1.0), ("slow", 1.6), ("off", 0.0))
                        if abs(m - self.motion) < 1e-6), "normal")
        for i, (word, label) in enumerate(_MOTIONS):
            x0 = x + i * 130
            sel = word == current
            hover = self._hover == ("motion", word)
            c.create_polygon(round_rect_points(x0, my + 22, x0 + 116, my + 62, theme.RADIUS[1]), smooth=True,
                             fill=theme.accent_soft(p) if sel else (p.control if hover else p.card),
                             outline=p.primary if sel else p.outline, width=2 if sel else 1)
            c.create_text(x0 + 58, my + 42, text=label, fill=p.primary if sel else theme.TEXT,
                          font=self._font(11, True, True))
            self._region(("motion", word), (x0, my + 22, x0 + 116, my + 62))
        c.create_text(x, my + 96, anchor="w", width=_W - _SIDEBAR - 80, fill=theme.TEXT_FAINT, font=self._font(9),
                      text=f"Seçim {theme.data_dirs()[0]} klasörüne yazılır. K-Launcher bir sonraki açılışında bu "
                           "temayı kullanır; K-Series ve K-Optimizer hemen değişir.")
        uy = my + 150
        c.create_text(x, uy, anchor="w", text="GÜNCELLEMELER (GITHUB)", fill=theme.TEXT_MUTED,
                      font=self._font(10, True, True))
        for i, (key, label, default) in enumerate((("auto_check", "Açılışta denetle", True),
                                                   ("auto_install", "Kendiliğinden kur", False))):
            x0 = x + i * 246
            on = settings.flag(key, default)
            hover = self._hover == ("flag", key)
            c.create_polygon(round_rect_points(x0, uy + 18, x0 + 232, uy + 58, theme.RADIUS[1]), smooth=True,
                             fill=theme.accent_soft(p) if on else (p.control if hover else p.card),
                             outline=p.primary if on else p.outline, width=2 if on else 1)
            c.create_text(x0 + 116, uy + 38, text=("✓  " if on else "") + label,
                          fill=p.primary if on else theme.TEXT, font=self._font(11, True, True))
            self._region(("flag", key), (x0, uy + 18, x0 + 232, uy + 58))
        self._button(("checknow", ""), x + 500, uy + 18, x + 500 + 150, uy + 58, "Şimdi denetle", primary=False,
                     enabled=not self._update_busy)
        for i, upid in enumerate(("k-launcher", "k-series")):
            ry = uy + 86 + i * 30
            c.create_text(x, ry, anchor="w", fill=theme.TEXT_MUTED, font=self._font(10),
                          text=f"{_UPDATE_NAMES[upid].split(' ')[0]} deposu:")
            c.create_text(x + 200, ry, anchor="w", fill=theme.TEXT, font=self._font(10), text=settings.repo(upid))
            self._button(("repo", upid), x + 400, ry - 13, x + 400 + 100, ry + 13, "Değiştir", primary=False)

    # --- interaction --------------------------------------------------------------
    def _hit(self, x, y):
        for key, (x0, y0, x1, y1) in self._regions:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key
        return None

    def _set_hover(self, key):
        self._hover = key
        self.canvas.configure(cursor="hand2" if key else "")

    def _on_click(self, e):
        key = self._hit(e.x, e.y)
        if key is None:
            return
        kind, arg = key
        if kind in ("nav", "goto"):
            return self._goto(arg)
        if self._preview:
            return  # preview mode: look around but never act on the user's system or settings
        if kind == "open":
            prod = self._product(arg)
            ok = prod is not None and products.launch(prod)
            self._message = f"{prod.name if prod else arg} başlatıldı." if ok else "Başlatılamadı."
            if ok:
                self.after(2500, self._rescan)
        elif kind == "folder":
            prod = self._product(arg)
            if prod and prod.path:
                os.startfile(str(prod.path.parent))
        elif kind == "rescan":
            self._message = ""
            self._rescan()
        elif kind == "pick":
            self._pick_launcher()
        elif kind == "web":
            webbrowser.open(_ITCH)
        elif kind == "theme":
            ok = theme.save(arg)
            self.pal = theme.load()
            apply_window_theme(self, self.pal)
            self._message = "" if ok else "Tema ayar klasörüne yazılamadı (salt okunur olabilir)."
        elif kind == "motion":
            ok = theme.save_motion(arg)
            self.motion = theme.motion_scale()
            self._message = "" if ok else "Hareket ayarı yazılamadı."
        elif kind == "update":
            self._start_update(arg, ask=True)
        elif kind == "checknow":
            self._check_updates(announce=True)
        elif kind == "flag":
            defaults = {"auto_check": True, "auto_install": False}
            ok = settings.save({**settings.load(), arg: not settings.flag(arg, defaults[arg])})
            self._message = "" if ok else "Ayar kaydedilemedi."
        elif kind == "repo":
            self._change_repo(arg)

    def _change_repo(self, upid: str):
        value = simpledialog.askstring("GitHub deposu", f"{_UPDATE_NAMES[upid]} güncellemeleri hangi depodan gelsin?\n"
                                       "(sahip/depo biçiminde, ör. ikagzy/k-launcher)", initialvalue=settings.repo(upid),
                                       parent=self)
        if value is None:
            return
        value = value.strip()
        if not updater._REPO_RE.match(value):
            self._message = "Geçersiz depo adı. 'sahip/depo' biçiminde yaz."
            return
        data = settings.load()
        repos = data.get("repos") if isinstance(data.get("repos"), dict) else {}
        ok = settings.save({**data, "repos": {**repos, upid: value}})
        self._message = f"Depo kaydedildi: {value}" if ok else "Depo kaydedilemedi."
        self._check_updates(announce=True)

    def _pick_launcher(self):
        path = filedialog.askopenfilename(title="KLauncher.exe seç", filetypes=[("K-Launcher", "KLauncher.exe"),
                                                                                  ("Uygulama", "*.exe")])
        if not path:
            return
        ok = settings.save({**settings.load(), "launcher_path": path})
        theme.set_launcher_hint(Path(path))
        self._message = "Konum kaydedildi." if ok else "Konum kaydedilemedi."
        self._rescan()

    def _close(self):
        self.optimizer.shutdown()
        self.destroy()


def run() -> None:
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    KSeriesApp().mainloop()
