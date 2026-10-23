from k_optimizer import ui
from k_optimizer.models import GpuAdapter, Snapshot


def snap(adapters=(), used=8 * 1024**3, total=32 * 1024**3, cpu=12.0):
    return Snapshot(cpu, used, total, tuple(adapters), ())


def test_gauge_color_thresholds():
    assert ui.gauge_color(10) == ui.NEON
    assert ui.gauge_color(70) == ui.WARN
    assert ui.gauge_color(95) == ui.HOT


def test_summarize_without_gpu_marks_gpu_unavailable():
    out = ui.summarize(snap())
    assert out["gpu"][0] is None
    assert out["ram"][0] == 25.0
    assert out["ram"][1] == "8.0 GB / 32.0 GB"
    assert out["cpu"][0] == 12.0


def test_summarize_gpu_uses_busiest_adapter_and_largest_vram():
    gb = 1024**3
    out = ui.summarize(snap([GpuAdapter("a", 3.0, 4 * gb), GpuAdapter("b", 40.0, 0)]))
    assert out["gpu"] == (40.0, "VRAM 4.0 GB")
