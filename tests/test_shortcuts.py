from pathlib import Path

from k_series import shortcuts


def test_create_passes_paths_through_the_environment_not_the_script(tmp_path):
    seen = {}

    def runner(script, env):
        seen["script"], seen["env"] = script, env
        return True

    lnk = tmp_path / "klasörler" / "K-Series.lnk"
    target = tmp_path / "ürün" / "K-Series.exe"
    icon = tmp_path / "ThemeIcons" / "aurora-KS.ico"
    assert shortcuts.create(lnk, target, icon, runner=runner) is True
    assert "CreateShortcut" in seen["script"] and "IconLocation" in seen["script"]
    # user paths are never spliced into the script text (no quoting or injection problems)
    assert str(target) not in seen["script"] and "klasörler" not in seen["script"]
    assert seen["env"]["KS_LNK"] == str(lnk) and seen["env"]["KS_TARGET"] == str(target)
    assert seen["env"]["KS_ICON"].startswith(str(icon)) and seen["env"]["KS_WORKDIR"] == str(target.parent)


def test_create_makes_the_folder_and_reports_failure_without_raising(tmp_path):
    lnk = tmp_path / "a" / "b" / "K-Series.lnk"
    assert shortcuts.create(lnk, Path("C:/x/K-Series.exe"), Path("C:/x/i.ico"), runner=lambda s, e: False) is False
    assert lnk.parent.is_dir()

    def boom(script, env):
        raise OSError("powershell missing")

    assert shortcuts.create(lnk, Path("C:/x/K-Series.exe"), Path("C:/x/i.ico"), runner=boom) is False


def test_desktop_folder_is_a_real_path():
    assert isinstance(shortcuts.desktop_dir(), Path)
