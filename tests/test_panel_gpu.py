import tkinter as tk

import pytest

from k_optimizer import gpupref, theme, throttle, ui
from k_optimizer.models import GpuAdapter, Level, ProcInfo, Snapshot

GB = 1024**3
GAME = "C:\\Games\\Cool Game\\game.exe"


class Ops:
    def __init__(self):
        self.cts = {100: 1.0, 101: 1.0, 102: 1.0}
        self.gpu = {100: 2, 101: 2, 102: 2}
        self.cpu, self.eco = {}, {}

    def create_time(self, pid):
        return self.cts.get(pid)

    def get_gpu(self, pid):
        return self.gpu.get(pid)

    def set_gpu(self, pid, cls):
        self.gpu[pid] = cls
        return True

    def get_cpu(self, pid):
        return self.cpu.get(pid)

    def set_cpu(self, pid, cls):
        self.cpu[pid] = cls
        return True

    def get_eco(self, pid):
        return False

    def set_eco(self, pid, on):
        return True


class Reg:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, data):
        self.values[name] = data

    def delete(self, name):
        self.values.pop(name, None)


def throttle_cores():
    from k_optimizer import probalance

    return probalance.CORES


def proc(pid, name, exe, gpu):
    return ProcInfo(pid, name, exe, (), 1.0, 0.0, 10, gpu, 0)


def snapshot(adapters=2):
    ads = tuple(GpuAdapter(f"0x{i}", 5.0, 1 * GB) for i in range(adapters))
    return Snapshot(5.0, 8 * GB, 32 * GB, ads, (
        proc(100, "game.exe", GAME, 35.0),                       # the game the user was in
        proc(101, "game-gpu.exe", "C:\\Games\\Cool Game\\gpu.exe", 3.0),
        proc(102, "other.exe", "C:\\Other\\other.exe", 5.0),     # a background app also using the GPU
    ))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.delenv("K_OPTIMIZER_PREVIEW", raising=False)
    monkeypatch.setattr(ui.monitor, "snapshot_after", lambda interval=0.5: snapshot())
    monkeypatch.setattr(throttle, "related_pids", lambda pid: frozenset({100, 101}))
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    p = ui.OptimizerPanel(root, lambda: theme.PALETTES["amber-orange"], lambda: 1.0)
    ops, reg = Ops(), Reg()
    p._throttler = throttle.Throttler(tmp_path / "t.json", ops)
    p._gpupref = gpupref.Store(tmp_path / "g.json", reg)
    p._classify = lambda pr: Level.UNKNOWN
    p._last_fg = 100
    p._snap = snapshot()
    p._ops, p._reg = ops, reg
    yield p
    p.shutdown()
    root.destroy()


def test_the_gpu_button_slows_background_users_boosts_the_foreground_app_and_prefers_the_fast_gpu(env):
    env._clean("gpu")
    assert env._ops.gpu[102] == 1                      # background GPU user: scheduled behind everyone
    assert env._ops.gpu[100] == 3 and env._ops.gpu[101] == 3   # the game and its GPU helper: ABOVE_NORMAL
    assert env._reg.values[GAME] == "GpuPreference=2;"          # next launch: the high-performance GPU
    assert "C:\\Other\\other.exe" not in env._reg.values        # background apps' preferences are left alone
    msg = env._result
    assert "game.exe" in msg and "other.exe" in msg and "yüksek performanslı" in msg and env._result_ok


def test_undo_puts_everything_back_priorities_and_the_registry_preference(env):
    env._reg.values[GAME] = "GpuPreference=1;"          # the user had chosen power saving for this game
    env._clean("gpu")
    env._refresh_undo()
    assert env._undo_ready is True
    env._restore()
    assert env._ops.gpu == {100: 2, 101: 2, 102: 2}
    assert env._reg.values[GAME] == "GpuPreference=1;"  # exactly the previous choice, not a default
    assert env._undo_ready is False
    assert "GPU tercihi" in env._result


def test_with_a_single_gpu_the_preference_is_not_touched_because_it_would_change_nothing(env):
    env._snap = snapshot(adapters=1)
    env._clean("gpu")
    assert env._reg.values == {}
    assert env._ops.gpu[100] == 3  # the priority boost still applies


def test_when_the_foreground_app_is_unknown_nothing_is_slowed_down_or_boosted(env):
    # K-Optimizer was started while a game ran and the user never left its window: the game must not be mistaken
    # for a background app and pushed to the back of the GPU queue.
    env._last_fg = None
    env._clean("gpu")
    assert env._ops.gpu == {100: 2, 101: 2, 102: 2} and env._reg.values == {}
    assert "ön plan" in env._result.lower()


def test_when_the_foreground_app_is_unknown_automatic_cpu_balancing_waits(env):
    from k_optimizer.models import Snapshot as S

    env._last_fg = None
    env._auto_balance = True
    hot = ProcInfo(102, "other.exe", "C:\Other\other.exe", (), 1.0, 90.0 / throttle_cores(), 10, None, None)
    env._ops.cpu[102] = 32
    env._balance(S(95.0, 1, 2, (), (hot,)))
    env._balance(S(95.0, 1, 2, (), (hot,)))
    assert env._ops.cpu[102] == 32 and env._throttler.pending() == 0


def test_clicking_twice_does_not_stack_or_lose_the_original_preference(env):
    env._reg.values[GAME] = "GpuPreference=1;"
    env._clean("gpu")
    env._clean("gpu")
    env._restore()
    assert env._reg.values[GAME] == "GpuPreference=1;" and env._ops.gpu == {100: 2, 101: 2, 102: 2}


def test_a_protected_foreground_app_is_never_boosted(env):
    env._classify = lambda pr: Level.PROTECTED if pr.pid == 100 else Level.UNKNOWN
    env._clean("gpu")
    assert env._ops.gpu[100] == 2 and env._ops.gpu[101] == 3
    assert GAME not in env._reg.values


def test_our_own_process_is_never_boosted(env):
    env._own = frozenset({101})
    env._clean("gpu")
    assert env._ops.gpu[101] == 2 and env._ops.gpu[100] == 3
