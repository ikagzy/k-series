import json
from pathlib import Path

from k_series import products, settings


def make_exe(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "KLauncher.exe"
    exe.write_bytes(b"MZ")
    return exe


def test_k_optimizer_is_always_present_as_a_builtin_module(tmp_path):
    got = {p.id: p for p in products.detect(saved=None, scan_roots=[tmp_path])}
    opt = got["k-optimizer"]
    assert opt.installed and opt.builtin and opt.running and opt.version


def test_missing_k_launcher_is_a_state_not_an_error(tmp_path):
    got = {p.id: p for p in products.detect(saved=None, scan_roots=[tmp_path])}
    kl = got["k-launcher"]
    assert kl.installed is False and kl.path is None and kl.version is None and kl.running is False


def test_k_launcher_found_through_the_saved_path(tmp_path):
    exe = make_exe(tmp_path / "mine")
    kl = {p.id: p for p in products.detect(saved=exe, scan_roots=[])}["k-launcher"]
    assert kl.installed and kl.path == exe and kl.builtin is False


def test_launch_starts_the_exe_detached_in_its_own_folder(tmp_path):
    exe = make_exe(tmp_path / "app")
    calls = []
    product = products.Product("k-launcher", "K-Launcher", "", True, False, exe, None, False)
    assert products.launch(product, popen=lambda *a, **k: calls.append((a, k))) is True
    args, kwargs = calls[0]
    assert args[0] == [str(exe)] and kwargs["cwd"] == str(exe.parent)


def test_launch_refuses_missing_or_builtin_products_without_raising(tmp_path):
    gone = products.Product("k-launcher", "K-Launcher", "", False, False, None, None, False)
    builtin = products.Product("k-optimizer", "K-Optimizer", "", True, True, None, "0.1.0", True)
    assert products.launch(gone, popen=lambda *a, **k: 1 / 0) is False
    assert products.launch(builtin, popen=lambda *a, **k: 1 / 0) is False
    exe = make_exe(tmp_path / "x")
    boom = products.Product("k-launcher", "K-Launcher", "", True, False, exe, None, False)

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


def test_saved_launcher_path_helper(tmp_path):
    f = tmp_path / "s.json"
    assert settings.launcher_path(f) is None
    exe = make_exe(tmp_path / "k")
    settings.save({"launcher_path": str(exe)}, f)
    assert settings.launcher_path(f) == exe
