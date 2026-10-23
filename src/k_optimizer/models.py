from dataclasses import dataclass
from enum import Enum


class Level(str, Enum):
    PROTECTED = "protected"
    SAFE = "safe"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str
    exe: str | None
    cmdline: tuple[str, ...]
    create_time: float
    cpu_percent: float
    rss_bytes: int
    gpu_percent: float | None
    vram_bytes: int | None


@dataclass(frozen=True)
class GpuAdapter:
    luid: str
    utilization: float
    dedicated_used_bytes: int | None


@dataclass(frozen=True)
class Snapshot:
    cpu_percent: float
    ram_used_bytes: int
    ram_total_bytes: int
    adapters: tuple[GpuAdapter, ...]
    processes: tuple[ProcInfo, ...]
