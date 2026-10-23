from k_optimizer import winutil


def test_visible_window_pids_returns_int_set_and_never_raises():
    got = winutil.visible_window_pids()
    assert isinstance(got, frozenset)
    assert all(isinstance(p, int) for p in got)
