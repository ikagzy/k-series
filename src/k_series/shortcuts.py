"""A desktop shortcut whose icon follows the theme (K-Launcher does the same with its ThemeIcons)."""
import ctypes
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

_NO_WINDOW = 0x08000000
# Paths arrive through environment variables so nothing the user typed is ever pasted into the script.
_SCRIPT = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:KS_LNK); "
    "$s.TargetPath = $env:KS_TARGET; $s.WorkingDirectory = $env:KS_WORKDIR; "
    "$s.IconLocation = $env:KS_ICON; $s.Description = 'K-Series'; $s.Save()"
)


def desktop_dir() -> Path:
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:  # DESKTOPDIRECTORY
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return Path.home() / "Desktop"


def _run_powershell(script: str, env: dict[str, str]) -> bool:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                       capture_output=True, timeout=20, creationflags=_NO_WINDOW)
    return r.returncode == 0


def create(lnk: Path, target: Path, icon: Path, runner: Callable[[str, dict], bool] = _run_powershell) -> bool:
    """Create or overwrite the shortcut. False on any failure; never raises."""
    env = {**os.environ, "KS_LNK": str(lnk), "KS_TARGET": str(target), "KS_WORKDIR": str(target.parent),
           "KS_ICON": f"{icon},0"}
    try:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        return bool(runner(_SCRIPT, env))
    except (OSError, subprocess.SubprocessError):
        return False
