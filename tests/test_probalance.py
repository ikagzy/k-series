import psutil

from k_optimizer import probalance, throttle
from k_optimizer.models import Level, ProcInfo, Snapshot

NORMAL = psutil.NORMAL_PRIORITY_CLASS
BELOW = psutil.BELOW_NORMAL_PRIORITY_CLASS


def proc(pid, cpu=0.0, gpu=None, name="hog.exe"):
    return ProcInfo(pid, name, "D:" + chr(92) + name, (), 1.0, cpu, 1, gpu, None)


def snap(system, *procs):
    return Snapshot(system, 1, 2, (), tuple(procs))


class Ops:
    def __init__(self, pids):
        self.cts = {p: 1.0 for p in pids}
        self.cpu = {p: NORMAL for p in pids}
        self.eco = {}

    def create_time(self, pid):
        return self.cts.get(pid)

    def get_cpu(self, pid):
        return self.cpu.get(pid)

    def set_cpu(self, pid, cls):
        self.cpu[pid] = cls
        return True

    def get_eco(self, pid):
        return self.eco.get(pid, False)

    def set_eco(self, pid, on):
        self.eco[pid] = on
        return True


def level(p):
    return Level.PROTECTED if p.pid == 99 else Level.UNKNOWN


def engine(tmp_path, pids=(1, 2, 3, 99)):
    ops = Ops(pids)
    t = throttle.Throttler(tmp_path / "t.json", ops)
    return probalance.ProBalance(t, level, frozenset({50})), ops, t


# process cpu_percent is a share of the whole machine; thresholds are in % of ONE core
HOT = (probalance.PROC_THRESHOLD + 20) / probalance.CORES
WARM = (probalance.PROC_THRESHOLD - 20) / probalance.CORES
BUSY = probalance.SYSTEM_THRESHOLD + 10


def run_for(pb, seconds, system, procs, exclude=frozenset(), start=0.0, step=1.5):
    now, reports = start, []
    while now <= start + seconds:
        reports.append(pb.tick(now, snap(system, *procs), exclude))
        now += step
    return reports


def test_nothing_is_restrained_while_the_system_is_not_busy(tmp_path):
    pb, ops, _ = engine(tmp_path)
    run_for(pb, 30, probalance.SYSTEM_THRESHOLD - 20, [proc(1, cpu=HOT)])
    assert ops.cpu[1] == NORMAL


def test_hog_is_restrained_only_after_staying_over_threshold_for_the_required_time(tmp_path):
    pb, ops, t = engine(tmp_path)
    first = pb.tick(0.0, snap(BUSY, proc(1, cpu=HOT)), frozenset())
    assert first.restrained == () and ops.cpu[1] == NORMAL
    pb.tick(1.5, snap(BUSY, proc(1, cpu=HOT)), frozenset())
    late = pb.tick(probalance.TIME_OVER + 0.1, snap(BUSY, proc(1, cpu=HOT)), frozenset())
    assert [p.pid for p in late.restrained] == [1]
    assert ops.cpu[1] == BELOW and t.pending_pids("cpu") == {1}


def test_a_dip_below_threshold_resets_the_timer(tmp_path):
    pb, ops, _ = engine(tmp_path)
    pb.tick(0.0, snap(BUSY, proc(1, cpu=HOT)), frozenset())
    pb.tick(2.0, snap(BUSY, proc(1, cpu=0.1)), frozenset())  # calmed down briefly
    pb.tick(4.0, snap(BUSY, proc(1, cpu=HOT)), frozenset())
    r = pb.tick(6.0, snap(BUSY, proc(1, cpu=HOT)), frozenset())  # only 2s over since the dip
    assert r.restrained == () and ops.cpu[1] == NORMAL


def test_foreground_protected_own_and_gpu_heavy_processes_are_never_restrained(tmp_path):
    pb, ops, _ = engine(tmp_path, pids=(1, 2, 3, 50, 99))
    procs = [proc(1, cpu=HOT), proc(2, cpu=HOT, gpu=40.0), proc(3, cpu=HOT), proc(50, cpu=HOT), proc(99, cpu=HOT)]
    run_for(pb, 10, BUSY, procs, exclude=frozenset({1}))
    assert ops.cpu[1] == NORMAL      # foreground
    assert ops.cpu[2] == NORMAL      # looks like a game
    assert ops.cpu[50] == NORMAL     # ourselves
    assert ops.cpu[99] == NORMAL     # protected
    assert ops.cpu[3] == BELOW       # the only genuine background hog


def test_released_after_hold_once_the_process_calms_down(tmp_path):
    pb, ops, t = engine(tmp_path)
    run_for(pb, 4, BUSY, [proc(1, cpu=HOT)])
    assert t.pending_pids("cpu") == {1}
    early = pb.tick(5.0, snap(BUSY, proc(1, cpu=0.0)), frozenset())
    assert early.released == () and ops.cpu[1] == BELOW  # minimum hold not elapsed
    late = pb.tick(4.0 + probalance.HOLD + 1, snap(BUSY, proc(1, cpu=0.0)), frozenset())
    assert late.released == (1,) and ops.cpu[1] == NORMAL and t.pending_pids("cpu") == set()


def test_released_when_the_system_is_no_longer_busy_after_hold(tmp_path):
    pb, ops, _ = engine(tmp_path)
    run_for(pb, 4, BUSY, [proc(1, cpu=HOT)])
    r = pb.tick(4.0 + probalance.HOLD + 1, snap(probalance.RELEASE_SYSTEM - 10, proc(1, cpu=HOT)), frozenset())
    assert r.released == (1,) and ops.cpu[1] == NORMAL


def test_released_immediately_when_the_process_becomes_the_foreground_app(tmp_path):
    pb, ops, _ = engine(tmp_path)
    run_for(pb, 4, BUSY, [proc(1, cpu=HOT)])
    r = pb.tick(4.5, snap(BUSY, proc(1, cpu=HOT)), frozenset({1}))
    assert r.released == (1,) and ops.cpu[1] == NORMAL


def test_vanished_process_is_forgotten(tmp_path):
    pb, ops, t = engine(tmp_path)
    run_for(pb, 4, BUSY, [proc(1, cpu=HOT)])
    ops.cts.pop(1)  # process exited
    pb.tick(20.0, snap(BUSY), frozenset())
    assert t.pending_pids("cpu") == set()


def test_release_all_puts_everything_back(tmp_path):
    pb, ops, t = engine(tmp_path)
    run_for(pb, 4, BUSY, [proc(1, cpu=HOT), proc(2, cpu=HOT)])
    assert pb.release_all() == 2
    assert ops.cpu[1] == NORMAL and ops.cpu[2] == NORMAL and t.pending_pids("cpu") == set()


def test_a_single_threaded_hog_is_caught_whatever_the_core_count(tmp_path, monkeypatch):
    # on a 24-thread machine one busy thread is only ~4% of total CPU, on 4 cores it is 25%
    for cores in (4, 24, 64):
        monkeypatch.setattr(probalance, "CORES", cores)
        pb, ops, _ = engine(tmp_path / str(cores))
        one_busy_core = 100.0 / cores * 0.6  # 60% of one core, as a share of the machine
        run_for(pb, 6, BUSY, [proc(1, cpu=one_busy_core)])
        assert ops.cpu[1] == BELOW, cores


def test_a_process_below_the_per_core_threshold_is_left_alone(tmp_path):
    pb, ops, _ = engine(tmp_path)
    run_for(pb, 10, BUSY, [proc(1, cpu=WARM)])
    assert ops.cpu[1] == NORMAL
