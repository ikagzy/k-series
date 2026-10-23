from k_optimizer import theme


def test_all_seven_k_launcher_palettes_exist_with_source_values():
    assert set(theme.PALETTES) == {"emerald-cyan", "violet-pink", "blue-cyan", "amber-orange", "midnight", "aurora", "minimal"}
    a = theme.PALETTES["aurora"]
    assert (a.primary, a.secondary) == ("#4DFFBE", "#8E5BFF")
    assert (a.background, a.surface, a.card, a.control, a.outline) == (
        "#0C1117", "#101820", "#141E27", "#19252C", "#26383E")
    e = theme.PALETTES["emerald-cyan"]
    assert (e.primary, e.secondary, e.background) == ("#00FF66", "#00D9FF", "#101014")
    m = theme.PALETTES["midnight"]
    assert (m.primary, m.background, m.outline) == ("#70A6FF", "#0A0F1A", "#26364E")


def test_load_reads_theme_id_from_file_case_and_whitespace_insensitive(tmp_path):
    f = tmp_path / "theme.txt"
    f.write_text("  Aurora \n")
    assert theme.load(f).id == "aurora"


def test_load_falls_back_to_default_for_missing_unknown_or_unreadable(tmp_path):
    assert theme.load(tmp_path / "nope.txt").id == theme.DEFAULT_ID
    f = tmp_path / "theme.txt"
    f.write_text("not-a-theme")
    assert theme.load(f).id == theme.DEFAULT_ID
    f.write_bytes(b"\xff\xfe\x00bad")
    assert theme.load(f).id == theme.DEFAULT_ID


def test_blend_and_lerp_endpoints_and_midpoint():
    assert theme.blend("#000000", "#FFFFFF", 0.0) == "#000000"
    assert theme.blend("#000000", "#FFFFFF", 1.0) == "#FFFFFF"
    assert theme.blend("#000000", "#FFFFFF", 0.5) == "#808080"


def test_derived_tokens_follow_the_palette():
    p = theme.PALETTES["aurora"]
    assert theme.accent_soft(p) == theme.blend(p.background, p.primary, 0.14)
    assert theme.accent_line(p) == theme.blend(p.background, p.primary, 0.40)


def test_arc_colors_gradient_from_primary_to_secondary_and_danger_when_hot():
    p = theme.PALETTES["aurora"]
    cols = theme.arc_colors(0.5, p, segments=10)
    assert len(cols) == 5
    assert cols[0] == p.primary
    assert theme.arc_colors(0.0, p, segments=10) == []
    assert theme.arc_colors(0.95, p, segments=10) == [theme.DANGER] * 10


def test_motion_scale_reads_k_launcher_motion_setting(tmp_path):
    assert theme.motion_scale([tmp_path]) == 1.0
    (tmp_path / "motion.txt").write_text("Fast")
    assert theme.motion_scale([tmp_path]) == 0.55
    (tmp_path / "motion.txt").write_text("slow\n")
    assert theme.motion_scale([tmp_path]) == 1.6
    (tmp_path / "motion.txt").write_text("Off")
    assert theme.motion_scale([tmp_path]) == 0.0
    (tmp_path / "motion.txt").write_text("???")
    assert theme.motion_scale([tmp_path]) == 1.0
