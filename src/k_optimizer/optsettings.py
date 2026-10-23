"""K-Optimizer's own small settings file (%APPDATA%/K-Optimizer/settings.json)."""
import json
import os
from pathlib import Path

THRESHOLDS = (70, 80, 90)
_DEFAULTS = {"auto_ram": False, "auto_ram_threshold": 80}


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
    t = data.get("auto_ram_threshold")
    if isinstance(t, int) and not isinstance(t, bool) and 60 <= t <= 95:
        out["auto_ram_threshold"] = t
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


def next_threshold(current: int) -> int:
    if current in THRESHOLDS:
        return THRESHOLDS[(THRESHOLDS.index(current) + 1) % len(THRESHOLDS)]
    return THRESHOLDS[0]
