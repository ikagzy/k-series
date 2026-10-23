"""The whole process table in one system call.

psutil on Windows asks the OS about every process separately, and each of those calls itself enumerates all
processes (about 6 ms each): a full snapshot cost ~2.5 s of CPU. NtQuerySystemInformation(SystemProcessInformation)
returns every process, with its name, parent, creation time, CPU time and working set, in a single ~4 ms call.
The x64 record layout used below was checked field by field against psutil on a live system.
"""
import ctypes
import struct
from ctypes import wintypes
from dataclasses import dataclass

_SYSTEM_PROCESS_INFORMATION = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
_FILETIME_TO_UNIX = 11644473600  # seconds between 1601-01-01 and 1970-01-01
_RECORD_MIN = 152  # up to and including WorkingSetSize at offset 144


@dataclass(frozen=True)
class RawProc:
    pid: int
    ppid: int
    name: str
    create_time: float   # unix seconds, the same value psutil reports
    cpu_100ns: int       # user + kernel time in 100 ns units
    working_set: int     # bytes


def parse(raw: bytes, base_address: int) -> list[RawProc]:
    """Decode the record chain. `base_address` is where `raw` lived in memory: image-name pointers are
    absolute addresses into that same buffer. Never raises; a damaged buffer yields what was readable."""
    out: list[RawProc] = []
    off, limit = 0, len(raw)
    while off + _RECORD_MIN <= limit:
        try:
            nxt = struct.unpack_from("<I", raw, off)[0]
            create, user, kernel = struct.unpack_from("<qqq", raw, off + 32)
            name_len = struct.unpack_from("<H", raw, off + 56)[0]
            name_ptr = struct.unpack_from("<Q", raw, off + 64)[0]
            pid, ppid = struct.unpack_from("<QQ", raw, off + 80)
            working_set = struct.unpack_from("<Q", raw, off + 144)[0]
        except struct.error:
            break
        name = ""
        start = name_ptr - base_address
        if name_ptr and 0 <= start and start + name_len <= limit and name_len % 2 == 0:
            name = raw[start:start + name_len].decode("utf-16-le", "replace")
        elif pid == 0:
            name = "System Idle Process"
        if pid == 0 and not name:
            name = "System Idle Process"
        out.append(RawProc(pid, ppid, name, create / 1e7 - _FILETIME_TO_UNIX, user + kernel, working_set))
        if nxt == 0 or off + nxt >= limit or off + nxt <= off:
            break
        off += nxt
    return out


def scan() -> list[RawProc]:
    """Every process on the machine, right now. Raises OSError if the system call fails."""
    ntdll = ctypes.windll.ntdll
    ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                               ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQuerySystemInformation.restype = ctypes.c_long
    size = 1 << 20
    for _ in range(6):
        buf = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG()
        status = ntdll.NtQuerySystemInformation(_SYSTEM_PROCESS_INFORMATION, buf, size, ctypes.byref(needed))
        if status == 0:
            return parse(buf.raw, ctypes.addressof(buf))
        if status & 0xFFFFFFFF == _STATUS_INFO_LENGTH_MISMATCH:
            size = max(needed.value + (1 << 16), size * 2)  # the table grew between the two calls
            continue
        raise OSError(f"NtQuerySystemInformation failed: {status & 0xFFFFFFFF:#x}")
    raise OSError("the process table kept growing")
