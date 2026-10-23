"""Per-app GPU preference, the setting behind Windows Settings > System > Display > Graphics.

`HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences` holds one string value per exe, named with its full path,
`GpuPreference=2;` meaning "high performance GPU" (0 = let Windows decide, 1 = power saving). It lives in the
user's own hive, so no administrator is needed. Windows applies it when the app is next started. Every change is
recorded with the value it replaced, so it can be put back exactly.
"""
import json
import os
import re
import winreg
from pathlib import Path

DEFAULT_KEY = "Software\\Microsoft\\DirectX\\UserGpuPreferences"
HIGH = "GpuPreference=2;"
_PATH_RE = re.compile(r"^[A-Za-z]:\\[^\x00-\x1f;<>|\"?*]{1,240}\.exe$", re.IGNORECASE)


class WinRegistry:
    """One registry key under HKEY_CURRENT_USER (created on first write)."""

    def __init__(self, key: str = DEFAULT_KEY):
        self.key = key

    def get(self, name: str) -> str | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as k:
                value, kind = winreg.QueryValueEx(k, name)
                return value if kind == winreg.REG_SZ else None
        except OSError:
            return None

    def set(self, name: str, data: str) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, data)

    def delete(self, name: str) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass


def _check(exe: str) -> str:
    if not isinstance(exe, str) or not _PATH_RE.match(exe):
        raise ValueError(f"not a plain absolute exe path: {exe!r}")
    return exe


def get(exe: str, reg=None) -> str | None:
    return (reg or WinRegistry()).get(_check(exe))


def set_high(exe: str, reg=None) -> str | None:
    """Prefer the high-performance GPU for this exe. Returns the previous value (None if there was none)."""
    reg = reg or WinRegistry()
    exe = _check(exe)
    previous = reg.get(exe)
    reg.set(exe, HIGH)
    return previous


def restore(exe: str, previous: str | None, reg=None) -> None:
    reg = reg or WinRegistry()
    exe = _check(exe)
    if previous is None:
        reg.delete(exe)
    else:
        reg.set(exe, previous)


class Store:
    """Remembers what each boost replaced (on disk, so Undo still works after a restart)."""

    def __init__(self, path: Path | None = None, reg=None):
        self._path = path or Path(os.environ.get("APPDATA") or Path.home()) / "K-Optimizer" / "gpupref.json"
        self._reg = reg or WinRegistry()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [d for d in data if isinstance(d, dict) and isinstance(d.get("exe"), str)] if isinstance(data, list) else []

    def _save(self, records: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records), encoding="utf-8")
        os.replace(tmp, self._path)

    def pending(self) -> list[str]:
        return [d["exe"] for d in self._load()]

    def boost(self, exe: str) -> bool:
        """Set the high-performance preference. False if the path is not acceptable or the write is refused."""
        try:
            records = self._load()
            if any(d["exe"].lower() == exe.lower() for d in records):
                _check(exe)
                return True  # already boosted by us: keep the ORIGINAL previous value, not our own
            previous = set_high(exe, self._reg)
        except (ValueError, OSError):
            return False
        try:
            self._save(records + [{"exe": exe, "previous": previous}])
        except OSError:
            restore(exe, previous, self._reg)  # never leave a change we could not record
            return False
        return True

    def restore_all(self) -> int:
        """Put every recorded preference back; returns how many. Failures stay recorded for the next try."""
        done, keep = 0, []
        for d in self._load():
            try:
                restore(d["exe"], d.get("previous"), self._reg)
                done += 1
            except (ValueError, OSError):
                keep.append(d)
        try:
            self._save(keep)
        except OSError:
            pass
        return done
