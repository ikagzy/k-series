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
    """A panel whose monitor reports the RAM use we choose, with a stand-in cleaner."""

    def __init__(self, panel, root, state):
        self.panel, self.root, self.state = panel, root, state

    def pump(self, until=lambda: False, n=300):
        for _ in range(n):
            self.root.update()
            if until():
                return True
            time.sleep(0.01)
        return False

    def poll_with(self, used_pct):
        """Publish a fresh snapshot at the given RAM use and run one poll."""
        total = 32 * GB
        self.panel._snap = Snapshot(5.0, int(total * used_pct / 100), total, (), ())
        self.panel._poll()

    def click(self, name):
        for key, (x0, y0, x1, y1) in self.panel._regions:
            if key == name:
                self.panel._on_click(types.SimpleNamespace(x=(x0 + x1) / 2, y=(y0 + y1) / 2))
                return True
        return False


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("K_OPTIMIZER_PREVIEW", raising=False)
    state = {"cleans": [], "freed": 300 * MB}
    steady = Snapshot(5.0, 8 * GB, 32 * GB, (), ())
    monkeypatch.setattr(ui.monitor, "snapshot_after", lambda interval=0.5: dataclasses.replace(steady))

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


def test_auto_ram_starts_off_with_the_default_threshold(env):
    assert env.panel._auto_ram is False and env.panel._autoram.threshold == 80
    draw(env)
    keys = [k for k, _ in env.panel._regions]
    assert "auto-ram" in keys and "auto-thr" in keys


def test_the_toggle_turns_it_on_and_off_and_remembers_the_choice(env):
    draw(env)
    assert env.click("auto-ram")
    assert env.panel._auto_ram is True and optsettings.load()["auto_ram"] is True
    draw(env)
    assert env.click("auto-ram")
    assert env.panel._auto_ram is False and optsettings.load()["auto_ram"] is False


def test_the_threshold_cycles_and_is_remembered(env):
    draw(env)
    assert env.click("auto-thr")
    assert env.panel._autoram.threshold == 90 and optsettings.load()["auto_ram_threshold"] == 90
    draw(env)
    assert env.click("auto-thr")
    assert env.panel._autoram.threshold == 70 and optsettings.load()["auto_ram_threshold"] == 70


def test_a_saved_choice_is_restored_on_the_next_launch(monkeypatch):
    optsettings.save({"auto_ram": True, "auto_ram_threshold": 70})
    monkeypatch.setattr(ui.monitor, "snapshot_after", lambda interval=0.5: Snapshot(5.0, 1, 2, (), ()))
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    panel = ui.OptimizerPanel(root, lambda: theme.PALETTES["aurora"], lambda: 1.0)
    try:
        assert panel._auto_ram is True and panel._autoram.threshold == 70
    finally:
        panel.shutdown()
        root.destroy()


def test_it_cleans_when_memory_use_reaches_the_threshold(env):
    draw(env)
    env.click("auto-ram")
    env.poll_with(90)
    assert env.pump(lambda: env.state["cleans"] and not env.panel._ram_busy)
    assert len(env.state["cleans"]) == 1
    assert "Otomatik" in env.panel._result and env.panel._result_ok is True


def test_it_does_nothing_below_the_threshold_or_when_switched_off(env):
    draw(env)
    env.click("auto-ram")
    env.poll_with(60)
    env.pump(n=30)
    assert env.state["cleans"] == []
    draw(env)
    env.click("auto-ram")  # off again
    env.poll_with(99)
    env.pump(n=30)
    assert env.state["cleans"] == []


def test_it_waits_the_interval_instead_of_cleaning_on_every_poll(env):
    draw(env)
    env.click("auto-ram")
    env.poll_with(95)
    assert env.pump(lambda: len(env.state["cleans"]) == 1 and not env.panel._ram_busy)
    for _ in range(5):
        env.poll_with(95)
    env.pump(n=30)
    assert len(env.state["cleans"]) == 1


def test_automatic_cleaning_only_trims_and_never_closes_anything(env, monkeypatch):
    draw(env)
    env.click("auto-ram")
    monkeypatch.setattr(env.panel, "_close_safe", lambda *a: (_ for _ in ()).throw(AssertionError("closed something")))
    env.poll_with(95)
    assert env.pump(lambda: env.state["cleans"] and not env.panel._ram_busy)
    assert env.panel._result_ok is True  # the clean itself worked; no AssertionError was swallowed


def test_a_clean_that_frees_nothing_backs_the_next_one_off(env):
    env.state["freed"] = 1 * MB
    draw(env)
    env.click("auto-ram")
    env.poll_with(95)
    assert env.pump(lambda: len(env.state["cleans"]) == 1 and not env.panel._ram_busy)
    assert env.panel._autoram._interval == 120


def test_a_manual_clean_also_restarts_the_automatic_interval(env):
    draw(env)
    env.panel._clean_ram()
    assert env.pump(lambda: env.state["cleans"] and not env.panel._ram_busy)
    draw(env)
    env.click("auto-ram")
    env.poll_with(95)
    env.pump(n=30)
    assert len(env.state["cleans"]) == 1  # the manual clean just now counts: no immediate second one


def test_preview_mode_ignores_the_toggle(env, monkeypatch):
    monkeypatch.setenv("K_OPTIMIZER_PREVIEW", "1")
    draw(env)
    assert env.click("auto-ram")
    assert env.panel._auto_ram is False and optsettings.load()["auto_ram"] is False


def test_the_toggle_appears_on_the_ram_card_only(env):
    draw(env)
    assert [k for k, _ in env.panel._regions].count("auto-ram") == 1
