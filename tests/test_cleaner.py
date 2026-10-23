import json

import psutil
import pytest

from k_optimizer.cleaner import Cleaner
from k_optimizer.models import Level, ProcInfo


def mk(pid=10, name="a.exe", exe=r"C:\Program Files\App\a.exe", ct=1.0):
    return ProcInfo(pid, name, exe, (exe, "--x"), ct, 0.0, 1000, None, None)


class FakeProc:
    def __init__(self, pid, create_time=1.0, wait_exc=None, term_exc=None):
        self.pid, self._ct, self.wait_exc, self.term_exc = pid, create_time, wait_exc, term_exc
        self.calls = []

    def create_time(self):
        return self._ct

    def terminate(self):
        self.calls.append("terminate")
        if self.term_exc:
            raise self.term_exc

    def kill(self):
        self.calls.append("kill")

    def wait(self, timeout=None):
        if self.wait_exc:
            exc, self.wait_exc = self.wait_exc, None
            raise exc


def make(tmp_path, procs, level=Level.SAFE, launched=None, launch_exc=None):
    got = []

    def get(pid):
        if pid not in procs:
            raise psutil.NoSuchProcess(pid)
        got.append(pid)
        return procs[pid]

    def launch(argv, cwd):
        if launch_exc and launch_exc(argv):
            raise OSError("boom")
        (launched if launched is not None else []).append((argv, cwd))

    c = Cleaner(tmp_path / "session.json", lambda p: level, get, launch)
    return c, got


def test_close_rejects_protected_process_without_touching_it(tmp_path):
    c, got = make(tmp_path, {10: FakeProc(10)}, level=Level.PROTECTED)
    r = c.close([mk()])
    assert got == [] and r.closed == ()
    assert r.skipped[0][1] == "korumalı"


def test_close_terminates_and_records_closed_process(tmp_path):
    fp = FakeProc(10)
    c, _ = make(tmp_path, {10: fp})
    r = c.close([mk()])
    assert fp.calls == ["terminate"]
    assert [p.pid for p in r.closed] == [10]
    assert [p.pid for p in c.pending()] == [10]


def test_close_skips_vanished_process(tmp_path):
    c, _ = make(tmp_path, {})
    assert c.close([mk()]).skipped[0][1] == "süreç yok"


def test_close_skips_reused_pid(tmp_path):
    fp = FakeProc(10, create_time=99.0)
    c, _ = make(tmp_path, {10: fp})
    r = c.close([mk(ct=1.0)])
    assert r.skipped[0][1] == "süreç değişmiş"
    assert fp.calls == []


def test_close_kills_when_terminate_times_out(tmp_path):
    fp = FakeProc(10, wait_exc=psutil.TimeoutExpired(3))
    c, _ = make(tmp_path, {10: fp})
    r = c.close([mk()])
    assert fp.calls == ["terminate", "kill"]
    assert len(r.closed) == 1


def test_close_reports_access_denied(tmp_path):
    fp = FakeProc(10, term_exc=psutil.AccessDenied(10))
    c, _ = make(tmp_path, {10: fp})
    r = c.close([mk()])
    assert r.skipped[0][1] == "yetki gerekir"
    assert c.pending() == ()


def test_restore_launches_recorded_commands_and_clears_store(tmp_path):
    launched = []
    c, _ = make(tmp_path, {10: FakeProc(10)}, launched=launched)
    c.close([mk()])
    r = c.restore()
    assert launched == [([r"C:\Program Files\App\a.exe", "--x"], r"C:\Program Files\App")]
    assert r.started == ("a.exe",) and r.failed == ()
    assert c.pending() == ()


def test_restore_continues_after_launch_failure(tmp_path):
    procs = {1: FakeProc(1), 2: FakeProc(2)}
    c, _ = make(tmp_path, procs, launch_exc=lambda argv: "bad" in argv[0])
    c.close([mk(1, "bad.exe", r"C:\bad.exe"), mk(2, "ok.exe", r"C:\ok.exe")])
    r = c.restore()
    assert len(r.failed) == 1 and r.failed[0][0] == "bad.exe"
    assert r.started == ("ok.exe",)
    assert [p.name for p in c.pending()] == ["bad.exe"]


def test_corrupt_store_is_treated_as_empty(tmp_path):
    (tmp_path / "session.json").write_text("{bozuk")
    c, _ = make(tmp_path, {})
    assert c.pending() == ()
    assert c.restore().started == ()


def test_restore_skips_chromium_style_helper_children(tmp_path):
    launched = []
    procs = {1: FakeProc(1), 2: FakeProc(2)}
    c, _ = make(tmp_path, procs, launched=launched)
    main = mk(1, "app.exe", r"C:\app.exe")
    helper = ProcInfo(2, "app.exe", r"C:\app.exe", (r"C:\app.exe", "--type=renderer"), 1.0, 0.0, 1, None, None)
    c.close([main, helper])
    r = c.restore()
    assert len(launched) == 1
    assert "--type=renderer" not in launched[0][0]
    assert c.pending() == ()
