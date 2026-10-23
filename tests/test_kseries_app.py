import time
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


# --- updates ---------------------------------------------------------------------------------
from pathlib import Path  # noqa: E402

from k_series import products as kproducts  # noqa: E402
from k_series import settings as ksettings  # noqa: E402
from k_series import updater  # noqa: E402


def available(tag="v4.1.0", pid_name="KLauncher.exe"):
    rel = updater.Release(tag, updater.parse_version(tag), pid_name, "https://github.com/o/r/x.exe", 10,
                          "a" * 64, "Notlar", "")
    return updater.Status("available", rel)


def pump(a, until, n=300):
    for _ in range(n):
        a.update()
        if until():
            return True
        time.sleep(0.01)  # let the after() timers and worker threads make progress
    return False


def launcher_product(running=False):
    return kproducts.Product("k-launcher", "K-Launcher", "", True, False, Path("C:/x/KLauncher.exe"), "4.0.0.0",
                             running)


def test_home_shows_an_update_button_only_when_an_update_is_available(ks):
    scan_done(ks)
    ks._goto("home")
    ks._draw()
    assert ("update", "k-launcher") not in [k for k, _ in ks._regions]
    ks._updates = {"k-launcher": available(), "k-series": updater.Status("current", None)}
    ks._draw()
    keys = [k for k, _ in ks._regions]
    assert ("update", "k-launcher") in keys and ("update", "k-series") not in keys


def test_confirmed_launcher_update_downloads_verifies_and_installs(ks, monkeypatch, tmp_path):
    scan_done(ks)
    ks._products = [launcher_product(running=False)]
    ks._updates = {"k-launcher": available()}
    asked, calls = [], []
    monkeypatch.setattr(kapp.messagebox, "askyesno", lambda t, m: asked.append(m) or True)
    monkeypatch.setattr(updater, "download", lambda rel, dest, progress=None: calls.append(("dl", rel.tag)) or tmp_path / "KLauncher.exe")
    monkeypatch.setattr(updater, "install_launcher", lambda path: calls.append(("install", path.name)))
    ks._start_update("k-launcher", ask=True)
    assert "v4.1.0" in asked[0] and "Notlar" in asked[0]
    assert pump(ks, lambda: not ks._update_busy and ks._message)
    assert calls == [("dl", "v4.1.0"), ("install", "KLauncher.exe")]
    assert "kuruluyor" in ks._message


def test_declining_the_confirmation_changes_nothing(ks, monkeypatch):
    scan_done(ks)
    ks._updates = {"k-launcher": available()}
    monkeypatch.setattr(kapp.messagebox, "askyesno", lambda t, m: False)
    monkeypatch.setattr(updater, "download", lambda *a, **k: 1 / 0)
    ks._start_update("k-launcher", ask=True)
    assert ks._update_busy is False


def test_update_errors_are_shown_and_never_leave_the_ui_busy(ks, monkeypatch):
    scan_done(ks)
    ks._updates = {"k-launcher": available()}
    monkeypatch.setattr(kapp.messagebox, "askyesno", lambda t, m: True)

    def refuse(*a, **k):
        raise updater.UpdateError("SHA-256 karması uyuşmuyor")

    monkeypatch.setattr(updater, "download", refuse)
    ks._start_update("k-launcher", ask=True)
    assert pump(ks, lambda: not ks._update_busy and "uyuşmuyor" in ks._message)

    monkeypatch.setattr(updater, "download", lambda *a, **k: 1 / 0)
    ks._start_update("k-launcher", ask=True)
    assert pump(ks, lambda: not ks._update_busy and "beklenmedik" in ks._message)


def test_self_update_is_refused_outside_the_frozen_exe(ks, monkeypatch):
    scan_done(ks)
    ks._updates = {"k-series": available(pid_name="K-Series.exe")}
    monkeypatch.setattr(kapp.messagebox, "askyesno", lambda t, m: 1 / 0)
    ks._start_update("k-series", ask=True)
    assert "exe" in ks._message and ks._update_busy is False


def test_automatic_install_waits_while_k_launcher_is_open_and_runs_once_otherwise(ks, monkeypatch, tmp_path):
    scan_done(ks)
    ksettings.save({"auto_install": True})
    monkeypatch.setattr(kapp.messagebox, "askyesno", lambda t, m: 1 / 0)  # must never ask in automatic mode
    started = []
    monkeypatch.setattr(updater, "download", lambda rel, dest, progress=None: started.append(rel.tag) or tmp_path / "KLauncher.exe")
    monkeypatch.setattr(updater, "install_launcher", lambda path: None)

    ks._products = [launcher_product(running=True)]
    ks._upd_q.put(({"k-launcher": available()}, False))
    assert pump(ks, lambda: "beklemede" in ks._message)
    assert started == []

    ks._auto_tried.clear()
    ks._products = [launcher_product(running=False)]
    ks._upd_q.put(({"k-launcher": available()}, False))
    assert pump(ks, lambda: started)
    ks._upd_q.put(({"k-launcher": available()}, False))  # the same update arriving again must not repeat
    pump(ks, lambda: False, n=20)
    assert started == ["v4.1.0"]


def test_automatic_install_is_off_by_default(ks, monkeypatch):
    scan_done(ks)
    monkeypatch.setattr(updater, "download", lambda *a, **k: 1 / 0)
    ks._upd_q.put(({"k-launcher": available()}, False))
    assert pump(ks, lambda: "k-launcher" in ks._updates)
    pump(ks, lambda: False, n=20)
    assert ks._update_busy is False


def test_preview_mode_never_checks_or_installs(monkeypatch):
    monkeypatch.setenv("K_OPTIMIZER_PREVIEW", "1")
    monkeypatch.setattr(updater, "check", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(updater, "download", lambda *a, **k: 1 / 0)
    try:
        a = kapp.KSeriesApp()
    except Exception as e:
        pytest.skip(f"no Tk display: {e}")
    try:
        scan_done(a)
        a.update()
        a._check_updates(announce=True)
        a._updates = {"k-launcher": available()}
        a._start_update("k-launcher", ask=False)
        assert a._update_busy is False
    finally:
        a._close()


def test_settings_page_has_update_toggles_and_toggling_persists(ks):
    scan_done(ks)
    ks._goto("settings")
    ks._draw()
    keys = [k for k, _ in ks._regions]
    assert ("flag", "auto_check") in keys and ("flag", "auto_install") in keys and ("checknow", "") in keys
    assert ksettings.flag("auto_install", False) is False
    assert click(ks, ("flag", "auto_install"))
    assert ksettings.flag("auto_install", False) is True
    assert click(ks, ("flag", "auto_check"))
    assert ksettings.flag("auto_check", True) is False


def test_changing_the_repo_validates_and_saves(ks, monkeypatch):
    scan_done(ks)
    monkeypatch.setattr(updater, "check", lambda *a, **k: updater.Status("none"))
    monkeypatch.setattr(kapp.simpledialog, "askstring", lambda *a, **k: "me/my-launcher")
    ks._change_repo("k-launcher")
    assert ksettings.repo("k-launcher") == "me/my-launcher"
    monkeypatch.setattr(kapp.simpledialog, "askstring", lambda *a, **k: "../evil")
    ks._change_repo("k-launcher")
    assert ksettings.repo("k-launcher") == "me/my-launcher" and "Geçersiz" in ks._message
