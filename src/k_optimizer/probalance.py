"""Automatic CPU balancing in the style of Process Lasso's ProBalance.

The principle (Bitsum's documentation): while the system is under load, a *background* process that
keeps hogging the CPU gets its priority lowered one notch, so the foreground stays responsive; it gets
its priority back as soon as the condition passes. The foreground app and processes that are not causing
trouble are never touched. Nothing is closed and the process still gets all the CPU time nobody else needs.

Bitsum does not publish the numeric defaults, so the thresholds below are K-Optimizer's own choices.
"""
from collections.abc import Callable
from dataclasses import dataclass

import psutil

from k_optimizer import throttle
from k_optimizer.models import Level, ProcInfo, Snapshot

CORES = psutil.cpu_count() or 1
SYSTEM_THRESHOLD = 40.0   # % of the whole machine: only balance while it is genuinely busy
PROC_THRESHOLD = 35.0     # % of ONE core a background process must exceed. Per-core on purpose: one busy
                          # thread is only 100/CORES % of the machine (about 4% on 24 threads)
TIME_OVER = 3.0           # seconds it must stay over the threshold before it is restrained
RELEASE_SYSTEM = 30.0     # system load below this releases everything
RELEASE_PROC = 15.0       # % of one core: a restrained process below this has calmed down
HOLD = 6.0                # minimum seconds a restraint lasts, so priorities don't flap


def _core_percent(p: ProcInfo) -> float:
    return p.cpu_percent * CORES


@dataclass(frozen=True)
class Report:
    restrained: tuple[ProcInfo, ...] = ()
    released: tuple[int, ...] = ()


class ProBalance:
    def __init__(self, throttler: throttle.Throttler, classify: Callable[[ProcInfo], Level],
                 own_pids: frozenset[int]):
        self._throttler = throttler
        self._classify = classify
        self._own = own_pids
        self._over_since: dict[int, float] = {}
        self._restrained_at: dict[int, float] = {}

    def tick(self, now: float, snap: Snapshot, exclude_pids: frozenset[int]) -> Report:
        by_pid = {p.pid: p for p in snap.processes}
        released = self._release(now, snap.cpu_percent, by_pid, exclude_pids)
        restrained = self._restrain(now, snap, exclude_pids)
        return Report(tuple(restrained), tuple(released))

    def _restrain(self, now: float, snap: Snapshot, exclude: frozenset[int]) -> list[ProcInfo]:
        already = self._throttler.pending_pids("cpu")
        hogs = [
            p for p in throttle.pick_background(snap.processes, self._classify, self._own, exclude, "cpu",
                                                min_cpu=0.0)
            if _core_percent(p) >= PROC_THRESHOLD and p.pid not in already
        ]
        hot = {p.pid for p in hogs}
        self._over_since = {pid: t for pid, t in self._over_since.items() if pid in hot}
        for p in hogs:
            self._over_since.setdefault(p.pid, now)
        if snap.cpu_percent < SYSTEM_THRESHOLD:
            return []
        due = [p for p in hogs if now - self._over_since[p.pid] >= TIME_OVER]
        if not due:
            return []
        applied = self._throttler.apply(due, "cpu").applied
        for p in applied:
            self._restrained_at[p.pid] = now
            self._over_since.pop(p.pid, None)
        return list(applied)

    def _release(self, now: float, system: float, by_pid: dict[int, ProcInfo],
                 exclude: frozenset[int]) -> list[int]:
        due: set[int] = set()
        for pid in self._throttler.pending_pids("cpu"):
            since = self._restrained_at.setdefault(pid, now)  # restraint from an earlier session
            p = by_pid.get(pid)
            if p is None or pid in exclude:
                due.add(pid)  # gone, or the user switched to it: give its priority back right away
            elif now - since >= HOLD and (system < RELEASE_SYSTEM or _core_percent(p) < RELEASE_PROC):
                due.add(pid)
        if due:
            self._throttler.restore(kind="cpu", pids=due)
            for pid in due:
                self._restrained_at.pop(pid, None)
        return sorted(due)

    def release_all(self) -> int:
        n = self._throttler.restore(kind="cpu")
        self._restrained_at.clear()
        self._over_since.clear()
        return n
