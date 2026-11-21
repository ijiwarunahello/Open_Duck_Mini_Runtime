"""Edge logging with chatter counting, IMU frame conversion, and ear servo duty."""

from collections import deque

CHATTER_WINDOW_S = 0.05

Vec3 = tuple[float, float, float]


class EdgeLog:
    """Records level changes per signal name; a change within CHATTER_WINDOW_S of the previous one counts as chatter."""

    def __init__(self, maxlen: int = 200) -> None:
        self._events: deque[tuple[float, str, int, int]] = deque(maxlen=maxlen)
        self._level: dict[str, int] = {}
        self._last_change: dict[str, float] = {}
        self.chatter: dict[str, int] = {}

    @property
    def events(self) -> list[tuple[float, str, int, int]]:
        return list(self._events)

    def update(self, name: str, level: int, t: float) -> None:
        self.chatter.setdefault(name, 0)
        prev = self._level.get(name)
        self._level[name] = level
        if prev is None or prev == level:
            return
        last = self._last_change.get(name)
        if last is not None and t - last <= CHATTER_WINDOW_S:
            self.chatter[name] += 1
        self._last_change[name] = t
        self._events.append((t, name, prev, level))


def to_runtime_frame(v: Vec3, upside_down: bool) -> Vec3:
    """Same mapping as the Runtime's BNO055 axis_remap (Y, X, Z)."""
    x, y, z = v
    if upside_down:
        return (-y, -x, -z)
    return (-y, x, z)


def ear_duty_percent(value: float, limit: float, sign: int) -> float:
    """Duty cycle (%) at 50 Hz for an ear value, as in mini_bdx_runtime/antennas.py."""
    v = max(-limit, min(limit, value)) * sign
    pulse_ms = 1.5 + 0.5 * v
    return pulse_ms / 20.0 * 100.0
