"""K-Series' own small settings file (%APPDATA%/K-Series/settings.json). Theme and motion are not stored
here: they live in K-Launcher's folder so both apps share them."""
import json
import os
import re
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


DEFAULT_REPOS = {"k-launcher": "ikagzy/k-launcher", "k-optimizer": "ikagzy/k-series",
                 "k-series": "ikagzy/k-series"}
# GitHub owner: letters, digits and single hyphens, never starting with one. Repo: letters, digits, _ . -
# but never "." or ".." (which would turn the API URL into a path traversal).
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}$")


def flag(name: str, default: bool, path: Path | None = None) -> bool:
    value = load(path).get(name)
    return value if isinstance(value, bool) else default


def repo(product_id: str, path: Path | None = None) -> str:
    """The GitHub repository to take a product's updates from; the default when unset or malformed."""
    repos = load(path).get("repos")
    value = repos.get(product_id) if isinstance(repos, dict) else None
    return value if isinstance(value, str) and REPO_RE.match(value) else DEFAULT_REPOS[product_id]


def optimizer_path(path: Path | None = None) -> Path | None:
    value = load(path).get("optimizer_path")
    return Path(value) if isinstance(value, str) and value else None
