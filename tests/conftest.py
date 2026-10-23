"""Safety net: no test may ever read or write the real K-Launcher settings.

K-Launcher is usually running on the developer's machine, so detection must not see it, and every
settings folder is redirected into a temporary directory.
"""
import pytest

from k_optimizer import klauncher, theme


@pytest.fixture(autouse=True)
def isolate_k_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "_local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "_roaming"))
    monkeypatch.setattr(klauncher, "running_exes", lambda: [])
    monkeypatch.setattr(klauncher, "running_pids", lambda: [])
    monkeypatch.setattr(klauncher, "running_optimizer_exes", lambda: [])
    monkeypatch.setattr(klauncher, "running_optimizer_pids", lambda: [])
    monkeypatch.setattr(klauncher, "default_scan_roots", lambda: [])
    theme.set_launcher_hint(None)
    yield
    theme.set_launcher_hint(None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test may reach the real GitHub: the update module's network opener always fails fast.
    (Tests that exercise downloads pass their own fake opener.)"""
    from urllib.error import URLError

    from k_series import updater

    def blocked(*args, **kwargs):
        raise URLError("network is blocked in tests")

    monkeypatch.setattr(updater, "urlopen", blocked)


@pytest.fixture(autouse=True)
def hidden_windows(monkeypatch):
    """Tests build real Tk windows; they must never appear on the developer's screen."""
    import tkinter

    original = tkinter.Tk.__init__

    def hidden_init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.withdraw()  # before the first update(), so it is never drawn

    monkeypatch.setattr(tkinter.Tk, "__init__", hidden_init)


@pytest.fixture(autouse=True)
def turkish_by_default(monkeypatch):
    """K-Series picks its language from the settings, else the system; tests start in Turkish on every machine."""
    from k_series import i18n

    monkeypatch.setattr(i18n, "system_default", lambda: "tr")
    i18n.set_language("tr")
    yield
    i18n.set_language("tr")
