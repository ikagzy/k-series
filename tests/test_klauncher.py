from pathlib import Path

from k_optimizer import klauncher, theme


def make_exe(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "KLauncher.exe"
    exe.write_bytes(b"MZ")
    return exe


def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))


def test_running_launcher_wins_over_everything_else(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    running = make_exe(tmp_path / "somewhere")
    installed = make_exe(tmp_path / "local" / "Programs" / "K-Launcher")
    got = klauncher.find_exe(saved=installed, running=lambda: [running], scan_roots=[])
    assert got == running


def test_saved_path_is_used_when_nothing_is_running(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    saved = make_exe(tmp_path / "mine")
    installed = make_exe(tmp_path / "local" / "Programs" / "K-Launcher")
    assert klauncher.find_exe(saved=saved, running=lambda: [], scan_roots=[]) == saved
    assert klauncher.find_exe(saved=tmp_path / "gone.exe", running=lambda: [], scan_roots=[]) == installed


def test_known_install_locations_are_searched_in_order(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    pf = make_exe(tmp_path / "pf" / "K-Launcher")
    assert klauncher.find_exe(running=lambda: [], scan_roots=[]) == pf
    programs = make_exe(tmp_path / "local" / "Programs" / "K-Launcher")
    assert klauncher.find_exe(running=lambda: [], scan_roots=[]) == programs


def test_scan_finds_the_newest_copy_when_not_installed(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    old = make_exe(tmp_path / "dev" / "K-Launcher" / "dist")
    new = make_exe(tmp_path / "dev" / "K-Launcher-4.0-Beta")
    import os
    os.utime(old, (1, 1))
    got = klauncher.find_exe(running=lambda: [], scan_roots=[tmp_path / "dev"])
    assert got == new


def test_nothing_found_returns_none(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    assert klauncher.find_exe(running=lambda: [], scan_roots=[tmp_path / "empty"]) is None


def test_data_dirs_prefer_the_exe_data_folder_then_legacy_locations(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    exe = tmp_path / "app" / "KLauncher.exe"
    dirs = klauncher.data_dirs(exe)
    assert dirs[0] == exe.parent / "Data"
    assert dirs[1] == tmp_path / "local" / "K-Launcher"
    assert dirs[2] == tmp_path / "roaming" / "K-Launcher"
    assert klauncher.data_dirs(None)[0] == tmp_path / "local" / "K-Launcher"


def test_file_version_reads_a_real_exe_and_survives_missing_files(tmp_path):
    import sys
    v = klauncher.file_version(Path(sys.executable))
    assert v and v[0].isdigit()
    assert klauncher.file_version(tmp_path / "nope.exe") is None
    assert klauncher.file_version(make_exe(tmp_path / "x")) is None  # no version resource


def test_theme_and_motion_come_from_the_launcher_data_folder_first(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    exe = make_exe(tmp_path / "local" / "Programs" / "K-Launcher")
    (exe.parent / "Data").mkdir()
    (exe.parent / "Data" / "theme.txt").write_text("amber-orange")
    (exe.parent / "Data" / "motion.txt").write_text("slow")
    (tmp_path / "roaming" / "K-Launcher").mkdir(parents=True)
    (tmp_path / "roaming" / "K-Launcher" / "theme.txt").write_text("aurora")
    theme.reset_launcher_cache()
    assert theme.load().id == "amber-orange"
    assert theme.motion_scale() == 1.6


def test_theme_falls_back_to_legacy_roaming_when_launcher_has_no_theme_file(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    make_exe(tmp_path / "local" / "Programs" / "K-Launcher")
    (tmp_path / "roaming" / "K-Launcher").mkdir(parents=True)
    (tmp_path / "roaming" / "K-Launcher" / "theme.txt").write_text("aurora")
    theme.reset_launcher_cache()
    assert theme.load().id == "aurora"


def test_saving_a_theme_writes_it_where_the_launcher_reads_it(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    exe = make_exe(tmp_path / "local" / "Programs" / "K-Launcher")
    theme.reset_launcher_cache()
    assert theme.save("midnight") is True
    assert (exe.parent / "Data" / "theme.txt").read_text() == "midnight"
    assert theme.load().id == "midnight"
    assert theme.save_motion("fast") is True
    assert theme.motion_scale() == 0.55


def test_saving_an_unknown_theme_or_motion_is_refused(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    make_exe(tmp_path / "local" / "Programs" / "K-Launcher")
    theme.reset_launcher_cache()
    assert theme.save("not-a-theme") is False
    assert theme.save_motion("warp") is False


# --- K-Optimizer detection (a separate app, found the same way as K-Launcher) -------------------------
def make_opt(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "K-Optimizer.exe"
    exe.write_bytes(b"MZ")
    return exe


def test_optimizer_running_copy_wins(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    running = make_opt(tmp_path / "somewhere")
    installed = make_opt(tmp_path / "local" / "Programs" / "K-Optimizer")
    got = klauncher.find_optimizer(saved=installed, running=lambda: [running], scan_roots=[])
    assert got == running


def test_optimizer_found_next_to_k_series_then_in_install_folders_then_by_scan(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    sibling = make_opt(tmp_path / "hub")
    installed = make_opt(tmp_path / "local" / "Programs" / "K-Optimizer")
    assert klauncher.find_optimizer(running=lambda: [], scan_roots=[], extra_dirs=[sibling.parent]) == sibling
    assert klauncher.find_optimizer(running=lambda: [], scan_roots=[]) == installed
    installed.unlink()
    dev = make_opt(tmp_path / "dev" / "dist")
    assert klauncher.find_optimizer(running=lambda: [], scan_roots=[tmp_path / "dev"]) == dev


def test_optimizer_saved_path_and_absence(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    saved = make_opt(tmp_path / "mine")
    assert klauncher.find_optimizer(saved=saved, running=lambda: [], scan_roots=[]) == saved
    assert klauncher.find_optimizer(saved=tmp_path / "gone.exe", running=lambda: [], scan_roots=[]) is None


def test_optimizer_scan_does_not_mistake_the_launcher_exe_for_it(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    make_exe(tmp_path / "dev")  # KLauncher.exe
    assert klauncher.find_optimizer(running=lambda: [], scan_roots=[tmp_path / "dev"]) is None


def test_default_optimizer_install_path_is_under_local_programs(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    assert klauncher.optimizer_install_path() == tmp_path / "local" / "Programs" / "K-Optimizer" / "K-Optimizer.exe"


def test_scan_prefers_the_shallower_copy_over_a_newer_one_buried_in_a_build_folder(tmp_path, monkeypatch):
    env(monkeypatch, tmp_path)
    shallow = make_opt(tmp_path / "desk")
    deep = make_opt(tmp_path / "desk" / "project" / "dist")
    import os
    os.utime(shallow, (1, 1))  # much older, still wins
    assert klauncher.find_optimizer(running=lambda: [], scan_roots=[tmp_path / "desk"]) == shallow
    assert klauncher.scan_for_exe([tmp_path / "desk"], name="K-Optimizer.exe") == [shallow, deep]


# --- finding running apps without asking the OS about every process -----------------------------------------
import os as _os  # noqa: E402
import time as _time  # noqa: E402

import psutil as _psutil  # noqa: E402

from k_optimizer import procscan  # noqa: E402


def _raw(pid, name):
    return procscan.RawProc(pid, 4, name, 1000.0, 0, 1)


def test_running_lookup_uses_the_single_call_process_table_and_asks_for_the_path_only_of_matches():
    asked = []
    scan = lambda: [_raw(10, "svchost.exe"), _raw(11, "KLauncher.exe"), _raw(12, "klauncher.exe"), _raw(13, "x.exe")]

    def exe_of(pid):
        asked.append(pid)
        return f"C:/apps/{pid}/KLauncher.exe"

    got = klauncher._running_named("KLauncher.exe", scan=scan, exe_of=exe_of)
    assert got == [Path("C:/apps/11/KLauncher.exe"), Path("C:/apps/12/KLauncher.exe")]
    assert asked == [11, 12]  # nothing was asked about the other processes


def test_running_lookup_tolerates_processes_that_vanish_or_deny_the_path_query():
    scan = lambda: [_raw(1, "KLauncher.exe"), _raw(2, "KLauncher.exe")]
    answers = {1: None, 2: "C:/a/KLauncher.exe"}
    got = klauncher._running_named("KLauncher.exe", scan=scan, exe_of=lambda pid: answers[pid])
    assert got == [Path("C:/a/KLauncher.exe")]


def test_pids_lookup_needs_no_path_queries_at_all():
    scan = lambda: [_raw(5, "K-Optimizer.exe"), _raw(6, "other.exe")]
    assert klauncher._pids_named("K-Optimizer.exe", scan=scan) == [5]


def test_if_the_native_scan_fails_the_lookups_fall_back_to_psutil():
    def broken():
        raise OSError("no ntdll")

    me = _psutil.Process(_os.getpid())
    got = klauncher._running_named(me.name(), scan=broken)
    assert Path(me.exe()) in got
    assert _os.getpid() in klauncher._pids_named(me.name(), scan=broken)


def test_the_live_lookup_finds_this_process_and_is_cheap():
    me = _psutil.Process(_os.getpid())
    _time.sleep(0)
    start = _psutil.Process().cpu_times()
    t = _time.perf_counter()
    for _ in range(5):
        found = klauncher._running_named(me.name())
    wall = (_time.perf_counter() - t) / 5
    used = _psutil.Process().cpu_times()
    cpu = ((used.user + used.system) - (start.user + start.system)) / 5
    assert Path(me.exe()) in found
    assert cpu < 0.15 and wall < 0.5, f"{cpu * 1000:.0f} ms CPU per lookup (the psutil walk cost about 1000 ms)"
