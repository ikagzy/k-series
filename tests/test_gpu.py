import json
import subprocess

from k_optimizer import gpu

LUID = "0x00000000_0x0000A1B2"


def eng(pid, idx, typ):
    return f"pid_{pid}_luid_{LUID}_phys_0_eng_{idx}_engtype_{typ}"


def test_parse_engine_sums_engines_per_pid_and_caps_at_100():
    per_pid, _ = gpu.parse_engine({eng(1234, 0, "3D"): 70.0, eng(1234, 1, "3D"): 60.0})
    assert per_pid[1234] == 100.0


def test_parse_engine_adapter_utilization_is_max_engtype_sum():
    _, per_luid = gpu.parse_engine(
        {eng(1, 0, "3D"): 25.0, eng(2, 0, "3D"): 15.0, eng(1, 1, "VideoDecode"): 10.0}
    )
    assert per_luid[LUID] == 40.0


def test_parse_engine_ignores_malformed_names():
    per_pid, per_luid = gpu.parse_engine({"garbage": 5.0, eng(7, 0, "3D"): 1.0})
    assert per_pid == {7: 1.0}
    assert per_luid == {LUID: 1.0}


def test_parse_process_memory_sums_adapters_per_pid():
    samples = {
        f"pid_9_luid_{LUID}_phys_0": 100,
        "pid_9_luid_0x00000000_0x0000FFFF_phys_0": 200,
    }
    assert gpu.parse_process_memory(samples) == {9: 300}


def test_parse_adapter_memory_keyed_by_luid():
    assert gpu.parse_adapter_memory({f"luid_{LUID}_phys_0": 4096}) == {LUID: 4096}


def _fake_run(stdout="", returncode=0, exc=None):
    def run(*a, **k):
        if exc:
            raise exc
        return subprocess.CompletedProcess(a, returncode, stdout, "")

    return run


def test_read_gpu_returns_none_when_powershell_fails(monkeypatch):
    for fake in (
        _fake_run(exc=OSError("no powershell")),
        _fake_run(returncode=1),
        _fake_run(stdout="not json"),
    ):
        monkeypatch.setattr(subprocess, "run", fake)
        assert gpu.read_gpu() is None


def test_read_gpu_builds_reading_from_json(monkeypatch):
    payload = {
        "engine": [{"Name": eng(5, 0, "3D"), "UtilizationPercentage": 30}],
        "process_memory": {"Name": f"pid_5_luid_{LUID}_phys_0", "DedicatedUsage": 2048},
        "adapter_memory": [{"Name": f"luid_{LUID}_phys_0", "DedicatedUsage": 8192}],
    }
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps(payload)))
    r = gpu.read_gpu()
    assert r.per_pid_percent == {5: 30.0}
    assert r.per_pid_vram == {5: 2048}
    assert len(r.adapters) == 1
    assert r.adapters[0].luid == LUID
    assert r.adapters[0].utilization == 30.0
    assert r.adapters[0].dedicated_used_bytes == 8192


def test_read_gpu_spawns_powershell_without_a_console_window(monkeypatch):
    seen = {}

    def run(*a, **k):
        seen.update(k)
        return subprocess.CompletedProcess(a, 1, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    gpu.read_gpu()
    assert seen["creationflags"] & 0x08000000  # CREATE_NO_WINDOW


# --- caching: a PowerShell per snapshot was the heaviest thing the app did ---------------------------------
def test_cached_reading_is_reused_within_the_max_age_and_refreshed_after_it(monkeypatch):
    calls = []
    clock = {"t": 100.0}
    monkeypatch.setattr(gpu, "read_gpu", lambda: calls.append(1) or gpu.GpuReading({}, {}, ()))
    cache = gpu.GpuCache(max_age=4.0, now=lambda: clock["t"])
    first = cache.get()
    clock["t"] = 103.0
    assert cache.get() is first and len(calls) == 1
    clock["t"] = 104.5
    assert cache.get() is not first and len(calls) == 2


def test_a_failed_reading_is_also_cached_so_a_broken_wmi_is_not_hammered(monkeypatch):
    calls = []
    clock = {"t": 0.0}
    monkeypatch.setattr(gpu, "read_gpu", lambda: calls.append(1))
    cache = gpu.GpuCache(max_age=4.0, now=lambda: clock["t"])
    assert cache.get() is None and cache.get() is None
    assert len(calls) == 1
    clock["t"] = 5.0
    cache.get()
    assert len(calls) == 2


def test_monitor_snapshot_uses_the_shared_cache_by_default(monkeypatch):
    from k_optimizer import monitor

    calls = []
    monkeypatch.setattr(gpu, "read_gpu", lambda: calls.append(1))
    gpu.shared_cache.clear()
    monitor.snapshot()
    monitor.snapshot()
    assert len(calls) == 1
