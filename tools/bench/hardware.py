"""Hardware interface used by the bench server, plus a fake backend for the PC and tests."""

import random
import time
from dataclasses import dataclass, replace
from typing import Protocol

from tools.bench.pins import HEADER, PinState
from tools.bench.servo_logic import JOINTS

Vec3 = tuple[float, float, float]


@dataclass
class ImuSample:
    accel: Vec3
    gyro: Vec3
    euler: Vec3


@dataclass
class ServoRow:
    id: int
    name: str
    position_rad: float | None
    voltage: float | None
    temperature: int | None
    status: int | None
    max_voltage: float | None
    torque: bool
    error: str | None = None


LEDS = ("左目", "右目", "プロジェクター")
EARS = ("左", "右")
FEET = ("左足", "右足")


class Hardware(Protocol):
    def read_pins(self) -> dict[int, PinState]: ...
    def read_feet(self) -> dict[str, int]: ...
    def set_pull(self, bcm: int, pull: str) -> None: ...
    def read_imu(self) -> ImuSample: ...
    def set_led(self, name: str, duty: float) -> None: ...
    def set_ear(self, side: str, value: float, limit: float) -> None: ...
    def release_ear(self, side: str) -> None: ...
    def play_tone(self, freq_hz: int, volume: float) -> None: ...
    def capture_jpeg(self) -> bytes: ...
    def read_servos(self) -> list[ServoRow]: ...
    def servo_torque_on(self, servo_id: int, kp: int) -> float: ...
    def servo_move(self, servo_id: int, target_rad: float) -> None: ...
    def servo_torque_off(self, servo_id: int) -> None: ...
    def stop_all(self) -> None: ...
    def pi_status(self) -> dict: ...


# Smallest valid JPEG (1x1 grey) so the camera panel has something to show in --fake mode.
_FAKE_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c"
    "20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f000001050101010101010000"
    "0000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191"
    "a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a"
    "737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8"
    "d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbfcffd9"
)


class FakeHardware:
    """Generates plausible values and records every operation in `calls`."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_imu = False
        self.fail_servos = False
        self._feet = {"左足": 1, "右足": 1}
        self._t0 = time.monotonic()
        self._servos = {
            sid: ServoRow(sid, name, random.uniform(-0.3, 0.3), 8.0, 24, 0, 9.0, False)
            for sid, name in JOINTS.items()
        }

    def read_pins(self) -> dict[int, PinState]:
        pins: dict[int, PinState] = {}
        for bcm in (v for v in HEADER.values() if isinstance(v, int)):
            level = 1
            if bcm == 22:
                level = self._feet["左足"]
            elif bcm == 27:
                level = self._feet["右足"]
            elif bcm in (14, 23, 24, 25):
                level = 0
            func = "a0" if bcm in (18, 19, 20, 21) else "ip"
            pull = "pu" if bcm in (22, 27) else "--"
            pins[bcm] = PinState(bcm, func, pull, level)
        return pins

    def read_feet(self) -> dict[str, int]:
        # Right foot toggles every 3 s so the edge log has something to show.
        phase = int((time.monotonic() - self._t0) / 3) % 2
        self._feet["右足"] = phase
        return dict(self._feet)

    def set_pull(self, bcm: int, pull: str) -> None:
        self.calls.append(("set_pull", bcm, pull))

    def read_imu(self) -> ImuSample:
        if self.fail_imu:
            raise OSError("fake IMU failure")
        j = lambda: random.uniform(-0.02, 0.02)  # noqa: E731
        return ImuSample((0.33 + j(), 0.78 + j(), -9.85 + j()), (j(), j(), j()), (0.0, 4.5, 2.0))

    def set_led(self, name: str, duty: float) -> None:
        self.calls.append(("set_led", name, duty))

    def set_ear(self, side: str, value: float, limit: float) -> None:
        self.calls.append(("set_ear", side, value, limit))

    def release_ear(self, side: str) -> None:
        self.calls.append(("release_ear", side))

    def play_tone(self, freq_hz: int, volume: float) -> None:
        self.calls.append(("play_tone", freq_hz, volume))

    def capture_jpeg(self) -> bytes:
        self.calls.append(("capture_jpeg",))
        return _FAKE_JPEG

    def read_servos(self) -> list[ServoRow]:
        if self.fail_servos:
            raise OSError("fake servo bus failure")
        return [replace(r) for r in self._servos.values()]

    def servo_torque_on(self, servo_id: int, kp: int) -> float:
        self.calls.append(("servo_torque_on", servo_id, kp))
        self._servos[servo_id].torque = True
        return self._servos[servo_id].position_rad

    def servo_move(self, servo_id: int, target_rad: float) -> None:
        self.calls.append(("servo_move", servo_id, target_rad))
        self._servos[servo_id].position_rad = target_rad

    def servo_torque_off(self, servo_id: int) -> None:
        self.calls.append(("servo_torque_off", servo_id))
        self._servos[servo_id].torque = False

    def stop_all(self) -> None:
        self.calls.append(("stop_all",))
        for r in self._servos.values():
            r.torque = False

    def pi_status(self) -> dict:
        return {"throttled": "0x0", "cpu_temp": 45.0, "uptime_s": int(time.monotonic() - self._t0)}
