from k_optimizer import ui
from k_optimizer.models import GpuAdapter, Snapshot


def snap(adapters=(), used=8 * 1024**3, total=32 * 1024**3, cpu=12.0):
    return Snapshot(cpu, used, total, tuple(adapters), ())


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


def test_round_rect_points_has_twelve_corner_points():
    pts = ui.round_rect_points(0, 0, 100, 50, 10)
    assert len(pts) == 24 and min(pts[0::2]) == 0 and max(pts[0::2]) == 100


def test_gauge_animates_towards_target_and_snaps_when_motion_is_off():
    g = ui.Gauge("ram", "RAM")
    g.set(80.0, "x")
    g.tick(1.0)
    assert 0 < g.shown < 80
    g.tick(0.0)
    assert g.shown == 80.0


def test_unavailable_gauge_reports_no_percent():
    g = ui.Gauge("gpu", "GPU")
    g.set(None, "okunamıyor")
    assert g.available is False and g.target == 0.0
