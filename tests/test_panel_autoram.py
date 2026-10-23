import dataclasses
import time
import tkinter as tk
import types

import pytest

from k_optimizer import optsettings, ramclean, theme, ui
from k_optimizer.models import Snapshot

GB = 1024**3
MB = 1024 * 1024


class Env:
    """A panel whose monitor, clock and cleaner we control."""

    def __init__(self, panel, root, state):
        self.panel, self.root, self.state = panel, root, state

    def pump(self, until=lambda: False, n=300):
        for _ in range(n):
            self.root.update()
            if until():
                return True
            time.sleep(0.01)
        return False

    def poll_at(self, t, used_pct=40):
        """Advance the fake clock to t, publish a fresh snapshot, run one poll."""
        self.state["t"] = t
        total = 32 * GB
        self.panel._snap = Snapshot(5.0, int(total * used_pct / 100), total, (), ())
        self.panel._poll()

    def settle(self):
        assert self.pump(lambda: not self.panel._ram_busy)

    def click(self, name):
        for key, (x0, y0, x1, y1) in self.panel._regions:
            if key == name:
                self.panel._on_click(types.SimpleNamespace(x=(x0 + x1) / 2, y=(y0 + y1) / 2))
                return True
        return False


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("K_OPTIMIZER_PREVIEW", raising=False)
    state = {"cleans": [], "freed": 300 * MB, "t": 0.0}
    steady = Snapshot(5.0, 8 * GB, 32 * GB, (), ())
    monkeypatch.setattr(ui.monitor, "snapshot_after", lambda interval=0.5: dataclasses.replace(steady))
    monkeypatch.setattr(ui, "time", types.SimpleNamespace(monotonic=lambda: state["t"]))

    def fake_clean(self, pids):
        state["cleans"].append(list(pids))
        return ramclean.RamReport(len(pids), state["freed"], False, {"working_sets": True})

    monkeypatch.setattr(ramclean.RamCleaner, "clean", fake_clean)
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    panel = ui.OptimizerPanel(root, lambda: theme.PALETTES["amber-orange"], lambda: 1.0)
    panel.pack(fill="both", expand=True)
    root.update()
    e = Env(panel, root, state)
    yield e
    panel.shutdown()
    root.destroy()


def draw(e):
    e.panel._draw()


def test_auto_ram_starts_off_with_the_default_interval(env):
    assert env.panel._auto_ram is False and env.panel._autoram.interval == 10
    draw(env)
    keys = [k for k, _ in env.panel._regions]
    assert "auto-ram" in keys and "auto-int" in keys and "auto-thr" not in keys


def test_the_toggle_turns_it_on_and_off_and_remembers_the_choice(env):
    draw(env)
    assert env.click("auto-ram")
    assert env.panel._auto_ram is True and optsettings.load()["auto_ram"] is True
    draw(env)
    assert env.click("auto-ram")
    assert env.panel._auto_ram is False and optsettings.load()["auto_ram"] is False


def test_the_interval_cycles_and_is_remembered(env):
    draw(env)
    assert env.click("auto-int")
    assert env.panel._autoram.interval == 30 and optsettings.load()["auto_ram_interval"] == 30
    for expected in (60, 5, 10):
        draw(env)
        env.click("auto-int")
        assert env.panel._autoram.interval == expected


def test_a_saved_choice_is_restored_on_the_next_launch(monkeypatch):
    optsettings.save({"auto_ram": True, "auto_ram_interval": 30})
    monkeypatch.setattr(ui.monitor, "snapshot_after", lambda interval=0.5: Snapshot(5.0, 1, 2, (), ()))
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    panel = ui.OptimizerPanel(root, lambda: theme.PALETTES["aurora"], lambda: 1.0)
    try:
        assert panel._auto_ram is True and panel._autoram.interval == 30
    finally:
        panel.shutdown()
        root.destroy()


def test_once_on_it_cleans_continuously_whatever_the_memory_use(env):
    draw(env)
    env.click("auto-ram")
    for t, expected in ((0, 1), (4, 1), (10, 2), (14, 2), (20, 3), (30, 4)):
        env.poll_at(t, used_pct=30)  # low use: it still cleans, there is no threshold
        env.settle()
        assert len(env.state["cleans"]) == expected, (t, expected)


def test_a_longer_interval_cleans_less_often(env):
    draw(env)
    env.click("auto-int")  # 10 -> 30
    draw(env)
    env.click("auto-ram")
    for t in (0, 10, 20, 29):
        env.poll_at(t)
        env.settle()
    assert len(env.state["cleans"]) == 1
    env.poll_at(30)
    env.settle()
    assert len(env.state["cleans"]) == 2


def test_it_does_nothing_while_switched_off(env):
    for t in (0, 10, 20, 100):
        env.poll_at(t, used_pct=99)
    env.pump(n=30)
    assert env.state["cleans"] == []


def test_automatic_cleaning_only_trims_and_never_closes_anything(env, monkeypatch):
    draw(env)
    env.click("auto-ram")
    monkeypatch.setattr(env.panel, "_close_safe", lambda *a: (_ for _ in ()).throw(AssertionError("closed something")))
    env.poll_at(0)
    env.settle()
    assert len(env.state["cleans"]) == 1 and "hata verdi" not in env.panel._result


def test_a_clean_in_progress_is_never_overlapped(env):
    draw(env)
    env.click("auto-ram")
    env.panel._ram_busy = True  # a clean is still running
    env.poll_at(0)
    env.poll_at(50)
    env.pump(n=20)
    assert env.state["cleans"] == []


def test_a_manual_clean_restarts_the_interval(env):
    env.state["t"] = 0.0
    env.panel._clean_ram()
    env.settle()
    assert len(env.state["cleans"]) == 1
    draw(env)
    env.click("auto-ram")
    env.poll_at(3)
    env.settle()
    assert len(env.state["cleans"]) == 1  # 3 s after the manual clean: not yet
    env.poll_at(10)
    env.settle()
    assert len(env.state["cleans"]) == 2


def test_automatic_runs_stay_quiet_unless_they_actually_freed_something(env):
    draw(env)
    env.click("auto-ram")
    env.panel._result, env.panel._result_ok = "senin son mesajın", False
    env.state["freed"] = 2 * MB
    env.poll_at(0)
    env.settle()
    assert env.panel._result == "senin son mesajın"  # a quiet no-op does not overwrite your message
    env.state["freed"] = 400 * MB
    env.poll_at(10)
    env.settle()
    assert "Otomatik RAM temizliği" in env.panel._result and env.panel._result_ok is True


def test_preview_mode_ignores_the_toggle(env, monkeypatch):
    monkeypatch.setenv("K_OPTIMIZER_PREVIEW", "1")
    draw(env)
    assert env.click("auto-ram")
    assert env.panel._auto_ram is False and optsettings.load()["auto_ram"] is False


def test_the_controls_appear_on_the_ram_card_only(env):
    draw(env)
    keys = [k for k, _ in env.panel._regions]
    assert keys.count("auto-ram") == 1 and keys.count("auto-int") == 1


def test_preview_mode_never_cleans_on_its_own_even_if_auto_is_saved_on(env, monkeypatch):
    monkeypatch.setenv("K_OPTIMIZER_PREVIEW", "1")
    env.panel._auto_ram = True  # as if it had been switched on in an earlier real run
    env.poll_at(0, used_pct=95)
    env.poll_at(20, used_pct=95)
    env.pump(n=30)
    assert env.state["cleans"] == []
