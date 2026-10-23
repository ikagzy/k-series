import os
import threading
import time
import tkinter as tk
import types

import pytest

from k_optimizer import theme, ui
from k_optimizer.models import Snapshot

GB = 1024**3


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.delenv("K_OPTIMIZER_PREVIEW", raising=False)
    calls = {"n": 0, "used": 8 * GB}

    def snap(interval=0.5):
        calls["n"] += 1
        return Snapshot(5.0, calls["used"], 32 * GB, (), ())

    monkeypatch.setattr(ui.monitor, "snapshot_after", snap)
    monkeypatch.setattr(ui, "_INTERVAL_MS", 40)
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    p = ui.OptimizerPanel(root, lambda: theme.PALETTES["amber-orange"], lambda: 1.0)
    p.pack(fill="both", expand=True)
    root.update()
    p._calls = calls
    p._root = root
    p._is_shown = lambda: True  # do not depend on the window manager's idea of 'mapped'
    yield p
    p.shutdown()
    root.destroy()


def pump(p, n=100, until=lambda: False):
    for _ in range(n):
        p._root.update()
        if until():
            return True
        time.sleep(0.01)
    return False


def draws(p, monkeypatch, frames=60):
    count = []
    original = p._draw
    monkeypatch.setattr(p, "_draw", lambda: (count.append(1), original())[1])
    pump(p, frames)
    return len(count)


def settled(p):
    """Wait until every dial has reached its value (how long that takes depends on how busy the machine is)."""
    assert pump(p, 800, until=lambda: all(abs(g.target - g.shown) < 0.2 for g in p._gauges.values())
                and p._tick > 20)
    pump(p, 15)


def test_an_idle_panel_does_not_redraw(panel, monkeypatch):
    settled(panel)
    assert draws(panel, monkeypatch, 60) == 0


def test_a_gauge_animating_to_a_new_value_repaints_until_it_arrives_and_then_stops(panel, monkeypatch):
    settled(panel)
    panel._calls["used"] = 28 * GB  # the machine's RAM use jumps from 25% to 88%
    count = []
    original = panel._draw
    monkeypatch.setattr(panel, "_draw", lambda: (count.append(1), original())[1])
    assert pump(panel, 800, until=lambda: panel._gauges["ram"].shown > 85)  # the dial sweeps there...
    assert len(count) >= 3  # ...over several repainted frames
    settled(panel)
    count.clear()
    pump(panel, 40)
    assert count == []  # and once it has arrived it stops repainting


def test_hover_messages_and_toggles_repaint(panel, monkeypatch):
    pump(panel, 80)
    panel._draw()  # regions exist
    panel._set_hover("ram")
    assert draws(panel, monkeypatch, 10) >= 1
    panel._result = "merhaba"
    assert draws(panel, monkeypatch, 10) >= 1
    panel._auto_ram = True
    assert draws(panel, monkeypatch, 10) >= 1
    panel._autoram.interval = 30
    assert draws(panel, monkeypatch, 10) >= 1


def test_it_trims_its_own_working_set_now_and_then(panel, monkeypatch):
    trimmed = []
    monkeypatch.setattr(ui.trimmer, "empty_working_set", lambda pid: trimmed.append(pid) or True)
    panel._last_trim = 0.0
    panel._maybe_trim(10)
    assert trimmed == []
    panel._maybe_trim(20)
    assert trimmed == [os.getpid()]
    panel._maybe_trim(25)
    assert len(trimmed) == 1


def test_measuring_pauses_while_minimised_and_nothing_automatic_is_on(panel, monkeypatch):
    pump(panel, 20)
    monkeypatch.setattr(panel, "_check_visible", lambda: False)
    pump(panel, 20)  # let the frame loop notice
    before = panel._calls["n"]
    pump(panel, 60)
    assert panel._calls["n"] <= before + 1  # at most the cycle that was already running


def test_measuring_continues_while_minimised_if_auto_ram_or_auto_balance_is_on(panel, monkeypatch):
    monkeypatch.setattr(panel, "_check_visible", lambda: False)
    panel._auto_ram = True
    pump(panel, 20)
    before = panel._calls["n"]
    assert pump(panel, 200, until=lambda: panel._calls["n"] >= before + 3)
    panel._auto_ram = False
    panel._auto_balance = True
    before = panel._calls["n"]
    assert pump(panel, 200, until=lambda: panel._calls["n"] >= before + 3)
    panel._auto_balance = False


def test_measuring_resumes_when_the_window_comes_back(panel, monkeypatch):
    state = {"visible": False}
    monkeypatch.setattr(panel, "_check_visible", lambda: state["visible"])
    pump(panel, 40)
    before = panel._calls["n"]
    state["visible"] = True
    assert pump(panel, 200, until=lambda: panel._calls["n"] >= before + 2)


def test_a_page_that_is_not_shown_is_never_painted_whatever_changes(panel, monkeypatch):
    pump(panel, 60)
    panel._is_shown = lambda: False
    panel._result = "gizli"
    panel._auto_ram = True
    assert draws(panel, monkeypatch, 30) == 0
    panel._is_shown = lambda: True
    assert draws(panel, monkeypatch, 15) >= 1  # shown again: it catches up with what changed meanwhile


def test_an_error_inside_one_frame_never_stops_the_repaint_loop(panel, monkeypatch, capsys):
    pump(panel, 40)
    boom = {"left": 3}

    def flaky():
        if boom["left"] > 0:
            boom["left"] -= 1
            raise RuntimeError("transient")
        return True

    monkeypatch.setattr(panel, "_check_visible", flaky)
    panel._tick = 9  # the visibility check runs every 10th frame
    before = panel._tick
    pump(panel, 60)
    assert panel._tick > before + 5  # the loop kept going
    panel._result = "hâlâ çiziyorum"
    assert draws(panel, monkeypatch, 15) >= 1


def test_minimising_is_noticed_through_the_shown_state_not_a_fragile_toplevel_lookup(panel):
    panel._is_shown = lambda: False
    assert panel._check_visible() is False
    panel._is_shown = lambda: True
    assert panel._check_visible() is True


def test_a_sub_percent_wobble_in_a_reading_does_not_repaint_but_a_whole_point_does(panel, monkeypatch):
    settled(panel)
    count = []
    original = panel._draw
    monkeypatch.setattr(panel, "_draw", lambda: (count.append(1), original())[1])
    panel._calls["used"] += int(0.03 * GB)  # +0.1 percentage point: same number, same text, same arc to the eye
    pump(panel, 60)
    assert count == []
    panel._calls["used"] += 2 * GB          # +6 points: a visible change
    assert pump(panel, 200, until=lambda: len(count) >= 1)


def test_the_dial_is_built_from_a_modest_number_of_canvas_items():
    assert ui._SEGMENTS <= 40  # each repaint creates this many arcs per active gauge
