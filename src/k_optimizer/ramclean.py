"""RAM cleaning in the order the best-known cleaners (Mem Reduct, Wise Memory Optimizer, RAMMap) use.

1. empty process working sets          (any user)
2. flush the system file cache         (needs SeIncreaseQuotaPrivilege, i.e. admin)
3. flush the modified page list        (needs SeProfileSingleProcessPrivilege, i.e. admin)
4. purge the low-priority standby list (admin)
5. purge the whole standby list        (admin, only when free memory is still low: dropping the
                                        whole file cache otherwise just costs disk reads later)

Each step is independent: one failing never stops the others. Without admin only step 1 runs.
"""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

import psutil

from k_optimizer import trimmer

# SYSTEM_MEMORY_LIST_COMMAND values for NtSetSystemInformation(SystemMemoryListInformation = 80)
FLUSH_MODIFIED = 3
PURGE_STANDBY = 4
PURGE_LOW_STANDBY = 5

LOW_MEMORY_FRACTION = 0.10
_SYSTEM_MEMORY_LIST_INFORMATION = 80
# Measured on a real machine: trimming processes that are active (cpu >= 0.1%) hands the memory back within
# seconds (they fault it straight in again, 178% of what was trimmed), while idle ones keep ~80% of it freed.
COLD_CPU_PERCENT = 0.1
COLD_GPU_PERCENT = 0.5
COLD_MIN_RSS = 8 * 1024 * 1024
_NEVER_TRIM = frozenset({"memcompression", "system", "registry", "secure system"})
_STEP_LABELS = {
    "working_sets": "çalışma kümeleri",
    "file_cache": "sistem önbelleği",
    "modified": "değiştirilmiş sayfalar",
    "low_standby": "düşük öncelikli bekleme listesi",
    "standby": "bekleme listesi",
}


def cold_pids(procs, exclude_pids=frozenset(), own_pids=frozenset()) -> list[int]:
    """Idle background processes worth trimming: the freed memory stays freed."""
    return [
        p.pid for p in procs
        if p.pid not in exclude_pids and p.pid not in own_pids
        and p.name.lower() not in _NEVER_TRIM
        and p.cpu_percent < COLD_CPU_PERCENT and (p.gpu_percent or 0) < COLD_GPU_PERCENT
        and p.rss_bytes >= COLD_MIN_RSS
    ]


class _Luid(ctypes.Structure):
    _fields_ = [("Low", wintypes.DWORD), ("High", wintypes.LONG)]


class _LuidAndAttributes(ctypes.Structure):
    _fields_ = [("Luid", _Luid), ("Attributes", wintypes.DWORD)]


class _TokenPrivileges(ctypes.Structure):
    _fields_ = [("Count", wintypes.DWORD), ("Privileges", _LuidAndAttributes * 1)]


class WinMemOps:
    def total_bytes(self) -> int:
        return psutil.virtual_memory().total

    def available_bytes(self) -> int:
        return psutil.virtual_memory().available

    def is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def _enable(self, name: str) -> bool:
        try:
            # Explicit argtypes: handles are 64-bit, and GetCurrentProcess() returns -1 (a pseudo handle)
            # which ctypes would otherwise try to squeeze into a 32-bit int.
            adv = ctypes.WinDLL("advapi32", use_last_error=True)
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            k32.GetCurrentProcess.argtypes = []
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
            adv.OpenProcessToken.restype = wintypes.BOOL
            adv.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(_Luid)]
            adv.LookupPrivilegeValueW.restype = wintypes.BOOL
            adv.AdjustTokenPrivileges.argtypes = [
                wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(_TokenPrivileges),
                wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
            ]
            adv.AdjustTokenPrivileges.restype = wintypes.BOOL
            token = wintypes.HANDLE()
            if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(token)):
                return False
            try:
                luid = _Luid()
                if not adv.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
                    return False
                tp = _TokenPrivileges(1, (_LuidAndAttributes * 1)(_LuidAndAttributes(luid, 0x2)))
                ctypes.set_last_error(0)
                adv.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
                return ctypes.get_last_error() == 0  # 1300 = privilege not held by this token
            finally:
                k32.CloseHandle(token)
        except (AttributeError, OSError, ctypes.ArgumentError, OverflowError):
            return False

    def enable_privileges(self) -> bool:
        a = self._enable("SeProfileSingleProcessPrivilege")
        b = self._enable("SeIncreaseQuotaPrivilege")
        return a and b

    def trim_working_sets(self, pids) -> int:
        return trimmer.trim_all(pids)

    def flush_file_cache(self) -> bool:
        try:
            neg = ctypes.c_size_t(-1)
            return bool(ctypes.windll.kernel32.SetSystemFileCacheSize(neg, neg, 0))
        except (AttributeError, OSError):
            return False

    def memory_list(self, command: int) -> bool:
        try:
            cmd = ctypes.c_int(command)
            status = ctypes.windll.ntdll.NtSetSystemInformation(
                _SYSTEM_MEMORY_LIST_INFORMATION, ctypes.byref(cmd), ctypes.sizeof(cmd)
            )
            return status == 0
        except (AttributeError, OSError):
            return False


@dataclass(frozen=True)
class RamReport:
    trimmed: int
    freed_bytes: int
    admin: bool
    steps: dict[str, bool] = field(default_factory=dict)

    def summary(self) -> str:
        done = [_STEP_LABELS[k] for k, ok in self.steps.items() if ok]
        failed = [_STEP_LABELS[k] for k, ok in self.steps.items() if not ok]
        text = (f"~{self.freed_bytes / 1024**2:.0f} MB RAM boşaldı ({self.trimmed} boşta süreç) "
                f"· temizlenen: {', '.join(done) or '-'}")
        if failed:
            text += f" · başarısız: {', '.join(failed)}"
        if not self.admin:
            text += " · tam temizlik için yönetici olarak aç"
        return text


class RamCleaner:
    def __init__(self, ops: WinMemOps | None = None):
        self._ops = ops or WinMemOps()

    @staticmethod
    def _attempt(step) -> bool:
        try:
            return bool(step())
        except Exception:  # one broken step must never stop the others
            return False

    def clean(self, pids) -> RamReport:
        ops = self._ops
        before = ops.available_bytes()
        steps: dict[str, bool] = {}
        admin = ops.is_admin()
        privileged = admin and self._attempt(ops.enable_privileges)
        trimmed = ops.trim_working_sets(pids)
        steps["working_sets"] = True
        if privileged:
            steps["file_cache"] = self._attempt(ops.flush_file_cache)
            steps["modified"] = self._attempt(lambda: ops.memory_list(FLUSH_MODIFIED))
            steps["low_standby"] = self._attempt(lambda: ops.memory_list(PURGE_LOW_STANDBY))
            if ops.available_bytes() < LOW_MEMORY_FRACTION * ops.total_bytes():
                steps["standby"] = self._attempt(lambda: ops.memory_list(PURGE_STANDBY))
        after = ops.available_bytes()
        return RamReport(trimmed, max(0, after - before), admin, steps)
