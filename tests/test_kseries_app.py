import os
import time
import tkinter as tk
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
    except tk.TclError as e:  # no display available
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
    for _ in range(5000):
        a.update()
        if not a._scanning:
            return
        time.sleep(0.01)  # let the worker thread and the after() timers make progress
    raise AssertionError("product scan never finished")


def test_every_page_draws_and_the_sidebar_navigates(ks):
    scan_done(ks)
    for page in ("home", "k-optimizer", "k-launcher", "settings"):
        ks._goto(page)
        ks._draw()
    for key in ("k-optimizer", "k-launcher", "settings", "home"):
        assert click(ks, ("nav", key)) and ks._page == key
        ks._draw()


def test_both_apps_are_separate_products_with_an_open_button_each(ks):
    scan_done(ks)
    ks._goto("home")
    ks._draw()
    ids = {p.id: p for p in ks._products}
    assert set(ids) == {"k-optimizer", "k-launcher"}
    assert not hasattr(ks, "optimizer")  # nothing of K-Optimizer is embedded in the hub any more
    ks._products = [launcher_product(), optimizer_product()]
    ks._draw()
    keys = [k for k, _ in ks._regions]
    assert ("open", "k-optimizer") in keys and ("open", "k-launcher") in keys


def test_the_open_button_launches_the_separate_optimizer_exe(ks, monkeypatch):
    scan_done(ks)
    ks._products = [optimizer_product(), launcher_product()]
    launched = []
    monkeypatch.setattr(kproducts, "launch", lambda prod, **k: launched.append(prod.id) or True)
    ks._goto("home")
    ks._draw()
    assert click(ks, ("open", "k-optimizer"))
    assert launched == ["k-optimizer"] and "başlatıldı" in ks._message


def test_a_missing_optimizer_offers_install_only_when_a_release_exists(ks):
    scan_done(ks)
    ks._products = [kproducts.Product("k-optimizer", "K-Optimizer", "", False, None, None, False), launcher_product()]
    ks._goto("home")
    ks._draw()
    keys = [k for k, _ in ks._regions]
    assert ("open", "k-optimizer") not in keys and ("update", "k-optimizer") not in keys  # disabled "Bulunamadı"
    ks._updates = {"k-optimizer": available(pid_name="K-Optimizer.exe")}
    ks._draw()
    assert ("update", "k-optimizer") in [k for k, _ in ks._regions]  # "Yükle"


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
    except tk.TclError as e:
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


def pump(a, until, n=1500):
    for _ in range(n):
        a.update()
        if until():
            return True
        time.sleep(0.01)  # let the after() timers and worker threads make progress
    return False


def launcher_product(running=False):
    return kproducts.Product("k-launcher", "K-Launcher", "", True, Path("C:/x/KLauncher.exe"), "4.0.0.0", running)


def optimizer_product(running=False, version="1.0.0.0"):
    return kproducts.Product("k-optimizer", "K-Optimizer", "", True, Path("C:/x/K-Optimizer.exe"), version, running)


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
    except tk.TclError as e:
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


# --- themed app icon & desktop shortcut ----------------------------------------------------------
import sys  # noqa: E402

from k_optimizer import icons  # noqa: E402
from k_series import shortcuts  # noqa: E402


def test_window_icon_is_the_k_launcher_theme_icon_and_follows_every_theme_change(ks):
    assert icons.current_icon_key(ks) == ks.pal.id
    scan_done(ks)
    ks._goto("settings")
    ks._draw()
    assert click(ks, ("theme", "midnight"))
    assert icons.current_icon_key(ks) == "midnight"
    assert click(ks, ("theme", "aurora"))
    assert icons.current_icon_key(ks) == "aurora"


def test_theme_change_rewrites_the_shortcut_icon_only_if_we_made_a_shortcut(ks, monkeypatch, tmp_path):
    scan_done(ks)
    made = []
    monkeypatch.setattr(shortcuts, "create", lambda lnk, target, icon, runner=None: made.append((lnk, icon)) or True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    ks._goto("settings")
    ks._draw()
    assert click(ks, ("theme", "midnight"))
    pump(ks, lambda: False, n=15)
    assert made == []  # no shortcut was created, so nothing to refresh

    lnk = tmp_path / "K-Series.lnk"
    lnk.write_bytes(b"x")
    ksettings.save({**ksettings.load(), "shortcut": str(lnk)})
    assert click(ks, ("theme", "aurora"))
    assert pump(ks, lambda: made)
    assert made[0][0] == lnk and "aurora-ks.ico" in str(made[0][1])
    assert made[0][1].exists()  # the themed .ico was generated for it


def test_creating_the_shortcut_saves_its_path_and_uses_the_themed_icon(ks, monkeypatch, tmp_path):
    scan_done(ks)
    made = []
    monkeypatch.setattr(shortcuts, "create", lambda lnk, target, icon, runner=None: made.append((lnk, icon)) or True)
    monkeypatch.setattr(shortcuts, "desktop_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    ks._goto("home")
    ks._draw()
    assert click(ks, ("shortcut", ""))
    assert made[0][0] == tmp_path / "K-Series.lnk" and f"{ks.pal.id}-ks.ico" in str(made[0][1])
    assert ksettings.load()["shortcut"] == str(tmp_path / "K-Series.lnk")
    assert "hazır" in ks._message


def test_shortcut_is_refused_outside_the_exe_and_reports_failures(ks, monkeypatch, tmp_path):
    scan_done(ks)
    monkeypatch.delattr(sys, "frozen", raising=False)
    ks._goto("home")
    ks._draw()
    assert click(ks, ("shortcut", ""))
    assert "exe" in ks._message

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(shortcuts, "create", lambda *a, **k: False)
    monkeypatch.setattr(shortcuts, "desktop_dir", lambda: tmp_path)
    assert click(ks, ("shortcut", ""))
    assert "oluşturulamadı" in ks._message and "shortcut" not in ksettings.load()


def test_standalone_optimizer_window_has_the_theme_icon(monkeypatch):
    from k_optimizer import ui

    try:
        app = ui.App()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    try:
        assert icons.current_icon_key(app) == app.pal.id
    finally:
        app._close()


# --- K-Optimizer updates and installation ---------------------------------------------------------
from k_optimizer import klauncher  # noqa: E402


def test_confirmed_optimizer_update_replaces_the_installed_exe_in_place(ks, monkeypatch, tmp_path):
    scan_done(ks)
    ks._products = [optimizer_product(running=True), launcher_product()]
    ks._updates = {"k-optimizer": available(pid_name="K-Optimizer.exe")}
    asked, calls = [], []
    monkeypatch.setattr(kapp.messagebox, "askyesno", lambda t, m: asked.append(m) or True)
    monkeypatch.setattr(updater, "download", lambda rel, dest, progress=None: tmp_path / "K-Optimizer.exe")
    monkeypatch.setattr(updater, "install_exe", lambda path, target: calls.append(target))
    ks._start_update("k-optimizer", ask=True)
    assert "K-Optimizer" in asked[0] and "nazikçe kapatılacak" in asked[0]  # it is running: closed politely
    assert pump(ks, lambda: not ks._update_busy and ks._message)
    assert calls == [Path("C:/x/K-Optimizer.exe")] and "hazır" in ks._message


def test_a_fresh_optimizer_install_goes_to_the_default_programs_folder(ks, monkeypatch, tmp_path):
    scan_done(ks)
    ks._products = [kproducts.Product("k-optimizer", "K-Optimizer", "", False, None, None, False), launcher_product()]
    ks._updates = {"k-optimizer": available(pid_name="K-Optimizer.exe")}
    asked, calls = [], []
    monkeypatch.setattr(kapp.messagebox, "askyesno", lambda t, m: asked.append(m) or True)
    monkeypatch.setattr(updater, "download", lambda rel, dest, progress=None: tmp_path / "K-Optimizer.exe")
    monkeypatch.setattr(updater, "install_exe", lambda path, target: calls.append(target))
    ks._start_update("k-optimizer", ask=True)
    assert "yüklü değil" in asked[0] and "yüklensin" in asked[0]
    assert pump(ks, lambda: not ks._update_busy and ks._message)
    assert calls == [klauncher.optimizer_install_path()]


def test_automatic_mode_updates_an_installed_optimizer_but_never_installs_a_missing_one(ks, monkeypatch, tmp_path):
    scan_done(ks)
    ksettings.save({"auto_install": True})
    started = []
    monkeypatch.setattr(kapp.messagebox, "askyesno", lambda t, m: 1 / 0)
    monkeypatch.setattr(updater, "download", lambda rel, dest, progress=None: started.append(rel.tag) or tmp_path / "x.exe")
    monkeypatch.setattr(updater, "install_exe", lambda path, target: None)

    ks._products = [kproducts.Product("k-optimizer", "K-Optimizer", "", False, None, None, False), launcher_product()]
    ks._upd_q.put(({"k-optimizer": available(pid_name="K-Optimizer.exe")}, False))
    pump(ks, lambda: "k-optimizer" in ks._updates)
    pump(ks, lambda: False, n=20)
    assert started == []  # a first install is always a manual choice

    ks._products = [optimizer_product(), launcher_product()]
    ks._upd_q.put(({"k-optimizer": available(pid_name="K-Optimizer.exe")}, False))
    assert pump(ks, lambda: started)


def test_optimizer_and_launcher_have_independent_repos_and_streams(ks):
    scan_done(ks)
    assert ksettings.repo("k-optimizer") != ksettings.repo("k-launcher")
    ks._goto("settings")
    ks._draw()
    repo_keys = [k for k, _ in ks._regions if k[0] == "repo"]
    assert {k[1] for k in repo_keys} == {"k-launcher", "k-optimizer", "k-series"}


def test_choosing_an_optimizer_location_is_remembered(ks, monkeypatch, tmp_path):
    scan_done(ks)
    exe = tmp_path / "K-Optimizer.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(kapp.filedialog, "askopenfilename", lambda **k: str(exe))
    ks._goto("k-optimizer")
    ks._draw()
    assert click(ks, ("pick", "k-optimizer"))
    assert ksettings.optimizer_path() == exe
    assert pump(ks, lambda: any(p.path == exe for p in ks._products))


# --- being light: draw only on change, trim the working set -----------------------------------------------------
def draws_during(a, monkeypatch, frames=60):
    count = []
    original = a._draw
    monkeypatch.setattr(a, "_draw", lambda: (count.append(1), original())[1])
    pump(a, lambda: False, n=frames)
    return len(count)


def test_an_idle_hub_does_not_redraw_at_all(ks, monkeypatch):
    scan_done(ks)
    pump(ks, lambda: False, n=40)  # let the startup activity settle
    assert draws_during(ks, monkeypatch, frames=60) == 0


def test_the_hub_redraws_when_something_actually_changes(ks, monkeypatch):
    scan_done(ks)
    pump(ks, lambda: False, n=40)
    assert (ks._set_hover(("nav", "settings")) or draws_during(ks, monkeypatch, 15)) >= 1  # hover
    pump(ks, lambda: False, n=10)
    ks._goto("settings")
    assert draws_during(ks, monkeypatch, 15) >= 1                                           # page
    ks._message = "merhaba"
    assert draws_during(ks, monkeypatch, 15) >= 1                                           # message
    ks._theme_changed(theme.PALETTES["aurora"])
    assert draws_during(ks, monkeypatch, 15) >= 1                                           # theme
    ks._products = [launcher_product(running=True)]
    assert draws_during(ks, monkeypatch, 15) >= 1                                           # detection result


def test_the_scanning_animation_still_moves_while_it_is_scanning(ks, monkeypatch):
    scan_done(ks)
    pump(ks, lambda: False, n=40)
    ks._scanning = True
    ks._goto("home")
    assert draws_during(ks, monkeypatch, frames=120) >= 2  # the dots advance about three times a second
    ks._scanning = False


def test_a_click_that_changes_settings_is_repainted(ks, monkeypatch):
    scan_done(ks)
    ks._goto("settings")
    pump(ks, lambda: False, n=40)
    assert click(ks, ("flag", "auto_install"))
    assert draws_during(ks, monkeypatch, 15) >= 1


def test_it_trims_its_own_working_set_now_and_then_like_k_launcher_does(ks, monkeypatch):
    trimmed = []
    monkeypatch.setattr(kapp.trimmer, "empty_working_set", lambda pid: trimmed.append(pid) or True)
    ks._last_trim = 0.0
    ks._maybe_trim(10)
    assert trimmed == []
    ks._maybe_trim(20)
    assert trimmed == [os.getpid()]
    ks._maybe_trim(30)
    assert len(trimmed) == 1
    ks._maybe_trim(40)
    assert len(trimmed) == 2


def test_a_finished_update_is_no_longer_offered(ks, monkeypatch):
    scan_done(ks)
    ks._products = [optimizer_product()]
    ks._updates = {"k-optimizer": available("v1.0.1", "K-Optimizer.exe")}
    checked = []

    def fake_check(pid, repo, local, opener=None):
        checked.append((pid, local))
        return updater.Status("current")

    monkeypatch.setattr(kapp.products, "detect", lambda **kw: [optimizer_product(version="1.0.1.0")])
    monkeypatch.setattr(updater, "check", fake_check)
    ks._upd_done.put(("K-Optimizer v1.0.1 hazır.", False, 10))
    assert pump(ks, lambda: ("k-optimizer", "1.0.1.0") in checked)  # asked again, with the new installed version
    assert pump(ks, lambda: ks._updates.get("k-optimizer") and ks._updates["k-optimizer"].state == "current")
