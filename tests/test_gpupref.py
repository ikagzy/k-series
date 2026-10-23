import json
import uuid
import winreg

import pytest

from k_optimizer import gpupref

EXE = "C:\\Games\\Cool Game\\game.exe"


class FakeReg:
    """An in-memory stand-in for the registry key."""

    def __init__(self, **values):
        self.values = dict(values)
        self.fail = set()

    def get(self, name):
        return self.values.get(name)

    def set(self, name, data):
        if name in self.fail:
            raise OSError("denied")
        self.values[name] = data

    def delete(self, name):
        if name in self.fail:
            raise OSError("denied")
        self.values.pop(name, None)


def test_set_high_writes_the_exact_value_windows_settings_writes_and_reports_the_previous_one():
    reg = FakeReg()
    assert gpupref.set_high(EXE, reg) is None
    assert reg.values[EXE] == "GpuPreference=2;"
    assert gpupref.get(EXE, reg) == "GpuPreference=2;"


def test_an_existing_preference_is_returned_so_it_can_be_put_back():
    reg = FakeReg(**{EXE: "GpuPreference=1;"})
    assert gpupref.set_high(EXE, reg) == "GpuPreference=1;"
    assert reg.values[EXE] == "GpuPreference=2;"


def test_restore_deletes_the_value_when_there_was_none_and_rewrites_it_otherwise():
    reg = FakeReg(**{EXE: "GpuPreference=2;"})
    gpupref.restore(EXE, None, reg)
    assert EXE not in reg.values
    gpupref.restore(EXE, "GpuPreference=1;", reg)
    assert reg.values[EXE] == "GpuPreference=1;"


@pytest.mark.parametrize("bad", ["", "game.exe", "C:game.exe", "C:\\Games\\game.dll", "C:\\a\\b.exe\x00", "C:\\" + "x" * 300 + ".exe",
                                 "\\\\server\\share\\game.exe", "C:\\Games\\game.exe;GpuPreference=0",
                                 "C:\\Games\ngame.exe", "C:\\Games\tgame.exe", "C:\\Ga\x1fmes\\game.exe"])
def test_only_plain_absolute_exe_paths_are_accepted(bad):
    with pytest.raises(ValueError):
        gpupref.set_high(bad, FakeReg())


def test_the_store_remembers_the_first_previous_value_even_if_boosted_twice(tmp_path):
    reg = FakeReg(**{EXE: "GpuPreference=1;"})
    store = gpupref.Store(tmp_path / "g.json", reg)
    assert store.boost(EXE) is True
    assert store.boost(EXE) is True  # second click: already boosted, must not record "GpuPreference=2;" as original
    assert store.pending() == [EXE]
    assert store.restore_all() == 1
    assert reg.values[EXE] == "GpuPreference=1;"
    assert store.pending() == []


def test_the_store_survives_a_restart_because_it_is_on_disk(tmp_path):
    reg = FakeReg()
    gpupref.Store(tmp_path / "g.json", reg).boost(EXE)
    again = gpupref.Store(tmp_path / "g.json", reg)
    assert again.pending() == [EXE]
    again.restore_all()
    assert EXE not in reg.values


def test_boost_reports_failure_without_recording_anything(tmp_path):
    reg = FakeReg()
    reg.fail.add(EXE)
    store = gpupref.Store(tmp_path / "g.json", reg)
    assert store.boost(EXE) is False
    assert store.pending() == []
    assert store.boost("not a path") is False


def test_one_failing_restore_does_not_stop_the_others_and_stays_recorded(tmp_path):
    other = "C:\\Games\\Other\\other.exe"
    reg = FakeReg()
    store = gpupref.Store(tmp_path / "g.json", reg)
    store.boost(EXE)
    store.boost(other)
    reg.fail.add(EXE)
    assert store.restore_all() == 1
    assert other not in reg.values and reg.values[EXE] == "GpuPreference=2;"
    assert store.pending() == [EXE]
    reg.fail.clear()
    assert store.restore_all() == 1


def test_a_corrupt_record_file_is_treated_as_empty(tmp_path):
    f = tmp_path / "g.json"
    f.write_text("{bozuk")
    store = gpupref.Store(f, FakeReg())
    assert store.pending() == [] and store.restore_all() == 0
    f.write_text(json.dumps({"not": "a list"}))
    assert store.pending() == []


def test_the_real_registry_roundtrip_in_a_private_test_key_never_touching_windows_own_key():
    key = f"Software\\K-Optimizer-Tests\\{uuid.uuid4().hex}"
    reg = gpupref.WinRegistry(key)
    try:
        assert reg.get(EXE) is None
        assert gpupref.set_high(EXE, reg) is None
        assert reg.get(EXE) == "GpuPreference=2;"
        gpupref.restore(EXE, None, reg)
        assert reg.get(EXE) is None
        reg.delete(EXE)  # deleting something absent must not raise
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, "Software\\K-Optimizer-Tests")
        except OSError:
            pass


def test_the_default_registry_key_is_the_one_windows_graphics_settings_uses():
    assert gpupref.WinRegistry().key == "Software\\Microsoft\\DirectX\\UserGpuPreferences"
