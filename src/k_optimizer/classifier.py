import json
import os
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


def _in_windows_dir(exe: str) -> bool:
    root = os.environ.get("SystemRoot", r"C:\Windows").lower().rstrip("\\")
    return exe.lower().replace("/", "\\").startswith(root + "\\")


def classify(p: ProcInfo, known: KnownApps, own_pids: frozenset[int]) -> Level:
    if p.pid in own_pids or p.exe is None or _in_windows_dir(p.exe):
        return Level.PROTECTED
    name = p.name.lower()
    if name in _PROTECTED_NAMES:
        return Level.PROTECTED
    return Level.SAFE if known.is_safe(name) else Level.UNKNOWN
