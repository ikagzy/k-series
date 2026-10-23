import hashlib
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from k_series import updater

DATA = b"MZ" + b"payload" * 1000
SHA = hashlib.sha256(DATA).hexdigest()


class Resp(io.BytesIO):
    def __init__(self, body: bytes, url: str = "https://example.invalid/x"):
        super().__init__(body)
        self._url = url
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self._url


def release_json(tag="v4.1.0", assets=None, **extra):
    return json.dumps({
        "tag_name": tag, "draft": False, "prerelease": False, "body": "Yeni özellikler",
        "html_url": "https://github.com/ikagzy/k-launcher/releases/tag/" + tag,
        "assets": assets if assets is not None else [
            {"name": "KLauncher.exe", "size": len(DATA), "digest": "sha256:" + SHA,
             "browser_download_url": "https://github.com/ikagzy/k-launcher/releases/download/v4.1.0/KLauncher.exe"},
            {"name": "notes.txt", "size": 5, "browser_download_url": "https://github.com/x/notes.txt"},
        ], **extra}).encode()


def opener_for(routes):
    def opener(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        for prefix, result in routes.items():
            if url.startswith(prefix):
                if isinstance(result, Exception):
                    raise result
                return Resp(result, url)
        raise AssertionError(f"unexpected request: {url}")
    return opener


API = "https://api.github.com/repos/ikagzy/k-launcher/releases/latest"


# --- versions -------------------------------------------------------------------
def test_parse_version_accepts_tags_and_file_versions():
    assert updater.parse_version("v4.1.0") == (4, 1, 0)
    assert updater.parse_version("4.0.0.0") == (4, 0, 0, 0)
    assert updater.parse_version("K-Launcher 4.2") == (4, 2)
    assert updater.parse_version("nightly") is None
    assert updater.parse_version(None) is None


def test_is_newer_pads_and_compares_numerically():
    assert updater.is_newer((4, 1, 0), (4, 0, 0, 0))
    assert not updater.is_newer((4, 0, 0), (4, 0, 0, 0))
    assert not updater.is_newer((3, 9), (4, 0))
    assert updater.is_newer((4, 10), (4, 9))  # 10 > 9, not a string comparison
    assert updater.is_newer((4, 0, 1), (4, 0))


# --- fetching ---------------------------------------------------------------------
def test_fetch_latest_picks_the_matching_asset_and_reads_the_digest():
    rel = updater.fetch_latest("ikagzy/k-launcher", r"^KLauncher.*\.exe$", opener_for({API: release_json()}))
    assert rel.version == (4, 1, 0) and rel.asset_name == "KLauncher.exe"
    assert rel.sha256 == SHA and rel.size == len(DATA) and "Yeni" in rel.notes


def test_fetch_latest_reads_a_sibling_sha256_file_when_there_is_no_digest():
    assets = [
        {"name": "KLauncher.exe", "size": 9, "browser_download_url": "https://github.com/o/r/releases/download/v1/KLauncher.exe"},
        {"name": "KLauncher.exe.sha256", "size": 90, "browser_download_url": "https://github.com/o/r/releases/download/v1/KLauncher.exe.sha256"},
    ]
    routes = {API: release_json(assets=assets),
              "https://github.com/o/r/releases/download/v1/KLauncher.exe.sha256": (SHA + "  KLauncher.exe\n").encode()}
    rel = updater.fetch_latest("ikagzy/k-launcher", r"^KLauncher.*\.exe$", opener_for(routes))
    assert rel.sha256 == SHA


def test_fetch_latest_without_any_checksum_keeps_sha256_empty():
    assets = [{"name": "KLauncher.exe", "size": 9, "browser_download_url": "https://github.com/o/r/KLauncher.exe"}]
    rel = updater.fetch_latest("ikagzy/k-launcher", r"^KLauncher.*\.exe$", opener_for({API: release_json(assets=assets)}))
    assert rel.sha256 is None


def test_no_release_yet_is_not_an_error():
    err = HTTPError(API, 404, "Not Found", {}, None)
    assert updater.fetch_latest("ikagzy/k-launcher", r"^KLauncher.*\.exe$", opener_for({API: err})) is None


def test_release_without_a_matching_asset_or_version_is_ignored():
    assert updater.fetch_latest("ikagzy/k-launcher", r"^KLauncher.*\.exe$",
                                opener_for({API: release_json(assets=[])})) is None
    assert updater.fetch_latest("ikagzy/k-launcher", r"^KLauncher.*\.exe$",
                                opener_for({API: release_json(tag="nightly")})) is None


def test_rate_limit_and_network_failures_become_readable_errors():
    for exc, word in ((HTTPError(API, 403, "rate limit", {}, None), "sınır"),
                      (HTTPError(API, 500, "boom", {}, None), "500"),
                      (URLError("offline"), "ulaşılamadı"),
                      (TimeoutError(), "ulaşılamadı")):
        with pytest.raises(updater.UpdateError) as e:
            updater.fetch_latest("ikagzy/k-launcher", r"^KLauncher.*\.exe$", opener_for({API: exc}))
        assert word in str(e.value)


def test_a_malformed_repo_name_is_rejected_before_any_request():
    for bad in ("../etc/passwd", "a b/c", "owner", "", "owner/repo/extra", "o/r?x=1",
                "../evil", "./x", "a/..", "a/.", "-a/b", "a/b#frag", "a/b%2e", "x" * 50 + "/r"):
        with pytest.raises(updater.UpdateError):
            updater.fetch_latest(bad, r".*", lambda *a, **k: 1 / 0)


# --- downloading ----------------------------------------------------------------------
def make_release(url="https://github.com/ikagzy/k-launcher/releases/download/v4.1.0/KLauncher.exe", sha=SHA):
    return updater.Release("v4.1.0", (4, 1, 0), "KLauncher.exe", url, len(DATA), sha, "", "")


def test_download_streams_verifies_and_reports_progress(tmp_path):
    rel = make_release()
    seen = []
    path = updater.download(rel, tmp_path, opener_for({rel.url: DATA}), progress=lambda d, t: seen.append((d, t)))
    assert path == tmp_path / "KLauncher.exe" and path.read_bytes() == DATA
    assert seen and seen[-1][0] == len(DATA)
    assert not list(tmp_path.glob("*.part"))


def test_download_refuses_when_no_checksum_is_available(tmp_path):
    rel = make_release(sha=None)
    with pytest.raises(updater.UpdateError, match="karma"):
        updater.download(rel, tmp_path, lambda *a, **k: 1 / 0)
    assert not list(tmp_path.iterdir())


def test_download_deletes_the_file_when_the_checksum_does_not_match(tmp_path):
    rel = make_release(sha="0" * 64)
    with pytest.raises(updater.UpdateError, match="uyuşmuyor"):
        updater.download(rel, tmp_path, opener_for({rel.url: DATA}))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("url", [
    "http://github.com/o/r/KLauncher.exe",              # not https
    "https://evil.example.com/KLauncher.exe",           # not a GitHub host
    "https://github.com.evil.com/KLauncher.exe",        # look-alike host
    "https://evilgithubusercontent.com/KLauncher.exe",  # look-alike suffix
    "file:///C:/Windows/system32/cmd.exe",
])
def test_download_refuses_non_github_or_non_https_urls(tmp_path, url):
    with pytest.raises(updater.UpdateError, match="güvenli"):
        updater.download(make_release(url=url), tmp_path, lambda *a, **k: 1 / 0)


def test_download_accepts_github_cdn_hosts_and_rejects_redirects_elsewhere(tmp_path):
    good = "https://release-assets.githubusercontent.com/x/KLauncher.exe"
    rel = make_release(url=good)
    assert updater.download(rel, tmp_path, opener_for({good: DATA})).exists()

    start = "https://github.com/o/r/releases/download/v1/KLauncher.exe"

    def redirecting(request, timeout=None):
        return Resp(DATA, "https://evil.example.com/KLauncher.exe")

    with pytest.raises(updater.UpdateError, match="güvenli"):
        updater.download(make_release(url=start), tmp_path / "b", redirecting)


def test_download_file_name_cannot_escape_the_target_folder(tmp_path):
    rel = updater.Release("v1", (1,), "..\\..\\evil.exe", "https://github.com/o/r/x.exe", 1, SHA, "", "")
    path = updater.download(rel, tmp_path / "d", opener_for({"https://github.com/o/r/x.exe": DATA}))
    assert path.parent == tmp_path / "d"


# --- installing K-Launcher -----------------------------------------------------------------
def test_install_launcher_asks_it_to_close_politely_then_runs_the_new_exe(tmp_path):
    exe = tmp_path / "KLauncher.exe"
    exe.write_bytes(b"x")
    state = {"pids": [11]}
    log = []

    def close(pids):
        log.append(("close", list(pids)))
        state["pids"] = []  # it exits on request

    updater.install_launcher(exe, running_pids=lambda: state["pids"], request_close=close,
                             run=lambda *a, **k: log.append(("run", a[0])), sleep=lambda s: None)
    assert log == [("close", [11]), ("run", [str(exe)])]


def test_install_launcher_never_force_kills_and_reports_when_it_will_not_close(tmp_path):
    exe = tmp_path / "KLauncher.exe"
    exe.write_bytes(b"x")
    ran = []
    with pytest.raises(updater.UpdateError, match="kapat"):
        updater.install_launcher(exe, running_pids=lambda: [11], request_close=lambda pids: None,
                                 run=lambda *a, **k: ran.append(1), sleep=lambda s: None, wait_s=0.2)
    assert ran == []


def test_install_launcher_runs_directly_when_it_is_not_running(tmp_path):
    exe = tmp_path / "KLauncher.exe"
    exe.write_bytes(b"x")
    ran = []
    updater.install_launcher(exe, running_pids=lambda: [], request_close=lambda p: 1 / 0,
                             run=lambda *a, **k: ran.append(a[0]), sleep=lambda s: None)
    assert ran == [[str(exe)]]


def test_install_launcher_reports_a_start_failure(tmp_path):
    exe = tmp_path / "KLauncher.exe"
    exe.write_bytes(b"x")

    def boom(*a, **k):
        raise OSError("blocked")

    with pytest.raises(updater.UpdateError, match="başlatılamadı"):
        updater.install_launcher(exe, running_pids=lambda: [], request_close=lambda p: None, run=boom,
                                 sleep=lambda s: None)


# --- installing K-Series itself --------------------------------------------------------------
def test_install_self_swaps_the_running_exe_and_starts_the_new_one(tmp_path):
    cur, new = tmp_path / "K-Series.exe", tmp_path / "dl" / "K-Series.exe"
    new.parent.mkdir()
    cur.write_bytes(b"old")
    new.write_bytes(b"new")
    started = []
    updater.install_self(new, cur, run=lambda *a, **k: started.append(a[0]))
    assert cur.read_bytes() == b"new" and (tmp_path / "K-Series.exe.old").read_bytes() == b"old"
    assert started == [[str(cur)]] and not new.exists()


def test_install_self_rolls_back_when_the_swap_fails(tmp_path, monkeypatch):
    cur, new = tmp_path / "K-Series.exe", tmp_path / "K-Series.new"
    cur.write_bytes(b"old")
    new.write_bytes(b"new")

    def broken_move(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(updater.shutil, "move", broken_move)
    with pytest.raises(updater.UpdateError):
        updater.install_self(new, cur, run=lambda *a, **k: 1 / 0)
    assert cur.read_bytes() == b"old"  # the working copy is back
    assert new.exists()


def test_install_self_does_not_start_anything_if_the_exe_cannot_be_renamed(tmp_path, monkeypatch):
    cur, new = tmp_path / "K-Series.exe", tmp_path / "K-Series.new"
    cur.write_bytes(b"old")
    new.write_bytes(b"new")
    monkeypatch.setattr(updater.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    with pytest.raises(updater.UpdateError):
        updater.install_self(new, cur, run=lambda *a, **k: 1 / 0)
    assert cur.read_bytes() == b"old"


def test_cleanup_old_removes_the_previous_copy_and_tolerates_absence(tmp_path):
    cur = tmp_path / "K-Series.exe"
    updater.cleanup_old(cur)
    (tmp_path / "K-Series.exe.old").write_bytes(b"old")
    updater.cleanup_old(cur)
    assert not (tmp_path / "K-Series.exe.old").exists()


# --- checking everything -----------------------------------------------------------------------
def test_check_reports_available_current_none_and_error():
    routes = {API: release_json(tag="v4.1.0")}
    opener = opener_for(routes)
    avail = updater.check("k-launcher", "ikagzy/k-launcher", "4.0.0.0", opener)
    assert avail.state == "available" and avail.release.version == (4, 1, 0)
    assert updater.check("k-launcher", "ikagzy/k-launcher", "4.1.0.0", opener).state == "current"
    assert updater.check("k-launcher", "ikagzy/k-launcher", None, opener).state == "available"
    none = opener_for({API: HTTPError(API, 404, "x", {}, None)})
    assert updater.check("k-launcher", "ikagzy/k-launcher", "4.0.0.0", none).state == "none"
    err = opener_for({API: URLError("offline")})
    bad = updater.check("k-launcher", "ikagzy/k-launcher", "4.0.0.0", err)
    assert bad.state == "error" and "ulaşılamadı" in bad.message


def test_default_repos_and_asset_patterns_cover_both_products():
    assert updater.DEFAULT_REPOS["k-launcher"] == "ikagzy/k-launcher"
    assert set(updater.DEFAULT_REPOS) == set(updater.ASSET_PATTERNS) == {"k-launcher", "k-series"}
