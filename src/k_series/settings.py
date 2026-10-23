"""K-Series' own small settings file (%APPDATA%/K-Series/settings.json). Theme and motion are not stored
here: they live in K-Launcher's folder so both apps share them."""
import json
import os
from pathlib import Path


def default_path() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "K-Series" / "settings.json"


def load(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or default_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict, path: Path | None = None) -> bool:
    target = path or default_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def launcher_path(path: Path | None = None) -> Path | None:
    value = load(path).get("launcher_path")
    return Path(value) if isinstance(value, str) and value else None
