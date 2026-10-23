import os

import psutil

from k_optimizer import monitor
from k_optimizer.gpu import GpuReading
from k_optimizer.models import GpuAdapter


def test_snapshot_contains_own_process():
    s = monitor.snapshot(lambda: None)
    assert os.getpid() in {p.pid for p in s.processes}
    assert s.ram_total_bytes > 0
    assert s.adapters == ()
    assert all(p.gpu_percent is None and p.vram_bytes is None for p in s.processes)


def test_snapshot_merges_gpu_reading():
    me = os.getpid()
    reading = GpuReading({me: 12.5}, {me: 1024}, (GpuAdapter("0x0_0x1", 5.0, 99),))
    s = monitor.snapshot(lambda: reading)
    by_pid = {p.pid: p for p in s.processes}
    assert by_pid[me].gpu_percent == 12.5
    assert by_pid[me].vram_bytes == 1024
    other = next(p for p in s.processes if p.pid != me)
    assert other.gpu_percent == 0.0 and other.vram_bytes == 0
    assert s.adapters == reading.adapters


class FakeProc:
    def __init__(self, pid, info, exc=None):
        self.info = {"pid": pid, "name": f"p{pid}.exe", "create_time": 1.0, **info}
        self._exc = exc

    def cpu_percent(self, interval=None):
        if self._exc:
            raise self._exc(self.info["pid"])
        return 4.0


def test_snapshot_skips_processes_that_vanish_and_keeps_denied_ones(monkeypatch):
    fakes = [
        FakeProc(1, {"exe": "C:\a.exe", "cmdline": ["a"], "memory_info": None}),
        FakeProc(2, {"exe": None, "cmdline": None, "memory_info": None}),
        FakeProc(3, {"exe": "C:\c.exe", "cmdline": ["c"], "memory_info": None}, psutil.NoSuchProcess),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None, ad_value=None: iter(fakes))
    s = monitor.snapshot(lambda: None)
    pids = {p.pid: p for p in s.processes}
    assert set(pids) == {1, 2}
    assert pids[2].exe is None and pids[2].cmdline == ()
    assert pids[2].rss_bytes == 0
