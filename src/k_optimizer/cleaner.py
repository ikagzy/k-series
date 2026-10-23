import json
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil

from k_optimizer.models import Level, ProcInfo

_TERMINATE_TIMEOUT = 3


@dataclass(frozen=True)
class CloseReport:
    closed: tuple[ProcInfo, ...]
    skipped: tuple[tuple[ProcInfo, str], ...]


@dataclass(frozen=True)
class RestoreReport:
    started: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


def _launch(argv: list[str], cwd: str | None) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(
        argv, cwd=cwd, creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class Cleaner:
    def __init__(
        self,
        store_path: Path,
        classify: Callable[[ProcInfo], Level],
        get_process: Callable[[int], psutil.Process] = psutil.Process,
        launch: Callable[[list[str], str | None], None] = _launch,
    ):
        self._store = store_path
        self._classify = classify
        self._get_process = get_process
        self._launch = launch

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, entries: list[dict]) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._store.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._store)

    def pending(self) -> tuple[ProcInfo, ...]:
        out = []
        for d in self._load():
            try:
                out.append(ProcInfo(**{**d, "cmdline": tuple(d["cmdline"])}))
            except (TypeError, KeyError):
                continue
        return tuple(out)

    def close(self, procs: Sequence[ProcInfo]) -> CloseReport:
        closed: list[ProcInfo] = []
        skipped: list[tuple[ProcInfo, str]] = []
        for p in procs:
            if self._classify(p) is Level.PROTECTED:
                skipped.append((p, "korumalı"))
                continue
            try:
                proc = self._get_process(p.pid)
                if proc.create_time() != p.create_time:
                    skipped.append((p, "süreç değişmiş"))
                    continue
                proc.terminate()
                try:
                    proc.wait(_TERMINATE_TIMEOUT)
                except psutil.TimeoutExpired:
                    proc.kill()
                closed.append(p)
            except psutil.NoSuchProcess:
                skipped.append((p, "süreç yok"))
            except psutil.AccessDenied:
                skipped.append((p, "yetki gerekir"))
        if closed:
            self._save(self._load() + [asdict(p) for p in closed])
        return CloseReport(tuple(closed), tuple(skipped))

    def restore(self) -> RestoreReport:
        started: list[str] = []
        failed: list[tuple[str, str]] = []
        remaining: list[dict] = []
        for p in self.pending():
            argv = list(p.cmdline) or ([p.exe] if p.exe else [])
            cwd = os.path.dirname(p.exe) if p.exe else None
            try:
                if not argv:
                    raise OSError("başlatma komutu yok")
                self._launch(argv, cwd)
                started.append(p.name)
            except OSError as e:
                failed.append((p.name, str(e)))
                remaining.append(asdict(p))
        self._save(remaining)
        return RestoreReport(tuple(started), tuple(failed))
