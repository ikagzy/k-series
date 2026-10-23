"""The app icon follows the theme: K-Optimizer's KO and K-Series' KS logos (AppIcons/<app>/<theme>.ico), with
K-Launcher's ThemeIcons as the fallback."""
import base64
import shutil
import struct
import tkinter as tk
from pathlib import Path

from k_optimizer import theme

THEME_ICONS = Path(__file__).parent / "assets" / "ThemeIcons"
APP_ICONS = Path(__file__).parent / "assets" / "AppIcons"
_FALLBACK = Path(__file__).parent / "assets" / "klauncher.ico"
DEFAULT_APP = "ko"  # 'ko' K-Optimizer, 'ks' K-Series, 'kl' K-Launcher (its own ThemeIcons)


def icon_for(pal: theme.Palette, app: str | None = None) -> Path:
    """This app's logo for the theme, else K-Launcher's icon for it, else the default K icon."""
    for path in (APP_ICONS / (app or DEFAULT_APP) / f"{pal.id}.ico", THEME_ICONS / f"{pal.id}.ico"):
        if path.is_file():
            return path
    return _FALLBACK


def apply_window_icon(window: tk.Misc, pal: theme.Palette, app: str | None = None) -> bool:
    """Set the title-bar/taskbar icon of a Tk window to the theme's icon."""
    try:
        window.iconbitmap(str(icon_for(pal, app)))
    except tk.TclError:
        return False
    window._k_icon_key = pal.id
    return True


def current_icon_key(window: tk.Misc):
    return getattr(window, "_k_icon_key", None)


def shortcut_icon(folder: Path, pal: theme.Palette, app: str | None = None) -> Path:
    """A stable on-disk copy of the theme icon for a desktop shortcut (the bundled one lives in a temp folder
    inside the exe). The file name differs per theme, so Explorer never serves a cached icon of the old theme."""
    dest = folder / (f"{pal.id}.ico" if app is None else f"{pal.id}-{app}.ico")
    if not dest.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(icon_for(pal, app), dest)
    return dest


def png_layer(pal: theme.Palette, size: int, app: str | None = None) -> bytes | None:
    """The PNG stored inside the theme's .ico whose size is closest to `size` (smallest one that is big enough,
    else the biggest). Tk cannot read .ico files but reads these PNGs directly."""
    try:
        raw = icon_for(pal, app).read_bytes()
        count = struct.unpack("<H", raw[4:6])[0]
        layers = []
        for i in range(count):
            w, _, _, _, _, _, length, offset = struct.unpack("<BBBBHHII", raw[6 + 16 * i: 22 + 16 * i])
            data = raw[offset: offset + length]
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                layers.append((w or 256, data))
    except (OSError, struct.error):
        return None
    if not layers:
        return None
    layers.sort(key=lambda t: t[0])
    return next((d for w, d in layers if w >= size), layers[-1][1])


def photo(window: tk.Misc, pal: theme.Palette, size: int, app: str | None = None) -> tk.PhotoImage | None:
    """The theme's K logo as a Tk image of about `size` pixels, cached on the window."""
    cache = window.__dict__.setdefault("_k_photos", {})
    key = (pal.id, size, app)
    if key not in cache:
        data = png_layer(pal, size, app)
        if data is None:
            return None
        cache[key] = tk.PhotoImage(master=window, data=base64.b64encode(data).decode())
    return cache[key]
