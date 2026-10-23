from k_optimizer import trimmer


def test_trim_all_counts_successes_and_never_raises():
    def fake(pid):
        if pid == 2:
            return False
        if pid == 3:
            raise OSError("denied")
        return True

    assert trimmer.trim_all([1, 2, 3, 4], fake) == 2


def test_empty_working_set_returns_false_for_missing_pid():
    assert trimmer.empty_working_set(0x7FFFFFF0) is False


def test_trim_own_process_works():
    import os

    assert trimmer.empty_working_set(os.getpid()) is True
