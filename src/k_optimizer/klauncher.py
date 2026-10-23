"""Finding K-Launcher and the folder it keeps its settings in.

K-Launcher (C#/WPF) stores theme.txt, motion.txt, ... in a `Data` folder next to its exe, falling back to
%LOCALAPPDATA%/K-Launcher when that is not writable; very old builds used %APPDATA%/K-Launcher.
"""
import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

import psutil

EXE_NAME = "KLauncher.exe"
_SKIP_DIRS = {"obj", "bin", ".git", "node_modules", "__pycache__", "assets", "data"}


def _env(name: str, default: str) -> Path:
    return Path(os.environ.get(name) or default)


def running_exes() -> list[Path]:
    out: list[Path] = []
    for p in psutil.process_iter(["name", "exe"]):
        try:
            if (p.info["name"] or "").lower() == EXE_NAME.lower() and p.info["exe"]:
                exe = Path(p.info["exe"])
                if exe not in out:
                    out.append(exe)
        except psutil.Error:
            continue
    return out


def install_candidates() -> list[Path]:
    local = _env("LOCALAPPDATA", str(Path.home()))
    return [
        local / "Programs" / "K-Launcher" / EXE_NAME,
        _env("ProgramFiles", "C:/Program Files") / "K-Launcher" / EXE_NAME,
        _env("ProgramFiles(x86)", "C:/Program Files (x86)") / "K-Launcher" / EXE_NAME,
        local / "K-Launcher" / EXE_NAME,
    ]


def scan_for_exe(roots: list[Path], depth: int = 4) -> list[Path]:
    """Shallow search for copies that are not installed (portable/dev folders), newest first."""
    found: list[Path] = []

    def walk(folder: Path, left: int):
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return
        for e in entries:
            try:
                if e.is_file() and e.name.lower() == EXE_NAME.lower():
                    found.append(Path(e.path))
                elif left > 0 and e.is_dir(follow_symlinks=False) and e.name.lower() not in _SKIP_DIRS:
                    walk(Path(e.path), left - 1)
            except OSError:
                continue

    for root in roots:
        walk(root, depth)
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def default_scan_roots() -> list[Path]:
    return [Path.home() / "Desktop", Path.home() / "Downloads"]


def find_exe(
    saved: Path | None = None,
    running: Callable[[], list[Path]] | None = None,
    scan_roots: list[Path] | None = None,
) -> Path | None:
    """Running copy, then the user's saved path, then known install folders, then a shallow scan."""
    live = (running or running_exes)()  # looked up at call time so tests can replace it
    if live:
        return live[0]
    if saved is not None and saved.is_file():
        return saved
    for c in install_candidates():
        if c.is_file():
            return c
    scanned = scan_for_exe(default_scan_roots() if scan_roots is None else scan_roots)
    return scanned[0] if scanned else None


def data_dirs(exe: Path | None) -> list[Path]:
    """Where K-Launcher keeps (or kept) its settings, current location first."""
    dirs = [exe.parent / "Data"] if exe is not None else []
    dirs.append(_env("LOCALAPPDATA", str(Path.home())) / "K-Launcher")
    dirs.append(_env("APPDATA", str(Path.home())) / "K-Launcher")
    return dirs


def is_running(exe: Path | None) -> bool:
    if exe is None:
        return False
    try:
        return any(p.samefile(exe) for p in running_exes() if p.exists())
    except OSError:
        return False


def file_version(exe: Path) -> str | None:
    """The exe's version resource (e.g. '4.0.1.0'), or None."""
    try:
        ver = ctypes.windll.version
        path = str(exe)
        ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(wintypes.UINT)]
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return None
        ptr, length = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) or length.value < 52:
            return None
        info = ctypes.cast(ptr, ctypes.POINTER(wintypes.DWORD * 13)).contents
        ms, ls = info[4], info[5]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (AttributeError, OSError, ValueError):
        return None
