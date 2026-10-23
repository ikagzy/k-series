"""When to clean RAM on its own: memory use at or above a threshold, never more often than the interval, and
backing off while cleaning achieves nothing (so an idle, already-lean system is not trimmed over and over)."""

_NEGLIGIBLE = 64 * 1024 * 1024  # freeing less than this counts as "nothing worth repeating"


class AutoRam:
    def __init__(self, threshold: float = 80.0, min_interval: float = 60.0, max_interval: float = 600.0):
        self.threshold = threshold
        self.min_interval, self.max_interval = min_interval, max_interval
        self._interval = min_interval
        self._last: float | None = None

    def due(self, now: float, used_percent: float) -> bool:
        if used_percent < self.threshold:
            return False
        return self._last is None or now - self._last >= self._interval

    def record(self, now: float, freed_bytes: int) -> None:
        self._last = now
        if freed_bytes < _NEGLIGIBLE:
            self._interval = min(self._interval * 2, self.max_interval)
        else:
            self._interval = self.min_interval
