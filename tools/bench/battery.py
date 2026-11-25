"""Pack voltage summary from the servo readings (there is no dedicated battery sensor)."""

import statistics

LOW_V = 7.2  # recharge soon (hub field notes F11)
CRITICAL_V = 7.0  # servos and the UBEC become unreliable below this


def summarize(voltages: list[float | None]) -> dict:
    values = [v for v in voltages if v is not None]
    if not values:
        return {"volts": None, "level": None}
    volts = round(statistics.median(values), 2)
    level = "critical" if volts <= CRITICAL_V else "low" if volts <= LOW_V else "ok"
    return {"volts": volts, "level": level}
