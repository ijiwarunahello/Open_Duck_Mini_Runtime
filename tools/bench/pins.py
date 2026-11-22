"""Raspberry Pi 40-pin header table, pin roles for this duck, and `pinctrl` parsing."""

import re
from dataclasses import dataclass

# Physical pin -> BCM GPIO number, or a power/ground label.
HEADER: dict[int, int | str] = {
    1: "3V3", 2: "5V",
    3: 2, 4: "5V",
    5: 3, 6: "GND",
    7: 4, 8: 14,
    9: "GND", 10: 15,
    11: 17, 12: 18,
    13: 27, 14: "GND",
    15: 22, 16: 23,
    17: "3V3", 18: 24,
    19: 10, 20: "GND",
    21: 9, 22: 25,
    23: 11, 24: 8,
    25: "GND", 26: 7,
    27: 0, 28: 1,
    29: 5, 30: "GND",
    31: 6, 32: 12,
    33: 13, 34: "GND",
    35: 19, 36: 16,
    37: 26, 38: 20,
    39: "GND", 40: 21,
}

# Roles on this build (hub docs/wiring/wiring-diagrams.html), not the tnkr table.
ROLES: dict[int, str] = {
    2: "IMU SDA",
    3: "IMU SCL",
    12: "右耳",
    13: "左耳",
    18: "I2S BCLK",
    19: "I2S LRC",
    20: "マイク DOUT",
    21: "アンプ DIN",
    17: "左足",
    23: "右目",
    24: "左目",
    25: "プロジェクター",
    27: "右足",
    0: "予約 (HAT EEPROM)",
    1: "予約 (HAT EEPROM)",
    4: "予約 (アンプ SD)",
    14: "予約 (UART TX)",
    15: "予約 (UART RX)",
    22: "予約 (ヘッダのピン 15 が断線。左足は GPIO17 へ移した)",
}

RESERVED: frozenset[int] = frozenset({0, 1, 4, 14, 15, 22})
IN_USE: frozenset[int] = frozenset({2, 3, 12, 13, 17, 18, 19, 20, 21, 23, 24, 25, 27})


@dataclass(frozen=True)
class PinState:
    bcm: int
    func: str
    pull: str
    level: int


_LINE = re.compile(r"^\s*(\d+):\s+(\S+)\s+(.*?)\s*\|\s*(hi|lo)\b")


def parse_pinctrl(text: str) -> dict[int, PinState]:
    """Parse `pinctrl get` output into BCM -> PinState."""
    states: dict[int, PinState] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        bcm, func, rest, level = int(m[1]), m[2], m[3].split(), m[4]
        pull = "--" if func == "op" or not rest else rest[0]
        states[bcm] = PinState(bcm, func, pull, 1 if level == "hi" else 0)
    return states


def can_set_pull(bcm: int) -> bool:
    """Only pins that are neither reserved nor in use may have their pull changed."""
    return 0 <= bcm <= 27 and bcm not in RESERVED and bcm not in IN_USE
