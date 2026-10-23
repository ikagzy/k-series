"""Non-destructive RAM relief: shrink working sets so idle pages move to the standby list.

Nothing is closed; Windows pages memory back in on demand.
"""
import ctypes
from collections.abc import Callable, Iterable
from ctypes import wintypes

_QUERY_INFORMATION = 0x0400
_SET_QUOTA = 0x0100


def empty_working_set(pid: int) -> bool:
    try:
        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    except AttributeError:  # not Windows
        return False
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(_QUERY_INFORMATION | _SET_QUOTA, False, pid)
    if not handle:
        return False
    try:
        return bool(psapi.EmptyWorkingSet(handle))
    finally:
        k32.CloseHandle(handle)


def trim_all(pids: Iterable[int], empty: Callable[[int], bool] = empty_working_set) -> int:
    """Trim every pid we are allowed to; returns how many succeeded."""
    done = 0
    for pid in pids:
        try:
            if empty(pid):
                done += 1
        except OSError:
            continue
    return done
