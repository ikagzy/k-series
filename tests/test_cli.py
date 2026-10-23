import json

from k_optimizer import cli
from k_optimizer.cleaner import CloseReport, RestoreReport
from k_optimizer.models import ProcInfo, Snapshot

BS = chr(92)


def mk(pid, name, exe, rss=50 * 1024 * 1024):
    return ProcInfo(pid, name, exe, (exe,), 1.0, 1.5, rss, None, None)


SNAP = Snapshot(
    10.0, 1, 2, (),
    (
        mk(1, "lsass.exe", "C:" + BS + "Windows" + BS + "System32" + BS + "lsass.exe"),
        mk(2, "CompatTelRunner.exe", "C:" + BS + "Windows" + BS + "System32" + BS + "CompatTelRunner.exe"),
        mk(3, "random.exe", "D:" + BS + "r" + BS + "random.exe"),
    ),
)


class FakeCleaner:
    def __init__(self):
        self.closed = None

    def close(self, procs):
        self.closed = [p.pid for p in procs]
        return CloseReport(tuple(procs), ())

    def restore(self):
        return RestoreReport(("a.exe",), ())


def run(argv, cleaner=None, tmp_path=None, trim=lambda pids: 0, safe=("compattelrunner.exe",)):
    known = tmp_path / "k.json"
    known.write_text(json.dumps({"safe": list(safe)}))
    return cli.main(argv, snapshot_fn=lambda: SNAP, cleaner=cleaner or FakeCleaner(),
                    known_path=known, trim_fn=trim)


def test_scan_never_prints_protected_processes(capsys, tmp_path):
    assert run(["scan"], tmp_path=tmp_path) == 0
    out = capsys.readouterr().out
    assert "lsass.exe" not in out
    assert "CompatTelRunner.exe" in out and "safe" in out
    assert "random.exe" in out and "unknown" in out


def test_close_without_yes_aborts_on_negative_answer(monkeypatch, tmp_path):
    c = FakeCleaner()
    monkeypatch.setattr("builtins.input", lambda *_: "h")
    assert run(["close", "--pids", "2"], c, tmp_path) == 1
    assert c.closed is None


def test_close_with_yes_calls_cleaner_for_selected_pids_only(tmp_path):
    c = FakeCleaner()
    assert run(["close", "--pids", "2", "--yes"], c, tmp_path) == 0
    assert c.closed == [2]


def test_close_unknown_pid_is_reported_not_crashing(capsys, tmp_path):
    c = FakeCleaner()
    assert run(["close", "--pids", "999", "--yes"], c, tmp_path) == 1
    assert "999" in capsys.readouterr().out
    assert c.closed is None


def test_close_protected_pid_is_not_offered_to_cleaner(tmp_path):
    c = FakeCleaner()
    assert run(["close", "--pids", "1", "--yes"], c, tmp_path) == 1
    assert c.closed is None


def test_restore_prints_summary(capsys, tmp_path):
    assert run(["restore"], tmp_path=tmp_path) == 0
    assert "a.exe" in capsys.readouterr().out


def test_boost_closes_only_windows_components_and_trims_without_prompt(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("prompted")))
    c = FakeCleaner()
    trimmed = []
    assert run(["boost"], c, tmp_path, trim=lambda pids: trimmed.append(list(pids)) or 5) == 0
    assert c.closed == [2]
    assert trimmed and 3 in trimmed[0]
    out = capsys.readouterr().out
    assert "CompatTelRunner.exe" in out


def test_boost_never_closes_user_apps_even_if_listed(tmp_path):
    c = FakeCleaner()
    assert run(["boost"], c, tmp_path, safe=("random.exe",)) == 0
    assert c.closed is None
