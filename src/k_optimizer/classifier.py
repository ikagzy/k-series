import json
import os
from collections.abc import Iterable
from pathlib import Path

from k_optimizer.models import Level, ProcInfo

_BUILTIN = Path(__file__).parent / "data" / "known_apps.json"

_PROTECTED_NAMES = frozenset(
    "system, system idle process, registry, smss.exe, csrss.exe, wininit.exe, services.exe, "
    "lsass.exe, svchost.exe, winlogon.exe, explorer.exe, dwm.exe, fontdrvhost.exe, "
    "msmpeng.exe, nissrv.exe, securityhealthservice.exe, sihost.exe, ctfmon.exe, "
    "taskhostw.exe, runtimebroker.exe, searchhost.exe, startmenuexperiencehost.exe, "
    "shellexperiencehost.exe".split(", ")
)


class KnownApps:
    def __init__(self, safe: set[str]):
        self._safe = {n.lower() for n in safe}

    @classmethod
    def load(cls, builtin: Path, user: Path | None) -> "KnownApps":
        try:
            names = set(json.loads(builtin.read_text(encoding="utf-8"))["safe"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise ValueError(f"known apps file unreadable: {builtin}") from e
        if user is not None:
            try:
                names |= set(json.loads(user.read_text(encoding="utf-8"))["safe"])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return cls(names)

    def is_safe(self, name: str) -> bool:
        return name.lower() in self._safe


def default_known_apps() -> KnownApps:
    appdata = os.environ.get("APPDATA")
    user = Path(appdata) / "K-Optimizer" / "known_apps.user.json" if appdata else None
    return KnownApps.load(_BUILTIN, user)


def _norm(path: str) -> str:
    return path.lower().replace("/", chr(92))


def _under(exe: str, root: str) -> bool:
    return _norm(exe).startswith(_norm(root).rstrip(chr(92)) + chr(92))


def _in_windows_dir(exe: str) -> bool:
    return _under(exe, os.environ.get("SystemRoot", "C:" + chr(92) + "Windows"))


def _in_windows_components_dir(exe: str) -> bool:
    """Where Windows' own optional components live: the Windows dir or the packaged-apps dir."""
    apps = os.path.join(os.environ.get("ProgramFiles", "C:" + chr(92) + "Program Files"), "WindowsApps")
    return _in_windows_dir(exe) or _under(exe, apps)


def classify(p: ProcInfo, known: KnownApps, own_pids: frozenset[int]) -> Level:
    """SAFE means: a listed Windows component running from Windows' own folders. User apps never are."""
    if p.pid in own_pids or not p.exe or not os.path.isabs(p.exe):
        return Level.PROTECTED
    name = p.name.lower()
    if name in _PROTECTED_NAMES:
        return Level.PROTECTED
    if known.is_safe(name) and _in_windows_components_dir(p.exe):
        return Level.SAFE
    return Level.PROTECTED if _in_windows_dir(p.exe) else Level.UNKNOWN


_MB = 1024 * 1024


def _uses(p: ProcInfo, resource: str | None) -> bool:
    if resource == "cpu":
        return p.cpu_percent >= 0.5
    if resource == "gpu":
        return (p.gpu_percent or 0) > 0 or (p.vram_bytes or 0) >= 50 * _MB
    return True  # "ram" or no filter: every safe process holds memory


def safe_targets(
    procs: Iterable[ProcInfo], known: KnownApps, own_pids: frozenset[int], resource: str | None = None
) -> list[ProcInfo]:
    """Processes a boost may close: only SAFE ones, optionally those using `resource` (cpu/ram/gpu)."""
    return [p for p in procs if classify(p, known, own_pids) is Level.SAFE and _uses(p, resource)]
