import os

import psutil

from k_optimizer import throttle
from k_optimizer.models import Level, ProcInfo

NORMAL = psutil.NORMAL_PRIORITY_CLASS
BELOW = psutil.BELOW_NORMAL_PRIORITY_CLASS


def mk(pid, cpu=0.0, gpu=None, ct=1.0, name="app.exe"):
    return ProcInfo(pid, name, "D:" + chr(92) + name, (), ct, cpu, 1, gpu, None)


class FakeOps:
    def __init__(self, cts=None, cpu=None, gpu=None, eco=None, fail_set=()):
        self.cts = cts or {}
        self.cpu = cpu if cpu is not None else {}
        self.gpu = gpu if gpu is not None else {}
        self.eco = eco if eco is not None else {}
        self.fail_set = set(fail_set)
        self.log = []

    def create_time(self, pid):
        return self.cts.get(pid)

    def get_cpu(self, pid):
        return self.cpu.get(pid)

    def set_cpu(self, pid, cls):
        self.log.append(("cpu", pid, cls))
        if pid in self.fail_set:
            return False
        self.cpu[pid] = cls
        return True

    def get_eco(self, pid):
        return self.eco.get(pid, False)

    def set_eco(self, pid, on):
        self.log.append(("eco", pid, on))
        self.eco[pid] = on
        return True

    def get_gpu(self, pid):
        return self.gpu.get(pid)

    def set_gpu(self, pid, cls):
        self.log.append(("gpu", pid, cls))
        if pid in self.fail_set:
            return False
        self.gpu[pid] = cls
        return True


def level(p):
    return Level.PROTECTED if p.pid == 99 else Level.UNKNOWN


def test_pick_cpu_skips_foreground_protected_own_light_and_gpu_heavy():
    procs = [
        mk(1, cpu=5.0),            # background hog -> picked
        mk(2, cpu=5.0),            # in the foreground tree
        mk(99, cpu=5.0),           # protected
        mk(4, cpu=0.1),            # idle
        mk(5, cpu=5.0, gpu=40.0),  # looks like a game / GPU workload
        mk(6, cpu=5.0),            # our own
    ]
    got = throttle.pick_background(procs, level, frozenset({6}), frozenset({2}), "cpu")
    assert [p.pid for p in got] == [1]


def test_pick_gpu_picks_background_gpu_users_only():
    procs = [mk(1, gpu=12.0), mk(2, gpu=12.0), mk(3, gpu=0.0), mk(4, gpu=None), mk(99, gpu=50.0)]
    got = throttle.pick_background(procs, level, frozenset(), frozenset({2}), "gpu")
    assert [p.pid for p in got] == [1]


def test_apply_cpu_lowers_priority_and_enables_eco_and_records(tmp_path):
    ops = FakeOps(cts={1: 1.0}, cpu={1: NORMAL})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    r = t.apply([mk(1)], "cpu")
    assert [p.pid for p in r.applied] == [1]
    assert ops.cpu[1] == BELOW and ops.eco[1] is True
    assert t.pending() == 1


def test_apply_skips_vanished_reused_denied_and_already_low(tmp_path):
    ops = FakeOps(
        cts={2: 9.0, 3: 1.0, 4: 1.0, 5: 1.0},
        cpu={2: NORMAL, 3: None, 4: BELOW, 5: NORMAL},
        fail_set={5},
    )
    t = throttle.Throttler(tmp_path / "t.json", ops)
    r = t.apply([mk(1), mk(2), mk(3), mk(4), mk(5)], "cpu")
    reasons = {p.pid: why for p, why in r.skipped}
    assert reasons == {1: "süreç yok", 2: "süreç değişmiş", 3: "yetki gerekir",
                       4: "zaten düşük", 5: "yetki gerekir"}
    assert r.applied == () and t.pending() == 0


def test_apply_gpu_lowers_scheduling_class(tmp_path):
    ops = FakeOps(cts={1: 1.0}, gpu={1: 2})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    assert len(t.apply([mk(1)], "gpu").applied) == 1
    assert ops.gpu[1] == 1


def test_restore_puts_back_previous_values_and_clears(tmp_path):
    ops = FakeOps(cts={1: 1.0, 2: 1.0}, cpu={1: NORMAL}, gpu={2: 3}, eco={1: False})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    t.apply([mk(1)], "cpu")
    t.apply([mk(2)], "gpu")
    assert t.restore() == 2
    assert ops.cpu[1] == NORMAL and ops.eco[1] is False and ops.gpu[2] == 3
    assert t.pending() == 0


def test_restore_leaves_eco_on_if_it_was_already_on(tmp_path):
    ops = FakeOps(cts={1: 1.0}, cpu={1: NORMAL}, eco={1: True})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    t.apply([mk(1)], "cpu")
    t.restore()
    assert ops.eco[1] is True


def test_restore_skips_reused_pid(tmp_path):
    ops = FakeOps(cts={1: 1.0}, cpu={1: NORMAL})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    t.apply([mk(1)], "cpu")
    ops.cts[1] = 77.0  # pid now belongs to another process
    ops.log.clear()
    assert t.restore() == 0
    assert ops.log == []


def test_corrupt_store_is_treated_as_empty(tmp_path):
    (tmp_path / "t.json").write_text("{bozuk")
    t = throttle.Throttler(tmp_path / "t.json", FakeOps())
    assert t.pending() == 0 and t.restore() == 0


def test_related_pids_includes_self_ancestors_and_descendants():
    got = throttle.related_pids(os.getpid())
    assert os.getpid() in got and os.getppid() in got


def test_real_ops_roundtrip_on_own_process():
    ops = throttle.WinOps()
    pid = os.getpid()
    before_cpu, before_gpu = ops.get_cpu(pid), ops.get_gpu(pid)
    assert before_cpu is not None and before_gpu is not None
    assert ops.set_cpu(pid, BELOW) and ops.get_cpu(pid) == BELOW
    assert ops.set_gpu(pid, 1) and ops.get_gpu(pid) == 1
    assert ops.set_cpu(pid, before_cpu) and ops.set_gpu(pid, before_gpu)
    assert ops.get_cpu(pid) == before_cpu and ops.get_gpu(pid) == before_gpu


def test_restore_can_be_limited_to_one_kind_and_keeps_the_rest(tmp_path):
    ops = FakeOps(cts={1: 1.0, 2: 1.0}, cpu={1: NORMAL}, gpu={2: 3})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    t.apply([mk(1)], "cpu")
    t.apply([mk(2)], "gpu")
    assert t.restore(kind="cpu") == 1
    assert ops.cpu[1] == NORMAL and ops.gpu[2] == 1  # gpu throttle untouched
    assert t.pending() == 1 and t.pending_pids("gpu") == {2}


def test_restore_can_be_limited_to_given_pids(tmp_path):
    ops = FakeOps(cts={1: 1.0, 2: 1.0}, cpu={1: NORMAL, 2: NORMAL})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    t.apply([mk(1), mk(2)], "cpu")
    assert t.restore(kind="cpu", pids={1}) == 1
    assert ops.cpu[1] == NORMAL and ops.cpu[2] == BELOW
    assert t.pending_pids("cpu") == {2}


# --- boosting the foreground app's GPU priority ---------------------------------------------------------------
MB = 1024 * 1024


def gp(pid, gpu=None, vram=None, name="game.exe"):
    return ProcInfo(pid, name, "C:\Games\\" + name, (), 1.0, 0.0, 1, gpu, vram)


def test_pick_foreground_gpu_takes_only_gpu_users_inside_the_foreground_group():
    procs = [
        gp(1, gpu=40.0),                       # the game itself
        gp(2, gpu=2.0, name="game-gpu.exe"),   # its GPU helper process
        gp(3, gpu=0.0, vram=500 * MB),         # holds lots of VRAM: counts
        gp(4, gpu=0.0, vram=10 * MB),          # idle
        gp(5, gpu=60.0),                       # busy but NOT in the foreground group
        gp(6, gpu=30.0),                       # ours
        gp(99, gpu=30.0),                      # protected
        gp(7, gpu=None, vram=None),            # no GPU data at all
    ]
    got = throttle.pick_foreground_gpu(procs, level, frozenset({6}), frozenset({1, 2, 3, 4, 6, 99, 7}))
    assert [p.pid for p in got] == [1, 2, 3]


def test_pick_foreground_gpu_with_no_foreground_group_picks_nothing():
    assert throttle.pick_foreground_gpu([gp(1, gpu=90.0)], level, frozenset(), frozenset()) == []


def test_boost_raises_the_gpu_class_to_above_normal_never_higher_and_records_the_old_value(tmp_path):
    ops = FakeOps(cts={1: 1.0}, gpu={1: 2})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    r = t.boost_gpu([mk(1)])
    assert [p.pid for p in r.applied] == [1]
    assert ops.gpu[1] == 3 and throttle.GPU_BOOST_CLASS == 3  # ABOVE_NORMAL: HIGH/REALTIME could starve the desktop
    assert t.pending_pids("gpu-boost") == {1}
    assert t.restore() == 1 and ops.gpu[1] == 2 and t.pending() == 0


def test_boost_skips_vanished_reused_unreadable_denied_and_already_high_processes(tmp_path):
    ops = FakeOps(cts={2: 9.0, 3: 1.0, 4: 1.0, 5: 1.0}, gpu={2: 2, 3: None, 4: 4, 5: 2}, fail_set={5})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    r = t.boost_gpu([mk(1), mk(2), mk(3), mk(4), mk(5)])
    reasons = {p.pid: why for p, why in r.skipped}
    assert reasons == {1: "süreç yok", 2: "süreç değişmiş", 3: "GPU önceliği okunamadı", 4: "zaten yüksek",
                       5: "yetki gerekir"}
    assert r.applied == () and t.pending() == 0


def test_boost_and_lowering_are_kept_apart_so_each_can_be_undone_on_its_own(tmp_path):
    ops = FakeOps(cts={1: 1.0, 2: 1.0}, gpu={1: 2, 2: 2})
    t = throttle.Throttler(tmp_path / "t.json", ops)
    t.apply([mk(1)], "gpu")       # background app slowed down
    t.boost_gpu([mk(2)])          # foreground app raised
    assert ops.gpu == {1: 1, 2: 3}
    assert t.pending_pids("gpu") == {1} and t.pending_pids("gpu-boost") == {2}
    assert t.restore(kind="gpu-boost") == 1
    assert ops.gpu == {1: 1, 2: 2}
    assert t.restore() == 1 and ops.gpu == {1: 2, 2: 2}
