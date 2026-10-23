"""Product detection, the way SteelSeries GG detects devices: find what is installed, report its state."""
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import k_optimizer
from k_optimizer import klauncher


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    tagline: str
    installed: bool
    builtin: bool
    path: Path | None
    version: str | None
    running: bool


def detect(saved: Path | None = None, scan_roots: list[Path] | None = None) -> list[Product]:
    optimizer = Product("k-optimizer", "K-Optimizer", "RAM, GPU ve CPU temizleyici",
                        installed=True, builtin=True, path=None, version=k_optimizer.__version__, running=True)
    exe = klauncher.find_exe(saved=saved, scan_roots=scan_roots)
    launcher = Product("k-launcher", "K-Launcher", "Oyun ve uygulama başlatıcı",
                       installed=exe is not None, builtin=False, path=exe,
                       version=klauncher.file_version(exe) if exe else None,
                       running=klauncher.is_running(exe))
    return [optimizer, launcher]


def launch(product: Product, popen: Callable = subprocess.Popen) -> bool:
    """Start an installed external product in its own folder. Built-in or missing products are refused."""
    if product.builtin or product.path is None or not product.path.is_file():
        return False
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        popen([str(product.path)], cwd=str(product.path.parent), creationflags=flags, close_fds=True,
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
