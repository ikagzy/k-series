import json
import os

from k_optimizer import cli
from k_optimizer.cleaner import CloseReport, RestoreReport
from k_optimizer.models import Level, ProcInfo, Snapshot


def mk(pid, name, exe, rss=50 * 1024 * 1024):
    return ProcInfo(pid, name, exe, (exe,), 1.0, 1.5, rss, None, None)


SNAP = Snapshot(
    10.0, 1, 2, (),
    (
        mk(1, "lsass.exe", r"D:\x\lsass.exe"),
        mk(2, "discord.exe", r"D:\d\discord.exe"),
        mk(3, "random.exe", r"D:\r\random.exe"),
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


def run(argv, cleaner=None, tmp_path=None):
    known = tmp_path / "k.json"
    known.write_text(json.dumps({"safe": ["discord.exe"]}))
    return cli.main(argv, snapshot_fn=lambda: SNAP, cleaner=cleaner or FakeCleaner(), known_path=known)


def test_scan_never_prints_protected_processes(capsys, tmp_path):
    assert run(["scan"], tmp_path=tmp_path) == 0
    out = capsys.readouterr().out
    assert "lsass.exe" not in out
    assert "discord.exe" in out and "safe" in out
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


def test_close_protected_pid_is_not_offered_to_cleaner(capsys, tmp_path):
    c = FakeCleaner()
    assert run(["close", "--pids", "1", "--yes"], c, tmp_path) == 1
    assert c.closed is None


def test_restore_prints_summary(capsys, tmp_path):
    assert run(["restore"], tmp_path=tmp_path) == 0
    assert "a.exe" in capsys.readouterr().out


def test_boost_closes_only_safe_processes_without_prompt(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("prompted")))
    c = FakeCleaner()
    assert run(["boost"], c, tmp_path) == 0
    assert c.closed == [2]
    assert "discord.exe" in capsys.readouterr().out.lower()


def test_boost_with_nothing_to_close_is_ok(capsys, tmp_path):
    c = FakeCleaner()
    known = tmp_path / "k.json"
    known.write_text(json.dumps({"safe": []}))
    assert cli.main(["boost"], snapshot_fn=lambda: SNAP, cleaner=c, known_path=known) == 0
    assert c.closed is None
