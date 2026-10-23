import os

import psutil

from k_optimizer import monitor, procscan
from k_optimizer.gpu import GpuReading
from k_optimizer.models import GpuAdapter

MB = 1024 * 1024


def raw(pid, name="app.exe", create=1000.0, cpu=0, ws=50 * MB, ppid=4):
    return procscan.RawProc(pid, ppid, name, create, cpu, ws)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def table(scans, info=None, clock=None, cores=4, budget=0.15):
    """A ProcessTable fed by a list of scripted scans (the last one repeats)."""
    seq = list(scans)
    clock = clock or Clock()
    calls = []

    def scan():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def default_info(pid):
        calls.append(pid)
        return (f"C:\apps\p{pid}.exe", (f"C:\apps\p{pid}.exe", "--x"))

    t = monitor.ProcessTable(scan=scan, info=info or default_info, clock=clock, cores=cores, budget_s=budget)
    t.info_calls = calls
    t.clock = clock
    return t


# --- the live machine ---------------------------------------------------------------------------------
def test_snapshot_contains_own_process_with_real_values():
    s = monitor.snapshot(lambda: None)
    me = next(p for p in s.processes if p.pid == os.getpid())
    assert me.name.lower().startswith("python") and me.rss_bytes > 5 * MB
    assert me.gpu_percent is None and me.vram_bytes is None
    assert s.ram_total_bytes > 0 and s.adapters == ()


def test_snapshot_merges_the_gpu_reading():
    me = os.getpid()
    reading = GpuReading({me: 12.5}, {me: 1024}, (GpuAdapter("0x0_0x1", 5.0, 99),))
    s = monitor.snapshot(lambda: reading)
    by_pid = {p.pid: p for p in s.processes}
    assert by_pid[me].gpu_percent == 12.5 and by_pid[me].vram_bytes == 1024
    other = next(p for p in s.processes if p.pid != me)
    assert other.gpu_percent == 0.0 and other.vram_bytes == 0  # reading succeeded: absent means idle
    assert s.adapters == reading.adapters


def test_snapshot_after_waits_then_snapshots(monkeypatch):
    slept = []
    monkeypatch.setattr(monitor.time, "sleep", slept.append)
    s = monitor.snapshot_after(0.25, read_gpu_fn=lambda: None)
    assert slept == [0.25] and os.getpid() in {p.pid for p in s.processes}


def test_a_full_snapshot_is_cheap_now():
    import time

    monitor.snapshot(lambda: None)
    start = psutil.Process().cpu_times()
    t = time.perf_counter()
    for _ in range(5):
        monitor.snapshot(lambda: None)
    wall = (time.perf_counter() - t) / 5
    used = psutil.Process().cpu_times()
    cpu = ((used.user + used.system) - (start.user + start.system)) / 5
    assert cpu < 0.25, f"{cpu * 1000:.0f} ms of CPU per snapshot (it used to be ~2500 ms)"
    assert wall < 0.5


# --- the process table ----------------------------------------------------------------------------------
def test_cpu_percent_is_cpu_time_over_wall_time_over_cores_and_first_sight_is_zero():
    t = table([[raw(1, cpu=0)], [raw(1, cpu=int(2e7))]], cores=4)  # +2 s of CPU
    first = t.read()
    assert first[0].cpu_percent == 0.0
    t.clock.t += 2.0                      # two seconds later: 2 s CPU / 2 s wall / 4 cores = 25%
    assert t.read()[0].cpu_percent == 25.0


def test_a_reused_pid_or_a_backwards_counter_never_gives_a_negative_or_wild_percent():
    t = table([[raw(1, create=1000.0, cpu=10**9)], [raw(1, create=2000.0, cpu=10)], [raw(1, create=2000.0, cpu=5)]])
    t.read()
    t.clock.t += 2
    assert t.read()[0].cpu_percent == 0.0   # a different process now owns pid 1
    t.clock.t += 2
    assert t.read()[0].cpu_percent == 0.0   # counter went backwards


def test_processinfo_fields_come_from_the_scan_and_the_cached_static_info():
    t = table([[raw(7, name="Discord.exe", create=1234.5, ws=300 * MB)]])
    p = t.read()[0]
    assert (p.pid, p.name, p.create_time, p.rss_bytes) == (7, "Discord.exe", 1234.5, 300 * MB)
    assert p.exe == "C:\apps\p7.exe" and p.cmdline == ("C:\apps\p7.exe", "--x")
    assert p.gpu_percent is None and p.vram_bytes is None


def test_static_info_is_fetched_once_per_process_not_on_every_read():
    t = table([[raw(1), raw(2)]])
    for _ in range(5):
        t.read()
        t.clock.t += 2
    assert sorted(t.info_calls) == [1, 2]


def test_a_new_or_restarted_process_gets_fresh_static_info_and_exited_ones_are_forgotten():
    t = table([[raw(1), raw(2)], [raw(1), raw(3)], [raw(1, create=5000.0), raw(3)]])
    t.read()
    t.read()
    assert sorted(t.info_calls) == [1, 2, 3]
    t.read()                                # pid 1 restarted: new create time, new lookup
    assert t.info_calls.count(1) == 2
    assert 2 not in t._static               # pid 2 exited and was pruned


def test_denied_info_is_remembered_as_none_so_it_is_not_retried_forever():
    asked = []

    def info(pid):
        asked.append(pid)
        return (None, ())

    t = table([[raw(1)]], info=info)
    for _ in range(4):
        p = t.read()[0]
    assert p.exe is None and p.cmdline == () and asked == [1]


def test_info_lookups_are_budgeted_so_the_first_snapshots_stay_quick():
    clock = Clock()

    def slow_info(pid):
        clock.t += 0.01                     # every lookup "takes" 10 ms
        return (f"C:\a\{pid}.exe", ())

    t = table([[raw(i) for i in range(1, 101)]], info=slow_info, clock=clock, budget=0.1)
    first = t.read()
    resolved = [p for p in first if p.exe]
    assert 5 <= len(resolved) <= 15 and len(first) == 100  # ~100 ms / 10 ms; the rest are listed, unresolved
    assert all(p.exe is None for p in first if p not in resolved)
    for _ in range(12):
        t.read()
    assert all(p.exe for p in t.read())     # a few reads later everything is resolved


def test_pid_zero_the_idle_process_is_left_out():
    t = table([[raw(0, name="System Idle Process"), raw(4, name="System")]])
    assert [p.pid for p in t.read()] == [4]


def test_if_the_native_scan_fails_the_snapshot_falls_back_to_psutil(monkeypatch):
    def broken():
        raise OSError("no ntdll")

    t = monitor.ProcessTable(scan=broken)
    got = t.read()
    assert os.getpid() in {p.pid for p in got}


# --- sampling in a loop: the previous reading is the baseline ----------------------------------------------
def test_sample_primes_only_the_first_time_and_then_reuses_the_previous_reading(monkeypatch):
    slept = []
    monkeypatch.setattr(monitor.time, "sleep", slept.append)
    fresh = monitor.ProcessTable()
    monkeypatch.setattr(monitor, "_default_table", fresh)
    assert fresh.primed is False
    monitor.sample(0.5, read_gpu_fn=lambda: None)
    assert slept.count(0.5) == 1 and fresh.primed is True      # the first call waits to build a baseline
    monitor.sample(0.5, read_gpu_fn=lambda: None)
    monitor.sample(0.5, read_gpu_fn=lambda: None)
    assert slept.count(0.5) == 1                             # later calls do not wait at all


def test_a_sample_after_a_gap_reports_cpu_over_the_whole_gap():
    clock = Clock()
    t = table([[raw(1, cpu=0)], [raw(1, cpu=int(1e7 * 8))]], clock=clock, cores=4)
    t.read()
    clock.t += 4.0                                       # 4 s later it has used 8 s of CPU on 4 cores
    assert t.read()[0].cpu_percent == 50.0
