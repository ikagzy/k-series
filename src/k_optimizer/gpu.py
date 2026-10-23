import json
import re
import subprocess
from dataclasses import dataclass

from k_optimizer.models import GpuAdapter

_PID_LUID = re.compile(r"pid_(\d+)_luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)")
_LUID = re.compile(r"luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)")
_ENGTYPE = re.compile(r"engtype_(\w+)")

# WMI class names are locale independent, unlike Get-Counter counter paths.
_SCRIPT = (
    "$e = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine "
    "| Select-Object Name,UtilizationPercentage; "
    "$p = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory "
    "| Select-Object Name,DedicatedUsage; "
    "$a = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory "
    "| Select-Object Name,DedicatedUsage; "
    "@{engine=@($e); process_memory=@($p); adapter_memory=@($a)} "
    "| ConvertTo-Json -Depth 4 -Compress"
)


@dataclass(frozen=True)
class GpuReading:
    per_pid_percent: dict[int, float]
    per_pid_vram: dict[int, int]
    adapters: tuple[GpuAdapter, ...]


def parse_engine(samples: dict[str, float]) -> tuple[dict[int, float], dict[str, float]]:
    per_pid: dict[int, float] = {}
    per_luid_type: dict[tuple[str, str], float] = {}
    for name, value in samples.items():
        m, t = _PID_LUID.search(name), _ENGTYPE.search(name)
        if not m or not t:
            continue
        pid, luid = int(m.group(1)), m.group(2)
        per_pid[pid] = per_pid.get(pid, 0.0) + float(value)
        key = (luid, t.group(1))
        per_luid_type[key] = per_luid_type.get(key, 0.0) + float(value)
    per_pid = {pid: min(v, 100.0) for pid, v in per_pid.items()}
    per_luid: dict[str, float] = {}
    for (luid, _), v in per_luid_type.items():
        per_luid[luid] = max(per_luid.get(luid, 0.0), min(v, 100.0))
    return per_pid, per_luid


def parse_process_memory(samples: dict[str, int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for name, value in samples.items():
        m = _PID_LUID.search(name)
        if m:
            pid = int(m.group(1))
            out[pid] = out.get(pid, 0) + int(value)
    return out


def parse_adapter_memory(samples: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, value in samples.items():
        m = _LUID.search(name)
        if m:
            out[m.group(1)] = out.get(m.group(1), 0) + int(value)
    return out


def _as_samples(rows, value_key: str) -> dict:
    if isinstance(rows, dict):
        rows = [rows]
    return {r["Name"]: r[value_key] for r in rows or [] if r.get("Name") is not None}


def read_gpu() -> GpuReading | None:
    try:
        run = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
        if run.returncode != 0:
            return None
        data = json.loads(run.stdout)
        per_pid, per_luid = parse_engine(_as_samples(data.get("engine"), "UtilizationPercentage"))
        vram = parse_process_memory(_as_samples(data.get("process_memory"), "DedicatedUsage"))
        adapter_mem = parse_adapter_memory(_as_samples(data.get("adapter_memory"), "DedicatedUsage"))
        luids = sorted(set(per_luid) | set(adapter_mem))
        adapters = tuple(
            GpuAdapter(luid, per_luid.get(luid, 0.0), adapter_mem.get(luid)) for luid in luids
        )
        return GpuReading(per_pid, vram, adapters)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None
