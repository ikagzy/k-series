import struct

import pytest

from k_optimizer import icons, theme


def test_every_theme_has_a_ready_made_ico_with_standard_sizes():
    seen = set()
    for pal in theme.PALETTES.values():
        path = icons.icon_for(pal)
        assert path.name == f"{pal.id}.ico" and path.parent.name == "ko" and path.is_file(), pal.id
        raw = path.read_bytes()
        assert raw[:4] == b"\x00\x00\x01\x00"
        count = struct.unpack("<H", raw[4:6])[0]
        sizes = {raw[6 + 16 * i] or 256 for i in range(count)}
        assert {16, 32, 256} <= sizes, (pal.id, sizes)
        seen.add(raw)
    assert len(seen) == len(theme.PALETTES)  # seven different logos


def test_each_app_has_its_own_logo_and_k_launcher_keeps_its_theme_icons():
    pal = theme.PALETTES["amber-orange"]
    ko, ks, kl = (icons.icon_for(pal, a) for a in ("ko", "ks", "kl"))
    assert ko.parent.name == "ko" and ks.parent.name == "ks" and kl.parent.name == "kl"
    assert len({ko.read_bytes(), ks.read_bytes(), kl.read_bytes()}) == 3


def test_unknown_theme_falls_back_to_the_default_icon():
    odd = theme.Palette("nope", "Nope", *["#000000"] * 7)
    assert icons.icon_for(odd).name == "klauncher.ico"


def test_shortcut_icon_is_copied_once_per_theme_under_a_distinct_name(tmp_path):
    a = icons.shortcut_icon(tmp_path / "ThemeIcons", theme.PALETTES["amber-orange"])
    b = icons.shortcut_icon(tmp_path / "ThemeIcons", theme.PALETTES["aurora"])
    assert a != b and a.name == "amber-orange.ico" and b.name == "aurora.ico"
    assert a.read_bytes() == icons.icon_for(theme.PALETTES["amber-orange"]).read_bytes()
    stamp = a.stat().st_mtime_ns
    assert icons.shortcut_icon(tmp_path / "ThemeIcons", theme.PALETTES["amber-orange"]) == a
    assert a.stat().st_mtime_ns == stamp  # reused, not rewritten


def test_window_icon_is_applied_and_follows_the_theme():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    try:
        assert icons.apply_window_icon(root, theme.PALETTES["amber-orange"]) is True
        assert icons.current_icon_key(root) == "amber-orange"
        assert icons.apply_window_icon(root, theme.PALETTES["aurora"]) is True
        assert icons.current_icon_key(root) == "aurora"
    finally:
        root.destroy()


def test_png_layer_extracts_the_closest_size_from_the_ico():
    import struct

    pal = theme.PALETTES["amber-orange"]
    for want, expect in ((64, 64), (128, 128), (100, 128), (10, 16), (5000, 256)):
        data = icons.png_layer(pal, want)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", data[16:24])
        assert (w, h) == (expect, expect), (want, w)


def test_png_layer_of_a_broken_ico_is_none(tmp_path, monkeypatch):
    bad = tmp_path / "amber-orange.ico"
    bad.write_bytes(b"not an icon")
    monkeypatch.setattr(icons, "THEME_ICONS", tmp_path)
    monkeypatch.setattr(icons, "APP_ICONS", tmp_path / "none")
    assert icons.png_layer(theme.PALETTES["amber-orange"], 64) is None


def test_photo_returns_a_tk_image_of_the_theme_logo_and_caches_it():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no Tk display: {e}")
    try:
        a = icons.photo(root, theme.PALETTES["aurora"], 64)
        assert (a.width(), a.height()) == (64, 64)
        assert icons.photo(root, theme.PALETTES["aurora"], 64) is a
        assert icons.photo(root, theme.PALETTES["midnight"], 64) is not a
    finally:
        root.destroy()
