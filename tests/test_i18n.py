import tkinter as tk
import types

import pytest

from k_series import app as kapp
from k_series import i18n, settings, updater


def test_english_swaps_known_phrases_and_leaves_the_rest_alone():
    i18n.set_language("en")
    assert i18n.t("Ayarlar") == "Settings"
    assert i18n.t("K-Optimizer: yeni sürüm v1.2") == "K-Optimizer: new version v1.2"
    assert i18n.t("Güncellemeler denetleniyor…") == "Checking for updates…"  # the long phrase beats "Güncelle"
    assert i18n.t("K-Series v1.0.0") == "K-Series v1.0.0"
    i18n.set_language("tr")
    assert i18n.t("Ayarlar") == "Ayarlar"


def test_unknown_language_codes_fall_back_to_turkish():
    i18n.set_language("de")
    assert i18n.current() == "tr"


def test_every_updater_message_has_an_english_text():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(updater.__file__).read_text(encoding="utf-8"))
    missing = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(c in node.value for c in "çğıöşüÇĞİÖŞÜ"):
            if node.value not in i18n._PAIRS:
                missing.append(node.value)
    assert not [m for m in missing if len(m) > 12 and not m.startswith('"""')], missing


@pytest.fixture
def ks(monkeypatch):
    monkeypatch.delenv("K_OPTIMIZER_PREVIEW", raising=False)
    monkeypatch.delenv("K_SERIES_PAGE", raising=False)
    try:
        a = kapp.KSeriesApp()
    except tk.TclError as e:
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


def drawn_text(a):
    c = a.canvas
    return [c.itemcget(i, "text") for i in c.find_all() if c.type(i) == "text"]


def test_the_language_dropdown_switches_and_remembers_the_language(ks):
    ks._goto("settings")
    ks._draw()
    assert "Ayarlar" in drawn_text(ks)
    assert click(ks, ("lang", "toggle")) and ks._lang_open
    ks._draw()
    assert click(ks, ("lang", "en")) and not ks._lang_open
    ks._draw()
    texts = drawn_text(ks)
    assert i18n.current() == "en" and "Settings" in texts and "Ayarlar" not in texts
    assert settings.load()["language"] == "en"
    again = kapp.KSeriesApp()
    try:
        assert i18n.current() == "en"  # the next start uses the saved language
    finally:
        again._close()


def test_clicking_elsewhere_closes_the_dropdown(ks):
    ks._goto("settings")
    ks._draw()
    click(ks, ("lang", "toggle"))
    ks._draw()
    assert ks._lang_open
    click(ks, ("motion", "fast"))
    assert not ks._lang_open
