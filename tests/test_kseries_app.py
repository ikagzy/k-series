import types

import pytest

from k_optimizer import theme
from k_series import app as kapp


@pytest.fixture
def ks(monkeypatch):
    monkeypatch.delenv("K_OPTIMIZER_PREVIEW", raising=False)
    monkeypatch.delenv("K_SERIES_PAGE", raising=False)
    try:
        a = kapp.KSeriesApp()
    except Exception as e:  # no display available
        pytest.skip(f"no Tk display: {e}")
    a.update()
    yield a
    a._close()


def click(a, key):
    for k, (x0, y0, x1, y1) in a._regions:
        if k == key:
            a._on_click(types.SimpleNamespace(x=(x0 + x1) / 2, y=(y0 + y1) / 2))
            return True
    return False


def scan_done(a):
    for _ in range(200):
        a.update()
        if not a._scanning:
            return
    raise AssertionError("product scan never finished")


def test_every_page_draws_and_the_sidebar_navigates(ks):
    scan_done(ks)
    for page in ("home", "launcher", "settings"):
        ks._goto(page)
        ks._draw()
    ks._goto("home")
    ks._draw()
    assert click(ks, ("nav", "settings")) and ks._page == "settings"
    ks._draw()
    assert click(ks, ("nav", "optimizer")) and ks._page == "optimizer"
    ks.update()
    assert ks.optimizer.winfo_ismapped()
    ks._goto("home")
    ks.update()
    assert not ks.optimizer.winfo_ismapped()


def test_home_lists_both_products_with_optimizer_builtin(ks):
    scan_done(ks)
    ks._goto("home")
    ks._draw()
    ids = {p.id: p for p in ks._products}
    assert ids["k-optimizer"].builtin and "k-launcher" in ids
    assert ("goto", "optimizer") in [k for k, _ in ks._regions]


def test_settings_offers_every_k_launcher_theme_and_selecting_one_applies_and_saves_it(ks):
    scan_done(ks)
    ks._goto("settings")
    ks._draw()
    theme_keys = [k for k, _ in ks._regions if k[0] == "theme"]
    assert len(theme_keys) == len(theme.PALETTES) == 7
    assert click(ks, ("theme", "midnight"))
    assert ks.pal.id == "midnight"
    assert theme.load().id == "midnight"  # persisted where K-Launcher reads it (a temp folder under test)
    ks._draw()
    assert click(ks, ("motion", "slow"))
    assert ks.motion == 1.6 and theme.motion_scale() == 1.6


def test_preview_mode_allows_navigation_but_never_changes_settings(monkeypatch):
    monkeypatch.setenv("K_OPTIMIZER_PREVIEW", "1")
    try:
        a = kapp.KSeriesApp()
    except Exception as e:
        pytest.skip(f"no Tk display: {e}")
    try:
        scan_done(a)
        a._goto("settings")
        a._draw()
        before = theme.load().id
        assert click(a, ("theme", "midnight"))
        assert theme.load().id == before
        assert click(a, ("nav", "home")) and a._page == "home"
    finally:
        a._close()
