from k_optimizer import ramclean

GB = 1024**3


class FakeOps:
    def __init__(self, admin=True, total=32 * GB, avail=(10 * GB, 12 * GB), fail=()):
        self.admin, self.total, self._avail = admin, total, list(avail)
        self.fail = set(fail)
        self.calls = []

    def total_bytes(self):
        return self.total

    def available_bytes(self):
        return self._avail.pop(0) if len(self._avail) > 1 else self._avail[0]

    def is_admin(self):
        return self.admin

    def enable_privileges(self):
        self.calls.append("privileges")
        return "privileges" not in self.fail

    def trim_working_sets(self, pids):
        self.calls.append("working_sets")
        return 3

    def flush_file_cache(self):
        self.calls.append("file_cache")
        return "file_cache" not in self.fail

    def memory_list(self, cmd):
        name = {ramclean.FLUSH_MODIFIED: "modified", ramclean.PURGE_LOW_STANDBY: "low_standby",
                ramclean.PURGE_STANDBY: "standby"}[cmd]
        self.calls.append(name)
        return name not in self.fail


def test_non_admin_only_trims_working_sets_and_flags_it():
    ops = FakeOps(admin=False)
    rep = ramclean.RamCleaner(ops).clean([1, 2, 3])
    assert ops.calls == ["working_sets"]
    assert rep.trimmed == 3 and rep.admin is False
    assert rep.steps == {"working_sets": True}


def test_admin_runs_all_steps_in_best_cleaner_order_without_full_standby_when_memory_is_fine():
    ops = FakeOps(admin=True, avail=(10 * GB, 12 * GB))
    rep = ramclean.RamCleaner(ops).clean([1])
    assert ops.calls == ["privileges", "working_sets", "file_cache", "modified", "low_standby"]
    assert rep.admin and all(rep.steps.values())


def test_full_standby_purge_only_when_available_memory_is_low():
    ops = FakeOps(admin=True, total=32 * GB, avail=(2 * GB, 2 * GB))  # ~6% free after cleaning
    ramclean.RamCleaner(ops).clean([1])
    assert ops.calls[-1] == "standby"


def test_a_failing_step_does_not_stop_the_others_and_is_reported():
    ops = FakeOps(admin=True, fail={"file_cache", "modified"})
    rep = ramclean.RamCleaner(ops).clean([1])
    assert ops.calls == ["privileges", "working_sets", "file_cache", "modified", "low_standby"]
    assert rep.steps["file_cache"] is False and rep.steps["modified"] is False
    assert rep.steps["low_standby"] is True


def test_missing_privileges_degrades_to_working_sets_only():
    ops = FakeOps(admin=True, fail={"privileges"})
    rep = ramclean.RamCleaner(ops).clean([1])
    assert ops.calls == ["privileges", "working_sets"]
    assert rep.steps == {"working_sets": True}


def test_freed_is_available_memory_gain_and_never_negative():
    gain = ramclean.RamCleaner(FakeOps(avail=(10 * GB, 12 * GB))).clean([1])
    assert gain.freed_bytes == 2 * GB
    loss = ramclean.RamCleaner(FakeOps(avail=(12 * GB, 10 * GB))).clean([1])
    assert loss.freed_bytes == 0


def test_summary_text_mentions_admin_hint_only_when_not_admin():
    low = ramclean.RamCleaner(FakeOps(admin=False)).clean([1]).summary()
    full = ramclean.RamCleaner(FakeOps(admin=True)).clean([1]).summary()
    assert "yönetici" in low.lower()
    assert "yönetici" not in full.lower()


def test_real_ops_never_raise_without_privileges():
    ops = ramclean.WinMemOps()
    assert isinstance(ops.is_admin(), bool)
    assert ops.total_bytes() > 0 and ops.available_bytes() > 0
    if not ops.is_admin():
        assert ops.memory_list(ramclean.PURGE_LOW_STANDBY) is False
        assert ops.flush_file_cache() is False
    assert ops.trim_working_sets([]) == 0


def test_enabling_privileges_never_raises_even_without_them():
    ops = ramclean.WinMemOps()
    assert isinstance(ops._enable("SeProfileSingleProcessPrivilege"), bool)
    assert isinstance(ops._enable("SeIncreaseQuotaPrivilege"), bool)
    assert isinstance(ops.enable_privileges(), bool)


def test_a_step_that_raises_is_recorded_as_failed_and_the_rest_still_run():
    class Boom(FakeOps):
        def flush_file_cache(self):
            self.calls.append("file_cache")
            raise OverflowError("int too long to convert")

    ops = Boom(admin=True)
    rep = ramclean.RamCleaner(ops).clean([1])
    assert ops.calls == ["privileges", "working_sets", "file_cache", "modified", "low_standby"]
    assert rep.steps["file_cache"] is False and rep.steps["modified"] is True


def test_privilege_enabling_that_raises_degrades_to_working_sets_only():
    class Boom(FakeOps):
        def enable_privileges(self):
            self.calls.append("privileges")
            raise OverflowError("boom")

    ops = Boom(admin=True)
    rep = ramclean.RamCleaner(ops).clean([1])
    assert ops.calls == ["privileges", "working_sets"]
    assert rep.steps == {"working_sets": True}
