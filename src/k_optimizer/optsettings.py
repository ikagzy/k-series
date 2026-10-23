"""K-Optimizer's own small settings file (%APPDATA%/K-Optimizer/settings.json)."""
import json
import os
from pathlib import Path

INTERVALS = (5, 10, 30, 60)  # seconds between automatic cleans
DEFAULT_INTERVAL = 10
_DEFAULTS = {"auto_ram": False, "auto_ram_interval": DEFAULT_INTERVAL}


def default_path() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "K-Optimizer" / "settings.json"


def load(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or default_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = dict(_DEFAULTS)
    if isinstance(data.get("auto_ram"), bool):
        out["auto_ram"] = data["auto_ram"]
    t = data.get("auto_ram_interval")
    if isinstance(t, int) and not isinstance(t, bool) and t in INTERVALS:
        out["auto_ram_interval"] = t
    return out


def save(values: dict, path: Path | None = None) -> bool:
    target = path or default_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(values, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def next_interval(current: int) -> int:
    if current in INTERVALS:
        return INTERVALS[(INTERVALS.index(current) + 1) % len(INTERVALS)]
    return DEFAULT_INTERVAL
