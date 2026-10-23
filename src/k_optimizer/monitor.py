import time
from collections.abc import Callable

import psutil

from k_optimizer import gpu, procscan
from k_optimizer.models import ProcInfo, Snapshot


def _static_info(pid: int) -> tuple[str | None, tuple[str, ...]]:
    """exe path and command line: fixed for the life of a process, so looked up once and cached.
    A denied lookup gives (None, ()), which the classifier treats as untouchable."""
    exe, cmd = None, ()
    try:
        p = psutil.Process(pid)
    except (psutil.Error, OSError):
        return exe, cmd
    try:
        exe = p.exe() or None
    except (psutil.Error, OSError):
        pass
    try:
        cmd = tuple(p.cmdline())
    except (psutil.Error, OSError):
        pass
    return exe, cmd


class ProcessTable:
    """The process list as ProcInfo, cheaply.

    One system call lists every process (procscan); CPU % comes from the change in CPU time between two reads;
    the expensive per-process lookups (exe, command line) are cached and spread over the first few reads by a
    time budget, so a snapshot never stalls. A process whose lookup is still pending shows exe=None, which makes
    it untouchable until it is resolved."""

    def __init__(self, scan: Callable = procscan.scan, info: Callable = _static_info,
                 clock: Callable[[], float] = time.monotonic, cores: int | None = None, budget_s: float = 0.15):
        self._scan, self._info, self._clock = scan, info, clock
        self._cores = cores or psutil.cpu_count() or 1
        self._budget = budget_s
        self._static: dict[int, tuple[float, str | None, tuple[str, ...]]] = {}
        self._prev: dict[int, tuple[float, int]] = {}
        self._prev_t: float | None = None

    @property
    def primed(self) -> bool:
        """True once a reading exists to measure CPU change against."""
        return self._prev_t is not None

    def read(self) -> list[ProcInfo]:
        try:
            raws = self._scan()
        except (OSError, AttributeError):
            return self._read_psutil()
        now = self._clock()
        dt = now - self._prev_t if self._prev_t is not None else None
        deadline = now + self._budget
        out: list[ProcInfo] = []
        static: dict[int, tuple[float, str | None, tuple[str, ...]]] = {}
        prev: dict[int, tuple[float, int]] = {}
        for r in raws:
            if r.pid == 0:
                continue
            known = self._static.get(r.pid)
            if known is not None and abs(known[0] - r.create_time) < 0.01:
                static[r.pid] = known
                exe, cmd = known[1], known[2]
            elif self._clock() < deadline:
                exe, cmd = self._info(r.pid)
                static[r.pid] = (r.create_time, exe, cmd)
            else:
                exe, cmd = None, ()  # not looked up yet; retried on the next read
            pct = 0.0
            before = self._prev.get(r.pid)
            if dt and dt > 0 and before and abs(before[0] - r.create_time) < 0.01 and r.cpu_100ns >= before[1]:
                pct = (r.cpu_100ns - before[1]) / 1e7 / dt / self._cores * 100
            prev[r.pid] = (r.create_time, r.cpu_100ns)
            out.append(ProcInfo(r.pid, r.name, exe, cmd, r.create_time, pct, r.working_set, None, None))
        self._static, self._prev, self._prev_t = static, prev, now
        return out

    def _read_psutil(self) -> list[ProcInfo]:
        """Slow fallback for when the native call is unavailable."""
        out = []
        for p in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time", "memory_info"], ad_value=None):
            try:
                info = p.info
                mem = info.get("memory_info")
                cpu = p.cpu_percent(None) / self._cores
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except psutil.AccessDenied:
                cpu, mem = 0.0, None
            out.append(ProcInfo(info["pid"], info.get("name") or "", info.get("exe"),
                                tuple(info.get("cmdline") or ()), info.get("create_time") or 0.0, cpu,
                                mem.rss if mem else 0, None, None))
        return out


_default_table = ProcessTable()


def snapshot(read_gpu_fn: Callable[[], gpu.GpuReading | None] | None = None,
             table: ProcessTable | None = None) -> Snapshot:
    reading = (read_gpu_fn or gpu.shared_cache.get)()
    procs = [
        ProcInfo(p.pid, p.name, p.exe, p.cmdline, p.create_time, p.cpu_percent, p.rss_bytes,
                 reading.per_pid_percent.get(p.pid, 0.0) if reading else None,
                 reading.per_pid_vram.get(p.pid, 0) if reading else None)
        for p in (table or _default_table).read()
    ]
    vm = psutil.virtual_memory()
    return Snapshot(
        cpu_percent=psutil.cpu_percent(None),
        ram_used_bytes=vm.used,
        ram_total_bytes=vm.total,
        adapters=reading.adapters if reading else (),
        processes=tuple(procs),
    )


def snapshot_after(interval: float = 0.5, read_gpu_fn: Callable[[], gpu.GpuReading | None] | None = None) -> Snapshot:
    """A reading with real CPU percentages: take a baseline, wait, then measure the change."""
    psutil.cpu_percent(None)
    _default_table.read()
    time.sleep(interval)
    return snapshot(read_gpu_fn)


def sample(interval: float = 0.5, read_gpu_fn: Callable[[], gpu.GpuReading | None] | None = None) -> Snapshot:
    """For polling in a loop: the previous reading is the baseline, so only the very first call has to wait."""
    if not _default_table.primed:
        psutil.cpu_percent(None)
        _default_table.read()
        time.sleep(interval)
    return snapshot(read_gpu_fn)
