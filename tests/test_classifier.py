import json

import pytest

from k_optimizer.classifier import KnownApps, classify, safe_targets
from k_optimizer.models import Level, ProcInfo



@pytest.fixture
def known(tmp_path):
    f = tmp_path / "builtin.json"
    f.write_text(json.dumps({"safe": ["discord.exe", "svchost.exe"]}))
    return KnownApps.load(f, None)


def proc(name, exe, pid=100):
    return ProcInfo(pid, name, exe, (), 1.0, 0.0, 0, None, None)


def test_system_dir_process_is_protected(known):
    p = proc("svchost.exe", r"C:\Windows\System32\foo.exe")
    assert classify(p, known, frozenset()) is Level.PROTECTED


def test_known_name_is_protected_even_outside_windows_dir(known):
    assert classify(proc("lsass.exe", r"D:\x\lsass.exe"), known, frozenset()) is Level.PROTECTED


def test_exe_none_is_protected(known):
    assert classify(proc("x.exe", None), known, frozenset()) is Level.PROTECTED


def test_own_pid_is_protected(known):
    assert classify(proc("discord.exe", r"D:\d.exe", pid=7), known, frozenset({7})) is Level.PROTECTED


def test_known_safe_app_is_safe(known):
    assert classify(proc("Discord.exe", r"D:\d.exe"), known, frozenset()) is Level.SAFE


def test_unknown_app_is_unknown_never_safe(known):
    assert classify(proc("random.exe", r"D:\r.exe"), known, frozenset()) is Level.UNKNOWN


def test_known_apps_ignores_corrupt_user_file(tmp_path):
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"safe": ["a.exe"]}))
    u = tmp_path / "u.json"
    u.write_text("{bozuk")
    k = KnownApps.load(b, u)
    assert k.is_safe("A.exe")


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


@pytest.mark.parametrize("exe", ["", "MemCompression"])
def test_non_absolute_or_empty_exe_is_protected(known, exe):
    assert classify(proc("MemCompression", exe), known, frozenset()) is Level.PROTECTED


def test_safe_targets_returns_only_safe_processes(known):
    procs = (
        proc("Discord.exe", r"D:\d.exe", pid=1),
        proc("random.exe", r"D:\x\random.exe", pid=2),
        proc("lsass.exe", r"D:\l.exe", pid=3),
    )
    got = safe_targets(procs, known, frozenset())
    assert [p.pid for p in got] == [1]


def test_builtin_whitelist_excludes_shared_runtimes_and_helper_processes():
    from k_optimizer.classifier import _BUILTIN

    k = KnownApps.load(_BUILTIN, None)
    for name in ("msedgewebview2.exe", "steamwebhelper.exe", "svchost.exe", "explorer.exe"):
        assert not k.is_safe(name)
