import json

import pytest

from k_optimizer.classifier import KnownApps, classify, safe_targets, _BUILTIN
from k_optimizer.models import Level, ProcInfo

BS = chr(92)
SYS = "C:" + BS + "Windows" + BS + "System32" + BS
WINAPPS = "C:" + BS + "Program Files" + BS + "WindowsApps" + BS + "MicrosoftWindows.Client_1" + BS


@pytest.fixture
def known(tmp_path):
    f = tmp_path / "builtin.json"
    f.write_text(json.dumps({"safe": ["compattelrunner.exe", "widgets.exe", "discord.exe"]}))
    return KnownApps.load(f, None)


def proc(name, exe, pid=100, cpu=0.0, rss=100 * 1024 * 1024, gpu=None, vram=None):
    return ProcInfo(pid, name, exe, (), 1.0, cpu, rss, gpu, vram)


def test_listed_windows_component_in_windows_dir_is_safe(known):
    assert classify(proc("CompatTelRunner.exe", SYS + "CompatTelRunner.exe"), known, frozenset()) is Level.SAFE


def test_listed_windows_component_in_windowsapps_is_safe(known):
    assert classify(proc("Widgets.exe", WINAPPS + "Widgets.exe"), known, frozenset()) is Level.SAFE


def test_user_app_is_never_safe_even_if_name_is_listed(known):
    p = proc("Discord.exe", "C:" + BS + "Users" + BS + "x" + BS + "Discord" + BS + "Discord.exe")
    assert classify(p, known, frozenset()) is Level.UNKNOWN


def test_impostor_with_windows_component_name_elsewhere_is_not_safe(known):
    p = proc("CompatTelRunner.exe", "D:" + BS + "tmp" + BS + "CompatTelRunner.exe")
    assert classify(p, known, frozenset()) is Level.UNKNOWN


def test_unlisted_windows_dir_process_is_protected(known):
    assert classify(proc("foo.exe", SYS + "foo.exe"), known, frozenset()) is Level.PROTECTED


def test_known_protected_name_wins_even_if_listed_safe(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"safe": ["lsass.exe"]}))
    k = KnownApps.load(f, None)
    assert classify(proc("lsass.exe", SYS + "lsass.exe"), k, frozenset()) is Level.PROTECTED


@pytest.mark.parametrize("exe", [None, "", "MemCompression"])
def test_missing_or_non_absolute_exe_is_protected(known, exe):
    assert classify(proc("MemCompression", exe), known, frozenset()) is Level.PROTECTED


def test_own_pid_is_protected(known):
    p = proc("CompatTelRunner.exe", SYS + "CompatTelRunner.exe", pid=7)
    assert classify(p, known, frozenset({7})) is Level.PROTECTED


def test_unknown_app_is_unknown_never_safe(known):
    assert classify(proc("random.exe", "D:" + BS + "r.exe"), known, frozenset()) is Level.UNKNOWN


def test_known_apps_ignores_corrupt_user_file(tmp_path):
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"safe": ["a.exe"]}))
    u = tmp_path / "u.json"
    u.write_text("{bozuk")
    assert KnownApps.load(b, u).is_safe("A.exe")


def test_known_apps_user_file_adds_names(tmp_path):
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"safe": ["a.exe"]}))
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"safe": ["Mine.exe"]}))
    k = KnownApps.load(b, u)
    assert k.is_safe("mine.exe") and k.is_safe("a.exe")


def test_corrupt_builtin_raises(tmp_path):
    b = tmp_path / "b.json"
    b.write_text("nope")
    with pytest.raises(ValueError):
        KnownApps.load(b, None)


def test_builtin_list_is_windows_components_only():
    k = KnownApps.load(_BUILTIN, None)
    assert k.is_safe("compattelrunner.exe")
    for name in ("discord.exe", "epicgameslauncher.exe", "steam.exe", "spotify.exe",
                 "msedgewebview2.exe", "steamwebhelper.exe", "svchost.exe", "explorer.exe"):
        assert not k.is_safe(name)


def test_safe_targets_returns_only_safe_processes(known):
    procs = (
        proc("CompatTelRunner.exe", SYS + "CompatTelRunner.exe", pid=1),
        proc("Discord.exe", "C:" + BS + "Users" + BS + "d.exe", pid=2),
        proc("lsass.exe", SYS + "lsass.exe", pid=3),
    )
    assert [p.pid for p in safe_targets(procs, known, frozenset())] == [1]


def test_safe_targets_resource_filters(known):
    mb = 1024 * 1024
    path = SYS + "CompatTelRunner.exe"
    idle = proc("CompatTelRunner.exe", path, pid=1)
    busy_cpu = proc("CompatTelRunner.exe", path, pid=2, cpu=3.0)
    busy_gpu = proc("CompatTelRunner.exe", path, pid=3, gpu=5.0)
    big_vram = proc("CompatTelRunner.exe", path, pid=4, gpu=0.0, vram=200 * mb)
    no_gpu_data = proc("CompatTelRunner.exe", path, pid=5)
    allp = [idle, busy_cpu, busy_gpu, big_vram, no_gpu_data]
    assert safe_targets(allp, known, frozenset(), resource="ram") == allp
    assert safe_targets(allp, known, frozenset(), resource="cpu") == [busy_cpu]
    assert safe_targets(allp, known, frozenset(), resource="gpu") == [busy_gpu, big_vram]
