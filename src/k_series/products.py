"""Product detection, the way SteelSeries GG detects devices: find what is installed, report its state.

Both K apps are separate programs: K-Series finds them, shows their state and launches them."""
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from k_optimizer import klauncher


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    tagline: str
    installed: bool
    path: Path | None
    version: str | None
    running: bool


def _product(pid: str, name: str, tagline: str, exe: Path | None, running: bool) -> Product:
    return Product(pid, name, tagline, exe is not None, exe,
                   klauncher.file_version(exe) if exe else None, running)


def detect(saved: Path | None = None, scan_roots: list[Path] | None = None,
           saved_optimizer: Path | None = None, extra_dirs: list[Path] | tuple = ()) -> list[Product]:
    """K-Optimizer and K-Launcher, each found (or not) on this computer. `saved` is the K-Launcher path."""
    opt = klauncher.find_optimizer(saved=saved_optimizer, scan_roots=scan_roots, extra_dirs=extra_dirs)
    launcher = klauncher.find_exe(saved=saved, scan_roots=scan_roots)
    return [
        _product("k-optimizer", "K-Optimizer", "RAM, GPU ve CPU temizleyici", opt,
                 bool(opt) and any(p.samefile(opt) for p in klauncher.running_optimizer_exes() if p.exists())),
        _product("k-launcher", "K-Launcher", "Oyun ve uygulama başlatıcı", launcher, klauncher.is_running(launcher)),
    ]


def launch(product: Product, popen: Callable = subprocess.Popen) -> bool:
    """Start an installed product in its own folder. A missing product is refused; failures never raise."""
    if product.path is None or not product.path.is_file():
        return False
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        popen([str(product.path)], cwd=str(product.path.parent), creationflags=flags, close_fds=True,
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
