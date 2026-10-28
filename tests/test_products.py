import json
from pathlib import Path

from k_optimizer import klauncher
from k_series import products, settings


def make_exe(folder: Path, name="KLauncher.exe") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_bytes(b"MZ")
    return exe


def by_id(**kw):
    return {p.id: p for p in products.detect(**kw)}


def test_both_apps_are_reported_even_when_nothing_is_installed(tmp_path):
    got = by_id(scan_roots=[tmp_path])
    assert set(got) == {"k-optimizer", "k-launcher", "k-minigames"}
    for p in got.values():
        assert p.installed is False and p.path is None and p.version is None and p.running is False


def test_k_optimizer_is_found_next_to_k_series_and_via_a_saved_path(tmp_path):
    sibling = make_exe(tmp_path / "hub", "K-Optimizer.exe")
    got = by_id(scan_roots=[], extra_dirs=[sibling.parent])["k-optimizer"]
    assert got.installed and got.path == sibling
    other = make_exe(tmp_path / "mine", "K-Optimizer.exe")
    assert by_id(scan_roots=[], saved_optimizer=other)["k-optimizer"].path == other


def test_k_launcher_found_through_the_saved_path(tmp_path):
    exe = make_exe(tmp_path / "mine")
    kl = by_id(saved=exe, scan_roots=[])["k-launcher"]
    assert kl.installed and kl.path == exe


def test_launch_starts_the_exe_detached_in_its_own_folder(tmp_path):
    exe = make_exe(tmp_path / "app")
    calls = []
    product = products.Product("k-launcher", "K-Launcher", "", True, exe, None, False)
    assert products.launch(product, popen=lambda *a, **k: calls.append((a, k))) is True
    args, kwargs = calls[0]
    assert args[0] == [str(exe)] and kwargs["cwd"] == str(exe.parent)


def test_launch_refuses_missing_products_and_never_raises(tmp_path):
    gone = products.Product("k-optimizer", "K-Optimizer", "", False, None, None, False)
    assert products.launch(gone, popen=lambda *a, **k: 1 / 0) is False
    exe = make_exe(tmp_path / "x", "K-Optimizer.exe")
    boom = products.Product("k-optimizer", "K-Optimizer", "", True, exe, None, False)

    def fail(*a, **k):
        raise OSError("blocked")

    assert products.launch(boom, popen=fail) is False


def test_settings_roundtrip_and_tolerate_corruption(tmp_path):
    f = tmp_path / "s.json"
    assert settings.load(f) == {}
    assert settings.save({"launcher_path": "C:/x/KLauncher.exe"}, f) is True
    assert settings.load(f)["launcher_path"] == "C:/x/KLauncher.exe"
    f.write_text("{bozuk")
    assert settings.load(f) == {}
    f.write_text(json.dumps(["not", "a", "dict"]))
    assert settings.load(f) == {}


def test_saved_path_helpers(tmp_path):
    f = tmp_path / "s.json"
    assert settings.launcher_path(f) is None and settings.optimizer_path(f) is None
    settings.save({"launcher_path": "C:/a/KLauncher.exe", "optimizer_path": "C:/b/K-Optimizer.exe"}, f)
    assert settings.launcher_path(f) == Path("C:/a/KLauncher.exe")
    assert settings.optimizer_path(f) == Path("C:/b/K-Optimizer.exe")


def test_update_settings_have_safe_defaults_and_can_be_overridden(tmp_path):
    f = tmp_path / "s.json"
    assert settings.flag("auto_check", True, f) is True
    assert settings.flag("auto_install", False, f) is False
    settings.save({"auto_check": False, "auto_install": True}, f)
    assert settings.flag("auto_check", True, f) is False
    assert settings.flag("auto_install", False, f) is True
    assert settings.repo("k-launcher", f) == "ikagzy/k-launcher"
    settings.save({"repos": {"k-launcher": "someone/else"}}, f)
    assert settings.repo("k-launcher", f) == "someone/else"
    assert settings.repo("k-optimizer", f) == "ikagzy/k-series"
    assert settings.repo("k-series", f) == "ikagzy/k-series"


def test_malformed_repo_setting_falls_back_to_the_default(tmp_path):
    f = tmp_path / "s.json"
    settings.save({"repos": {"k-launcher": "../../etc", "k-series": 42}, "auto_check": "yes"}, f)
    assert settings.repo("k-launcher", f) == "ikagzy/k-launcher"
    assert settings.repo("k-series", f) == "ikagzy/k-series"
    assert settings.flag("auto_check", True, f) is True


# --- K-MiniGames ---------------------------------------------------------------------------------

def register_minigames(tmp_path, exe: Path):
    """K-MiniGames writes its own exe path to %LOCALAPPDATA%/K-MiniGames/settings.json when it starts."""
    registry = tmp_path / "_local" / "K-MiniGames" / "settings.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"exe_path": str(exe)}), encoding="utf-8")


def test_k_minigames_is_reported_even_when_not_installed(tmp_path):
    got = by_id(scan_roots=[tmp_path])["k-minigames"]
    assert (got.name, got.installed, got.path, got.version, got.running) == ("K-MiniGames", False, None, None, False)
    assert got.tagline


def test_k_minigames_is_found_through_the_path_it_registered_itself(tmp_path):
    exe = make_exe(tmp_path / "anywhere", "K-MiniGames.exe")
    register_minigames(tmp_path, exe)
    got = by_id(scan_roots=[])["k-minigames"]
    assert got.installed and got.path == exe


def test_a_registered_path_that_no_longer_exists_is_ignored_and_the_next_place_is_tried(tmp_path):
    register_minigames(tmp_path, tmp_path / "gone" / "K-MiniGames.exe")
    saved = make_exe(tmp_path / "mine", "K-MiniGames.exe")
    assert by_id(scan_roots=[], saved_minigames=saved)["k-minigames"].path == saved
    assert by_id(scan_roots=[])["k-minigames"].installed is False


def test_k_minigames_is_found_next_to_k_series_and_by_scanning(tmp_path):
    sibling = make_exe(tmp_path / "hub", "K-MiniGames.exe")
    assert by_id(scan_roots=[], extra_dirs=[sibling.parent])["k-minigames"].path == sibling
    deep = make_exe(tmp_path / "Games" / "Tools" / "K-MiniGames", "K-MiniGames.exe")
    assert by_id(scan_roots=[tmp_path / "Games"])["k-minigames"].path == deep


def test_k_minigames_is_found_in_the_programs_folder_of_the_user(tmp_path):
    exe = make_exe(tmp_path / "_local" / "Programs" / "K-MiniGames", "K-MiniGames.exe")
    assert by_id(scan_roots=[])["k-minigames"].path == exe


def test_a_running_k_minigames_is_reported_as_running(tmp_path, monkeypatch):
    exe = make_exe(tmp_path / "apps", "K-MiniGames.exe")
    register_minigames(tmp_path, exe)
    monkeypatch.setattr(klauncher, "running_minigames_exes", lambda: [exe])
    assert by_id(scan_roots=[])["k-minigames"].running is True


def test_launch_starts_k_minigames_like_the_other_products(tmp_path):
    exe = make_exe(tmp_path / "apps", "K-MiniGames.exe")
    register_minigames(tmp_path, exe)
    calls = []
    product = by_id(scan_roots=[])["k-minigames"]
    assert products.launch(product, popen=lambda *a, **k: calls.append((a, k))) is True
    assert calls[0][0][0] == [str(exe)] and calls[0][1]["cwd"] == str(exe.parent)
