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

from k_optimizer import procscan

EXE_NAME = "KLauncher.exe"
OPTIMIZER_EXE = "K-Optimizer.exe"
_SKIP_DIRS = {"obj", "bin", ".git", "node_modules", "__pycache__", "assets", "data"}


def _env(name: str, default: str) -> Path:
    return Path(os.environ.get(name) or default)


def _exe_of(pid: int) -> str | None:
    try:
        return psutil.Process(pid).exe() or None
    except (psutil.Error, OSError):
        return None


def _running_named(name: str, scan=None, exe_of=_exe_of) -> list[Path]:
    """Paths of the running processes with this image name. The process table comes from one system call; only
    the (few) matches are asked for their path. (psutil.process_iter(["exe"]) queried every process separately:
    about a second of CPU, and the theme poller did it every 20 seconds.)"""
    scan = scan or procscan.scan
    out: list[Path] = []
    try:
        matches = [r.pid for r in scan() if r.name.lower() == name.lower()]
    except (OSError, AttributeError):
        matches = [p.pid for p in _iter_psutil(name)]
    for pid in matches:
        exe = exe_of(pid)
        if exe and Path(exe) not in out:
            out.append(Path(exe))
    return out


def _iter_psutil(name: str):
    for p in psutil.process_iter(["name", "pid"]):
        try:
            if (p.info["name"] or "").lower() == name.lower():
                yield p
        except psutil.Error:
            continue


def running_exes() -> list[Path]:
    return _running_named(EXE_NAME)


def running_optimizer_exes() -> list[Path]:
    return _running_named(OPTIMIZER_EXE)


def install_candidates() -> list[Path]:
    local = _env("LOCALAPPDATA", str(Path.home()))
    return [
        local / "Programs" / "K-Launcher" / EXE_NAME,
        _env("ProgramFiles", "C:/Program Files") / "K-Launcher" / EXE_NAME,
        _env("ProgramFiles(x86)", "C:/Program Files (x86)") / "K-Launcher" / EXE_NAME,
        local / "K-Launcher" / EXE_NAME,
    ]


def scan_for_exe(roots: list[Path], depth: int = 4, name: str = EXE_NAME) -> list[Path]:
    """Shallow search for copies that are not installed (portable/dev folders). Nearest to the root first
    (the copy sitting on the desktop beats one buried in a build folder), newest first among equals."""
    found: list[tuple[int, Path]] = []

    def walk(folder: Path, level: int):
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return
        for e in entries:
            try:
                if e.is_file() and e.name.lower() == name.lower():
                    found.append((level, Path(e.path)))
                elif level < depth and e.is_dir(follow_symlinks=False) and e.name.lower() not in _SKIP_DIRS:
                    walk(Path(e.path), level + 1)
            except OSError:
                continue

    for root in roots:
        walk(root, 0)
    return [p for _, p in sorted(found, key=lambda t: (t[0], -t[1].stat().st_mtime))]


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


def _pids_named(name: str, scan=None) -> list[int]:
    scan = scan or procscan.scan
    try:
        return [r.pid for r in scan() if r.name.lower() == name.lower()]
    except (OSError, AttributeError):
        return [p.pid for p in _iter_psutil(name)]


def running_pids() -> list[int]:
    return _pids_named(EXE_NAME)


def running_optimizer_pids() -> list[int]:
    return _pids_named(OPTIMIZER_EXE)


def optimizer_install_path() -> Path:
    """Where K-Series installs K-Optimizer when it is not found anywhere."""
    return _env("LOCALAPPDATA", str(Path.home())) / "Programs" / "K-Optimizer" / OPTIMIZER_EXE


def find_optimizer(
    saved: Path | None = None,
    running: Callable[[], list[Path]] | None = None,
    scan_roots: list[Path] | None = None,
    extra_dirs: list[Path] | tuple = (),
) -> Path | None:
    """K-Optimizer is its own app: running copy, saved path, next to K-Series, install folders, shallow scan."""
    live = (running or running_optimizer_exes)()
    if live:
        return live[0]
    if saved is not None and saved.is_file():
        return saved
    candidates = [Path(d) / OPTIMIZER_EXE for d in extra_dirs] + [
        optimizer_install_path(),
        _env("ProgramFiles", "C:/Program Files") / "K-Optimizer" / OPTIMIZER_EXE,
        _env("ProgramFiles(x86)", "C:/Program Files (x86)") / "K-Optimizer" / OPTIMIZER_EXE,
    ]
    for c in candidates:
        if c.is_file():
            return c
    scanned = scan_for_exe(default_scan_roots() if scan_roots is None else scan_roots, name=OPTIMIZER_EXE)
    return scanned[0] if scanned else None
