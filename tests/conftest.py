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
    monkeypatch.setattr(klauncher, "default_scan_roots", lambda: [])
    theme.set_launcher_hint(None)
    yield
    theme.set_launcher_hint(None)
