"""Window chrome shared by K-Optimizer and K-Series (kept free of heavy imports)."""
import ctypes
import tkinter as tk

from k_optimizer import theme


def round_rect_points(x0, y0, x1, y1, r):
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
            x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def apply_window_theme(window: tk.Misc, pal: theme.Palette) -> None:
    """Dark, palette-coloured title bar and rounded corners (Windows 11); fails soft elsewhere."""
    window.configure(bg=pal.background)
    try:
        window.update_idletasks()
        dwm = ctypes.windll.dwmapi
        user32 = ctypes.windll.user32
        user32.GetParent.restype = ctypes.c_void_p
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()

        def colorref(c: str) -> ctypes.c_uint:
            r, g, b = theme._rgb(c)
            return ctypes.c_uint(r | g << 8 | b << 16)

        for attr, value in ((20, ctypes.c_int(1)), (33, ctypes.c_int(2)),
                            (35, colorref(pal.background)), (34, colorref(pal.outline)),
                            (36, colorref(theme.TEXT))):
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        pass
