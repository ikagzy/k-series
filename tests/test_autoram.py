from k_optimizer import autoram, optsettings


def test_the_first_clean_is_due_immediately_then_one_per_interval():
    a = autoram.AutoRam(interval=10)
    assert a.due(0) is True
    a.record(0)
    assert a.due(5) is False and a.due(9.9) is False
    assert a.due(10) is True
    a.record(10)
    assert a.due(15) is False and a.due(20) is True


def test_it_keeps_cleaning_at_the_same_pace_whatever_the_results():
    a = autoram.AutoRam(interval=10)
    for t in (0, 10, 20, 30, 40):
        assert a.due(t) is True
        a.record(t)  # no back-off: continuous means continuous


def test_the_interval_can_change_while_running():
    a = autoram.AutoRam(interval=60)
    a.record(0)
    assert a.due(30) is False
    a.interval = 5
    assert a.due(30) is True


def test_settings_have_safe_defaults_roundtrip_and_tolerate_corruption(tmp_path):
    f = tmp_path / "s.json"
    assert optsettings.load(f) == {"auto_ram": False, "auto_ram_interval": 10}
    assert optsettings.save({"auto_ram": True, "auto_ram_interval": 30}, f) is True
    assert optsettings.load(f) == {"auto_ram": True, "auto_ram_interval": 30}
    f.write_text("{bozuk")
    assert optsettings.load(f) == {"auto_ram": False, "auto_ram_interval": 10}


def test_settings_reject_nonsense_values_and_ignore_the_old_threshold_key(tmp_path):
    f = tmp_path / "s.json"
    optsettings.save({"auto_ram": "yes", "auto_ram_interval": 3}, f)
    assert optsettings.load(f) == {"auto_ram": False, "auto_ram_interval": 10}
    optsettings.save({"auto_ram": True, "auto_ram_interval": "fast"}, f)
    assert optsettings.load(f) == {"auto_ram": True, "auto_ram_interval": 10}
    optsettings.save({"auto_ram": True, "auto_ram_threshold": 90}, f)  # written by the previous version
    assert optsettings.load(f) == {"auto_ram": True, "auto_ram_interval": 10}


def test_interval_choices_cycle():
    assert [optsettings.next_interval(t) for t in (5, 10, 30, 60)] == [10, 30, 60, 5]
    assert optsettings.next_interval(7) == 10  # an unknown value goes back to the default
