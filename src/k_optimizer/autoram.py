"""Continuous RAM cleaning: one clean every `interval` seconds for as long as it is switched on.

It is safe to run this often because each clean only trims idle background processes (see ramclean.cold_pids),
which is cheap and never touches what the user is working in."""


class AutoRam:
    def __init__(self, interval: float = 10.0):
        self.interval = interval
        self._last: float | None = None

    def due(self, now: float) -> bool:
        return self._last is None or now - self._last >= self.interval

    def record(self, now: float) -> None:
        self._last = now
