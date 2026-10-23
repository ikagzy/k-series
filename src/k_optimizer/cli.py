import argparse
import os
from collections.abc import Callable
from pathlib import Path

import psutil

from k_optimizer import classifier, monitor, trimmer, winutil
from k_optimizer.cleaner import Cleaner
from k_optimizer.models import Level, ProcInfo, Snapshot


def session_path() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "K-Optimizer" / "session.json"


def own_pids() -> frozenset[int]:
    pids = {os.getpid()}
    try:
        pids |= {p.pid for p in psutil.Process().parents()}
    except psutil.Error:
        pass
    return frozenset(pids)


def make_classify(known: classifier.KnownApps) -> Callable[[ProcInfo], Level]:
    own = own_pids()
    return lambda p: classifier.classify(p, known, own)


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.0f} MB"


def _gpu(p: ProcInfo) -> str:
    return "-" if p.gpu_percent is None else f"{p.gpu_percent:.0f}%"


def main(
    argv: list[str] | None = None,
    *,
    snapshot_fn: Callable[[], Snapshot] = monitor.snapshot_after,
    cleaner: Cleaner | None = None,
    known_path: Path | None = None,
    trim_fn: Callable[[list[int]], int] = trimmer.trim_all,
) -> int:
    ap = argparse.ArgumentParser(prog="k_optimizer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    c = sub.add_parser("close")
    c.add_argument("--pids", required=True)
    c.add_argument("--yes", action="store_true")
    sub.add_parser("restore")
    sub.add_parser("boost")
    args = ap.parse_args(argv)

    known = (
        classifier.KnownApps.load(known_path, None) if known_path else classifier.default_known_apps()
    )
    classify = make_classify(known)
    cleaner = cleaner or Cleaner(session_path(), classify)

    if args.cmd == "restore":
        r = cleaner.restore()
        print(f"Geri açılan: {', '.join(r.started) or '-'}")
        for name, err in r.failed:
            print(f"Açılamadı: {name} ({err})")
        return 0

    snap = snapshot_fn()
    if args.cmd == "boost":
        targets = classifier.safe_targets(snap.processes, known, own_pids(), None, winutil.visible_window_pids())
        if targets:
            r = cleaner.close(targets)
            freed = sum(p.rss_bytes for p in r.closed)
            print(f"Kapatılan Windows bileşenleri: {', '.join(sorted({p.name for p in r.closed})) or '-'} (~{_mb(freed)} RAM)")
            for p, why in r.skipped:
                print(f"Atlanan: {p.name} ({why})")
        else:
            print("Kapatılacak gereksiz Windows bileşeni yok.")
        print(f"Bellek sıkıştırılan süreç: {trim_fn([p.pid for p in snap.processes])}")
        return 0
    listed = [(p, classify(p)) for p in snap.processes]
    listed = [(p, lv) for p, lv in listed if lv is not Level.PROTECTED]

    if args.cmd == "scan":
        listed.sort(key=lambda t: t[0].rss_bytes, reverse=True)
        print(f"{'PID':>7}  {'Ad':<28} {'CPU':>6} {'RAM':>9} {'GPU':>5}  Seviye")
        for p, lv in listed:
            print(f"{p.pid:>7}  {p.name[:28]:<28} {p.cpu_percent:>5.1f}% {_mb(p.rss_bytes):>9} {_gpu(p):>5}  {lv.value}")
        return 0

    by_pid = {p.pid: p for p, _ in listed}
    try:
        wanted = [int(x) for x in args.pids.split(",") if x.strip()]
    except ValueError:
        print("--pids sayı listesi olmalı (ör. 12,34)")
        return 1
    missing = [pid for pid in wanted if pid not in by_pid]
    if missing:
        print(f"Kapatılamaz veya listede yok: {', '.join(map(str, missing))}")
        return 1
    chosen = [by_pid[pid] for pid in wanted]
    if not args.yes:
        total = sum(p.rss_bytes for p in chosen)
        if input(f"{len(chosen)} süreç kapatılacak (~{_mb(total)} RAM). Onaylıyor musun? [e/H] ").strip().lower() not in ("e", "evet", "y"):
            return 1
    r = cleaner.close(chosen)
    print(f"Kapatılan: {', '.join(p.name for p in r.closed) or '-'}")
    for p, why in r.skipped:
        print(f"Atlanan: {p.name} ({why})")
    return 0
