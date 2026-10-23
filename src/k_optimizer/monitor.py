import time
from collections.abc import Callable

import psutil

from k_optimizer import gpu
from k_optimizer.models import ProcInfo, Snapshot

_ATTRS = ["pid", "name", "exe", "cmdline", "create_time", "memory_info"]
_CPUS = psutil.cpu_count() or 1


def snapshot(read_gpu_fn: Callable[[], gpu.GpuReading | None] | None = None) -> Snapshot:
    reading = (read_gpu_fn or gpu.read_gpu)()
    procs: list[ProcInfo] = []
    for p in psutil.process_iter(_ATTRS, ad_value=None):
        try:
            info = p.info
            mem = info.get("memory_info")
            # cpu_percent(None) compares against the previous call on this cached
            # Process object, so the first snapshot reports 0.0.
            cpu = p.cpu_percent(None) / _CPUS
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            cpu, mem = 0.0, None
        pid = info["pid"]
        procs.append(
            ProcInfo(
                pid=pid,
                name=info.get("name") or "",
                exe=info.get("exe"),
                cmdline=tuple(info.get("cmdline") or ()),
                create_time=info.get("create_time") or 0.0,
                cpu_percent=cpu,
                rss_bytes=mem.rss if mem else 0,
                gpu_percent=reading.per_pid_percent.get(pid, 0.0) if reading else None,
                vram_bytes=reading.per_pid_vram.get(pid, 0) if reading else None,
            )
        )
    vm = psutil.virtual_memory()
    return Snapshot(
        cpu_percent=psutil.cpu_percent(None),
        ram_used_bytes=vm.used,
        ram_total_bytes=vm.total,
        adapters=reading.adapters if reading else (),
        processes=tuple(procs),
    )


def snapshot_after(interval: float = 0.5) -> Snapshot:
    """Prime per-process CPU counters, wait, then snapshot so CPU values are real."""
    psutil.cpu_percent(None)
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(interval)
    return snapshot()
