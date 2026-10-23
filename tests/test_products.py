import json
from pathlib import Path

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
    assert set(got) == {"k-optimizer", "k-launcher"}
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
