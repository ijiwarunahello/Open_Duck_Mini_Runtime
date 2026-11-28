"""Optional, fire-and-forget state broadcast from the walk loop (fork addition).

The walk script sends a small JSON datagram at most `rate_hz` times per second to a local
UDP port; tools/duck_vision/pi_stream.py picks it up for the booth display. It never
blocks and never raises: a missing listener or a bad value must not disturb the 50 Hz loop.
"""

import json
import socket
import time


def parse_address(spec: str) -> tuple[str, int]:
    host, _, port = spec.rpartition(":")
    return (host or "127.0.0.1", int(port))


class Telemetry:
    def __init__(self, address: tuple[str, int], rate_hz: float = 10.0, clock=time.monotonic):
        self.address = address
        self.period = 1.0 / rate_hz
        self.clock = clock
        self._next = 0.0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)

    def due(self) -> bool:
        return self.clock() >= self._next

    def send(self, paused: bool, commands, imu_data) -> None:
        now = self.clock()
        if now < self._next:
            return
        self._next = now + self.period
        try:
            payload = {
                "t": time.time(),
                "paused": bool(paused),
                "cmd": [round(float(c), 3) for c in commands],
                "acc": [round(float(a), 3) for a in imu_data["accelero"]],
                "gyro": [round(float(g), 3) for g in imu_data["gyro"]],
            }
            self._sock.sendto(json.dumps(payload).encode(), self.address)
        except Exception:
            pass
