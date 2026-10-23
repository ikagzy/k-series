import dataclasses

import pytest

from k_optimizer.models import Level, ProcInfo


def test_level_values_and_procinfo_is_immutable():
    assert Level.SAFE.value == "safe"
    assert Level.PROTECTED.value == "protected"
    assert Level.UNKNOWN.value == "unknown"
    p = ProcInfo(1, "a.exe", None, (), 0.0, 0.0, 0, None, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.pid = 5
