from k_optimizer import autoram, optsettings

MB = 1024 * 1024


def test_nothing_happens_below_the_threshold():
    a = autoram.AutoRam(threshold=80, min_interval=60)
    assert a.due(0, 50.0) is False and a.due(1000, 79.9) is False


def test_runs_when_memory_use_reaches_the_threshold_then_waits_the_minimum_interval():
    a = autoram.AutoRam(threshold=80, min_interval=60)
    assert a.due(0, 85.0) is True
    a.record(0, freed_bytes=500 * MB)
    assert a.due(30, 90.0) is False       # too soon
    assert a.due(61, 90.0) is True        # after the interval, still high


def test_backs_off_when_cleaning_frees_next_to_nothing():
    a = autoram.AutoRam(threshold=80, min_interval=60, max_interval=240)
    a.record(0, freed_bytes=5 * MB)
    assert a.due(61, 95.0) is False       # interval doubled to 120 s
    assert a.due(121, 95.0) is True
    a.record(121, freed_bytes=0)
    assert a.due(121 + 239, 95.0) is False
    assert a.due(121 + 241, 95.0) is True  # capped at 240 s, never longer
    a.record(121 + 241, freed_bytes=0)
    assert a.due(121 + 241 + 241, 95.0) is True


def test_a_good_clean_resets_the_back_off():
    a = autoram.AutoRam(threshold=80, min_interval=60, max_interval=600)
    a.record(0, freed_bytes=0)
    a.record(200, freed_bytes=0)          # interval is now 240
    a.record(500, freed_bytes=400 * MB)   # a real result
    assert a.due(500 + 61, 90.0) is True


def test_threshold_can_change_while_running():
    a = autoram.AutoRam(threshold=80)
    assert a.due(0, 75.0) is False
    a.threshold = 70
    assert a.due(0, 75.0) is True


def test_settings_have_safe_defaults_roundtrip_and_tolerate_corruption(tmp_path):
    f = tmp_path / "s.json"
    assert optsettings.load(f) == {"auto_ram": False, "auto_ram_threshold": 80}
    assert optsettings.save({"auto_ram": True, "auto_ram_threshold": 90}, f) is True
    assert optsettings.load(f) == {"auto_ram": True, "auto_ram_threshold": 90}
    f.write_text("{bozuk")
    assert optsettings.load(f) == {"auto_ram": False, "auto_ram_threshold": 80}


def test_settings_reject_nonsense_values(tmp_path):
    f = tmp_path / "s.json"
    optsettings.save({"auto_ram": "yes", "auto_ram_threshold": 5}, f)
    assert optsettings.load(f) == {"auto_ram": False, "auto_ram_threshold": 80}
    optsettings.save({"auto_ram": True, "auto_ram_threshold": 99}, f)
    assert optsettings.load(f)["auto_ram_threshold"] == 80  # out of the 60-95 range
    optsettings.save({"auto_ram_threshold": "high"}, f)
    assert optsettings.load(f)["auto_ram_threshold"] == 80


def test_threshold_choices_cycle():
    assert [optsettings.next_threshold(t) for t in (70, 80, 90)] == [80, 90, 70]
    assert optsettings.next_threshold(85) == 70  # an unknown value restarts the cycle
