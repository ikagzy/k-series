"""Reversible CPU/GPU relief: lower the scheduling priority of background hogs.

Nothing is closed. CPU: process priority class (+ EcoQoS efficiency mode). GPU: the
process GPU scheduling priority class (D3DKMT). The foreground app, our own process,
protected processes and GPU-heavy workloads (games) are never touched, and every change
is recorded so it can be put back.
"""
import ctypes
import json
import os
from collections.abc import Callable, Iterable, Sequence
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil

from k_optimizer.models import Level, ProcInfo

CPU_MIN_PERCENT = 1.0  # share of total CPU, i.e. roughly a quarter of one core on a 24-thread chip
GPU_MIN_PERCENT = 1.0
GAME_LIKE_GPU_PERCENT = 5.0  # a process this busy on the GPU is treated as a foreground workload

_GPU_BELOW_NORMAL = 1
_QUERY, _SET_INFO, _LIMITED = 0x0400, 0x0200, 0x1000
_POWER_THROTTLING = 4
_THROTTLE_EXEC_SPEED = 0x1


class _PowerThrottling(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]


class WinOps:
    """Thin Win32 wrapper; every call fails soft (None / False)."""

    def __init__(self):
        # Explicit argtypes: handles are 64-bit and ctypes defaults to 32-bit ints.
        k32, gdi = ctypes.windll.kernel32, ctypes.windll.gdi32
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        for fn in (k32.GetProcessInformation, k32.SetProcessInformation):
            fn.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        gdi.D3DKMTGetProcessSchedulingPriorityClass.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_int)]
        gdi.D3DKMTSetProcessSchedulingPriorityClass.argtypes = [wintypes.HANDLE, ctypes.c_int]

    def _open(self, pid: int):
        return ctypes.windll.kernel32.OpenProcess(_QUERY | _SET_INFO, False, pid) or None

    def _close(self, handle) -> None:
        ctypes.windll.kernel32.CloseHandle(handle)

    def create_time(self, pid: int) -> float | None:
        try:
            return psutil.Process(pid).create_time()
        except psutil.Error:
            return None

    def get_cpu(self, pid: int) -> int | None:
        try:
            return int(psutil.Process(pid).nice())
        except psutil.Error:
            return None

    def set_cpu(self, pid: int, cls: int) -> bool:
        try:
            psutil.Process(pid).nice(cls)
            return True
        except psutil.Error:
            return False

    def get_eco(self, pid: int) -> bool | None:
        h = self._open(pid)
        if not h:
            return None
        try:
            s = _PowerThrottling(1, 0, 0)
            ok = ctypes.windll.kernel32.GetProcessInformation(h, _POWER_THROTTLING, ctypes.byref(s), ctypes.sizeof(s))
            return bool(s.StateMask & _THROTTLE_EXEC_SPEED) if ok else None
        finally:
            self._close(h)

    def set_eco(self, pid: int, on: bool) -> bool:
        h = self._open(pid)
        if not h:
            return False
        try:
            s = _PowerThrottling(1, _THROTTLE_EXEC_SPEED, _THROTTLE_EXEC_SPEED if on else 0)
            return bool(ctypes.windll.kernel32.SetProcessInformation(h, _POWER_THROTTLING, ctypes.byref(s), ctypes.sizeof(s)))
        finally:
            self._close(h)

    def get_gpu(self, pid: int) -> int | None:
        h = self._open(pid)
        if not h:
            return None
        try:
            cls = ctypes.c_int(-1)
            status = ctypes.windll.gdi32.D3DKMTGetProcessSchedulingPriorityClass(h, ctypes.byref(cls))
            return cls.value if status == 0 else None
        finally:
            self._close(h)

    def set_gpu(self, pid: int, cls: int) -> bool:
        h = self._open(pid)
        if not h:
            return False
        try:
            return ctypes.windll.gdi32.D3DKMTSetProcessSchedulingPriorityClass(h, cls) == 0
        finally:
            self._close(h)


def foreground_pid() -> int | None:
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        return pid.value or None
    except (AttributeError, OSError):
        return None


def related_pids(pid: int) -> frozenset[int]:
    """The process, its ancestors and all its descendants (a game and its launcher/helpers)."""
    out = {pid}
    try:
        p = psutil.Process(pid)
        out |= {a.pid for a in p.parents()}
        out |= {c.pid for c in p.children(recursive=True)}
    except psutil.Error:
        pass
    return frozenset(out)


def pick_background(
    procs: Iterable[ProcInfo],
    classify: Callable[[ProcInfo], Level],
    own_pids: frozenset[int],
    exclude_pids: frozenset[int],
    kind: str,
    min_cpu: float = CPU_MIN_PERCENT,
) -> list[ProcInfo]:
    out = []
    for p in procs:
        if p.pid in own_pids or p.pid in exclude_pids or classify(p) is Level.PROTECTED:
            continue
        gpu = p.gpu_percent or 0.0
        if kind == "cpu" and p.cpu_percent >= min_cpu and gpu < GAME_LIKE_GPU_PERCENT:
            out.append(p)
        elif kind == "gpu" and gpu >= GPU_MIN_PERCENT:
            out.append(p)
    return out


@dataclass(frozen=True)
class Record:
    pid: int
    create_time: float
    name: str
    kind: str
    prev: int
    eco_was_on: bool = False


@dataclass(frozen=True)
class ThrottleReport:
    applied: tuple[ProcInfo, ...]
    skipped: tuple[tuple[ProcInfo, str], ...]


class Throttler:
    def __init__(self, store_path: Path, ops: WinOps | None = None):
        self._store = store_path
        self._ops = ops or WinOps()

    def _load(self) -> list[Record]:
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            return [Record(**d) for d in data] if isinstance(data, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def _save(self, records: Sequence[Record]) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._store.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(r) for r in records]), encoding="utf-8")
        os.replace(tmp, self._store)

    def pending(self) -> int:
        return len(self._load())

    def apply(self, procs: Sequence[ProcInfo], kind: str) -> ThrottleReport:
        ops = self._ops
        applied: list[ProcInfo] = []
        skipped: list[tuple[ProcInfo, str]] = []
        new: list[Record] = []
        for p in procs:
            ct = ops.create_time(p.pid)
            if ct is None:
                skipped.append((p, "süreç yok"))
                continue
            if abs(ct - p.create_time) > 0.01:
                skipped.append((p, "süreç değişmiş"))
                continue
            if kind == "cpu":
                prev = ops.get_cpu(p.pid)
                if prev is None:
                    skipped.append((p, "yetki gerekir"))
                    continue
                if prev in (psutil.BELOW_NORMAL_PRIORITY_CLASS, psutil.IDLE_PRIORITY_CLASS):
                    skipped.append((p, "zaten düşük"))
                    continue
                eco_was_on = bool(ops.get_eco(p.pid))
                if not ops.set_cpu(p.pid, psutil.BELOW_NORMAL_PRIORITY_CLASS):
                    skipped.append((p, "yetki gerekir"))
                    continue
                ops.set_eco(p.pid, True)
                new.append(Record(p.pid, ct, p.name, "cpu", prev, eco_was_on))
            else:
                prev = ops.get_gpu(p.pid)
                if prev is None:
                    skipped.append((p, "GPU önceliği okunamadı"))
                    continue
                if prev <= _GPU_BELOW_NORMAL:
                    skipped.append((p, "zaten düşük"))
                    continue
                if not ops.set_gpu(p.pid, _GPU_BELOW_NORMAL):
                    skipped.append((p, "yetki gerekir"))
                    continue
                new.append(Record(p.pid, ct, p.name, "gpu", prev))
            applied.append(p)
        if new:
            self._save(self._load() + new)
        return ThrottleReport(tuple(applied), tuple(skipped))

    def pending_pids(self, kind: str | None = None) -> set[int]:
        return {r.pid for r in self._load() if kind is None or r.kind == kind}

    def restore(self, kind: str | None = None, pids: set[int] | None = None) -> int:
        """Put back recorded values; limit to one kind and/or some pids, the rest stay recorded."""
        ops = self._ops
        restored = 0
        keep: list[Record] = []
        for r in self._load():
            if (kind is not None and r.kind != kind) or (pids is not None and r.pid not in pids):
                keep.append(r)
                continue
            ct = ops.create_time(r.pid)
            if ct is None or abs(ct - r.create_time) > 0.01:
                continue  # gone, or the pid now belongs to someone else
            if r.kind == "cpu":
                ok = ops.set_cpu(r.pid, r.prev)
                if not r.eco_was_on:
                    ops.set_eco(r.pid, False)
            else:
                ok = ops.set_gpu(r.pid, r.prev)
            restored += bool(ok)
        self._save(keep)
        return restored
