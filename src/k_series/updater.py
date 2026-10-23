"""Updates from GitHub Releases for K-Launcher and K-Series (which contains K-Optimizer).

The author pushes the source to GitHub and tags a version; a GitHub Actions workflow builds the exe and
publishes it as a release asset. This module finds that release, downloads the asset, verifies its SHA-256
and installs it. Nothing is installed without a verified checksum, and nothing is fetched from outside GitHub.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from k_optimizer import klauncher

from k_series.settings import DEFAULT_REPOS, REPO_RE  # noqa: E402  (re-exported)

ASSET_PATTERNS = {"k-launcher": r"^KLauncher.*\.exe$", "k-optimizer": r"^K-Optimizer.*\.exe$",
                  "k-series": r"^K-Series.*\.exe$"}

_REPO_RE = REPO_RE
_SHA_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")
_NO_WINDOW = 0x08000000
_CHUNK = 256 * 1024


class UpdateError(Exception):
    """An update problem the user should be told about in plain words."""


@dataclass(frozen=True)
class Release:
    tag: str
    version: tuple[int, ...]
    asset_name: str
    url: str
    size: int
    sha256: str | None
    notes: str
    page: str


@dataclass(frozen=True)
class Status:
    state: str  # "current" | "available" | "none" | "error"
    release: Release | None = None
    message: str = ""


# --- versions ---------------------------------------------------------------------------
def parse_version(text: str | None) -> tuple[int, ...] | None:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4]) if nums else None


def is_newer(remote: tuple[int, ...], local: tuple[int, ...]) -> bool:
    n = max(len(remote), len(local))
    return tuple(remote) + (0,) * (n - len(remote)) > tuple(local) + (0,) * (n - len(local))


# --- GitHub -------------------------------------------------------------------------------
def _allowed_host(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == "github.com" or host.endswith(".githubusercontent.com")
                                   or host == "githubusercontent.com")


def _get(url: str, opener, timeout: float, accept: str = "*/*"):
    request = Request(url, headers={"User-Agent": "K-Series-Updater", "Accept": accept})
    return opener(request, timeout=timeout)


def fetch_latest(repo: str, asset_pattern: str, opener=None, timeout: float = 10) -> Release | None:
    """The newest published release of `repo` with a matching asset, or None when there is none yet."""
    if not _REPO_RE.match(repo or ""):
        raise UpdateError(f"Geçersiz GitHub deposu: {repo!r} (sahip/depo biçiminde olmalı)")
    opener = opener or urlopen  # looked up at call time, so tests can cut the network off in one place
    try:
        with _get(f"https://api.github.com/repos/{repo}/releases/latest", opener, timeout,
                  "application/vnd.github+json") as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 404:
            return None
        if e.code in (403, 429):
            raise UpdateError("GitHub istek sınırına takıldı, biraz sonra yeniden dene.") from e
        raise UpdateError(f"GitHub yanıtı alınamadı ({e.code}).") from e
    except (URLError, OSError, TimeoutError, ValueError) as e:
        raise UpdateError("İnternete ulaşılamadı veya GitHub yanıt vermedi.") from e
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = parse_version(str(data.get("tag_name", "")))
    pattern = re.compile(asset_pattern, re.IGNORECASE)
    assets = [a for a in data.get("assets", []) if isinstance(a, dict)]
    asset = next((a for a in assets if pattern.match(str(a.get("name", "")))), None)
    if version is None or asset is None or not asset.get("browser_download_url"):
        return None
    return Release(
        tag=str(data["tag_name"]), version=version, asset_name=str(asset["name"]),
        url=str(asset["browser_download_url"]), size=int(asset.get("size") or 0),
        sha256=_checksum(asset, assets, opener, timeout), notes=str(data.get("body") or "")[:600],
        page=str(data.get("html_url") or ""),
    )


def _checksum(asset: dict, assets: list[dict], opener, timeout: float) -> str | None:
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:") and _SHA_RE.fullmatch(digest[7:]):
        return digest[7:].lower()
    sibling = next((a for a in assets if a.get("name") == f"{asset['name']}.sha256"), None)
    if sibling and _allowed_host(str(sibling.get("browser_download_url", ""))):
        try:
            with _get(sibling["browser_download_url"], opener, timeout) as resp:
                found = _SHA_RE.search(resp.read(4096).decode("utf-8", "replace"))
            return found.group(0).lower() if found else None
        except (URLError, OSError, TimeoutError, ValueError):
            return None
    return None


def check(product_id: str, repo: str, local_version: str | None, opener=None) -> Status:
    try:
        rel = fetch_latest(repo, ASSET_PATTERNS[product_id], opener)
    except UpdateError as e:
        return Status("error", message=str(e))
    if rel is None:
        return Status("none", message="Henüz yayınlanmış sürüm yok.")
    local = parse_version(local_version)
    if local is None or is_newer(rel.version, local):
        return Status("available", rel)
    return Status("current", rel)


# --- downloading ------------------------------------------------------------------------------
def download(release: Release, dest_dir: Path, opener=None,
             progress: Callable[[int, int], None] | None = None, timeout: float = 30) -> Path:
    """Download the asset into dest_dir. The SHA-256 must be known and must match, else nothing is kept."""
    if not _allowed_host(release.url):
        raise UpdateError("İndirme adresi güvenli değil (yalnızca https GitHub adresleri kabul edilir).")
    if not release.sha256:
        raise UpdateError("Bu sürümün SHA-256 doğrulama karması yok; güvenlik için kurulmadı.")
    opener = opener or urlopen
    name = Path(release.asset_name.replace("\\", "/")).name
    dest_dir.mkdir(parents=True, exist_ok=True)
    final, part = dest_dir / name, dest_dir / (name + ".part")
    sha = hashlib.sha256()
    try:
        with _get(release.url, opener, timeout) as resp:
            final_url = getattr(resp, "geturl", lambda: release.url)()
            if not _allowed_host(final_url):
                raise UpdateError("İndirme güvenli olmayan bir adrese yönlendirildi; durduruldu.")
            total = int(resp.headers.get("Content-Length") or release.size or 0)
            done = 0
            with open(part, "wb") as out:
                while chunk := resp.read(_CHUNK):
                    out.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (URLError, OSError, TimeoutError) as e:
        part.unlink(missing_ok=True)
        raise UpdateError("İndirme tamamlanamadı (bağlantı veya disk hatası).") from e
    if sha.hexdigest().lower() != release.sha256.lower():
        part.unlink(missing_ok=True)
        raise UpdateError("İndirilen dosyanın SHA-256 karması uyuşmuyor; dosya silindi, kurulmadı.")
    os.replace(part, final)
    return final


# --- installing ---------------------------------------------------------------------------------
def _polite_close(pids: list[int]) -> None:
    """Ask K-Launcher's windows to close (taskkill without /F); the app saves its state and exits itself."""
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, creationflags=_NO_WINDOW)


def _spawn(argv, **kwargs):
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(argv, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def install_launcher(new_exe: Path, running_pids=None, request_close=_polite_close,
                     run=_spawn, sleep=time.sleep, wait_s: float = 12.0) -> None:
    """K-Launcher updates itself: the single-file release installs into %LOCALAPPDATA%/Programs/K-Launcher
    (refusing while the installed copy runs), relaunches and removes the portable copy. So: close the running
    one politely, then run the new exe. Never force-kills."""
    running_pids = running_pids or klauncher.running_pids  # looked up at call time so tests can replace it
    pids = running_pids()
    if pids:
        request_close(pids)
        waited = 0.0
        while running_pids() and waited < wait_s:
            sleep(0.25)
            waited += 0.25
        if running_pids():
            raise UpdateError("K-Launcher kapanmadı. Çalışmanı kaydedip kapat, sonra güncellemeyi yeniden dene.")
    try:
        run([str(new_exe)], cwd=str(new_exe.parent))
    except OSError as e:
        raise UpdateError("Yeni K-Launcher başlatılamadı.") from e


def install_exe(new_exe: Path, target: Path, running_pids=None, request_close=_polite_close,
                run=_spawn, sleep=time.sleep, wait_s: float = 12.0) -> None:
    """Install or update a standalone exe (K-Optimizer) at `target`.

    A running copy is asked to close politely (never force-killed); the old file is kept as `.old`, the new one
    moved into place, and the app is started again only if it was running. Failures leave the old copy working."""
    running_pids = running_pids or klauncher.running_optimizer_pids  # looked up at call time (tests replace it)
    pids = running_pids()
    was_running = bool(pids)
    if pids:
        request_close(pids)
        waited = 0.0
        while running_pids() and waited < wait_s:
            sleep(0.25)
            waited += 0.25
        if running_pids():
            raise UpdateError("K-Optimizer kapanmadı. İşini kaydedip kapat, sonra güncellemeyi yeniden dene.")
    old = target.with_name(target.name + ".old")
    had_old_target = target.exists()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if had_old_target:
            old.unlink(missing_ok=True)
            os.replace(target, old)
    except OSError as e:
        raise UpdateError("Mevcut K-Optimizer dosyası değiştirilemedi.") from e
    try:
        shutil.move(str(new_exe), str(target))
    except OSError as e:
        if had_old_target:
            try:
                os.replace(old, target)  # put the working copy back
            except OSError:
                pass
        raise UpdateError("Yeni sürüm yerine konamadı; eski sürüm korundu.") from e
    if was_running:
        try:
            run([str(target)], cwd=str(target.parent))
        except OSError as e:
            raise UpdateError("K-Optimizer güncellendi ama yeniden başlatılamadı; elle aç.") from e


def install_self(new_exe: Path, current_exe: Path, run=_spawn) -> None:
    """Swap the running exe: Windows allows renaming a running file, so current -> .old, new -> current."""
    old = current_exe.with_name(current_exe.name + ".old")
    try:
        old.unlink(missing_ok=True)
        os.replace(current_exe, old)
    except OSError as e:
        raise UpdateError("Çalışan K-Series dosyası değiştirilemedi.") from e
    try:
        shutil.move(str(new_exe), str(current_exe))
    except OSError as e:
        try:
            os.replace(old, current_exe)  # put the working copy back
        except OSError:
            pass
        raise UpdateError("Yeni sürüm yerine konamadı; eski sürüm korundu.") from e
    try:
        run([str(current_exe)], cwd=str(current_exe.parent))
    except OSError as e:
        raise UpdateError("Yeni K-Series başlatılamadı; kapatıp elle aç.") from e


def cleanup_old(current_exe: Path) -> None:
    try:
        current_exe.with_name(current_exe.name + ".old").unlink(missing_ok=True)
    except OSError:
        pass
