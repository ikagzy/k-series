import os
import struct

import psutil

from k_optimizer import procscan

BASE = 0x10000


def entry(pid, ppid, name, create=116444736000000000 + 10**7 * 100, user=10**7, kernel=2 * 10**7, ws=50 * 1024 * 1024,
          name_at=None, next_offset=0):
    """One SYSTEM_PROCESS_INFORMATION record (x64 layout) followed by its UTF-16 image name."""
    rec = bytearray(256)
    name_bytes = name.encode("utf-16-le")
    struct.pack_into("<II", rec, 0, next_offset, 3)
    struct.pack_into("<qqq", rec, 32, create, user, kernel)
    struct.pack_into("<HH", rec, 56, len(name_bytes), len(name_bytes) + 2)
    struct.pack_into("<Q", rec, 64, name_at if name_at is not None else 0)
    struct.pack_into("<QQ", rec, 80, pid, ppid)
    struct.pack_into("<Q", rec, 144, ws)
    return rec, name_bytes


def build(entries):
    """Lay out records back to back, each followed by its name; returns (raw bytes, base address)."""
    raw = bytearray()
    offsets = []
    for pid, ppid, name, kw in entries:
        offsets.append(len(raw))
        raw += bytes(256)
        raw += name.encode("utf-16-le")
        while len(raw) % 8:
            raw += b"\x00"
    for i, (pid, ppid, name, kw) in enumerate(entries):
        start = offsets[i]
        nxt = (offsets[i + 1] - start) if i + 1 < len(entries) else 0
        name_off = start + 256
        rec, _ = entry(pid, ppid, name, name_at=BASE + name_off if name else 0, next_offset=nxt, **kw)
        raw[start:start + 256] = rec
    return bytes(raw), BASE


def test_parse_reads_every_field_of_each_record():
    raw, base = build([
        (4, 0, "System", {"ws": 8 * 1024 * 1024}),
        (123, 4, "chrome.exe", {"ws": 300 * 1024 * 1024, "user": 5 * 10**7, "kernel": 5 * 10**7,
                                "create": 116444736000000000 + 10**7 * 1000}),
    ])
    got = procscan.parse(raw, base)
    assert [p.pid for p in got] == [4, 123]
    p = got[1]
    assert (p.ppid, p.name, p.working_set) == (4, "chrome.exe", 300 * 1024 * 1024)
    assert p.cpu_100ns == 10**8
    assert p.create_time == 1000.0  # FILETIME -> unix seconds


def test_a_process_without_a_name_is_named_idle_for_pid_zero_and_empty_otherwise():
    raw, base = build([(0, 0, "", {}), (9, 4, "", {})])
    got = procscan.parse(raw, base)
    assert got[0].name == "System Idle Process" and got[1].name == ""


def test_a_truncated_or_corrupt_buffer_returns_what_could_be_read_and_never_raises():
    raw, base = build([(1, 0, "a.exe", {}), (2, 1, "b.exe", {}), (3, 1, "c.exe", {})])
    assert [p.pid for p in procscan.parse(raw[:256 + 20], base)] == [1]  # the first record is intact, the rest is cut
    assert procscan.parse(b"", base) == []
    assert procscan.parse(b"\x01" * 40, base) == []
    garbage = bytearray(raw)
    struct.pack_into("<I", garbage, 0, 10**9)  # NextEntryOffset pointing far outside the buffer
    assert [p.pid for p in procscan.parse(bytes(garbage), base)] == [1]


def test_a_name_pointer_outside_the_buffer_is_ignored_not_dereferenced():
    raw, base = build([(7, 0, "x.exe", {})])
    bad = bytearray(raw)
    struct.pack_into("<Q", bad, 64, 0xDEAD0000)  # not inside [base, base+len)
    assert procscan.parse(bytes(bad), base)[0].name == ""


def test_the_live_scan_agrees_with_psutil_about_this_very_process():
    me = psutil.Process(os.getpid())
    found = {p.pid: p for p in procscan.scan()}
    p = found[me.pid]
    assert p.name.lower() == me.name().lower()
    assert p.ppid == me.ppid()
    assert abs(p.create_time - me.create_time()) < 2.0
    assert 0.3 < p.working_set / me.memory_info().rss < 3.0
    assert len(found) > 20 and 4 in found


def test_the_live_scan_is_a_single_cheap_call():
    import time

    procscan.scan()
    t = time.perf_counter()
    for _ in range(20):
        procscan.scan()
    per_call = (time.perf_counter() - t) / 20
    assert per_call < 0.05, f"{per_call * 1000:.1f} ms per scan"  # psutil needed ~2500 ms of CPU for the same data
