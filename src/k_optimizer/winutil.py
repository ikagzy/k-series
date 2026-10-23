import ctypes
from ctypes import wintypes


def visible_window_pids() -> frozenset[int]:
    """PIDs owning a visible, titled top-level window, i.e. apps the user can actually see."""
    pids: set[int] = set()
    try:
        user32 = ctypes.windll.user32
        callback_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pids.add(pid.value)
            return True

        user32.EnumWindows(callback_t(cb), 0)
    except (AttributeError, OSError):
        return frozenset()
    return frozenset(pids)
