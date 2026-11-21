"""Servo joint table, STS3215 status decoding, and the jog safety guard."""

# Same 14 axes and IDs as mini_bdx_runtime/rustypot_position_hwi.py (HWI.joints).
JOINTS: dict[int, str] = {
    20: "left_hip_yaw",
    21: "left_hip_roll",
    22: "left_hip_pitch",
    23: "left_knee",
    24: "left_ankle",
    30: "neck_pitch",
    31: "head_pitch",
    32: "head_yaw",
    33: "head_roll",
    10: "right_hip_yaw",
    11: "right_hip_roll",
    12: "right_hip_pitch",
    13: "right_knee",
    14: "right_ankle",
}

_STATUS_BITS = {0: "電圧", 1: "角度センサ", 2: "温度", 3: "電流", 5: "過負荷"}

KP_CHOICES = (2, 8, 16)
STEP_RAD = 0.05
MAX_TRAVEL_RAD = 0.3


def decode_status(value: int) -> list[str]:
    """Names of the error bits set in the STS3215 status register."""
    return [name for bit, name in _STATUS_BITS.items() if value & (1 << bit)]


class GuardError(Exception):
    pass


class JogGuard:
    """Only one axis may hold torque; each jog is ±STEP_RAD within ±MAX_TRAVEL_RAD of the torque-on position."""

    def __init__(self) -> None:
        self.active: int | None = None
        self._baseline = 0.0

    def torque_on(self, servo_id: int, position_rad: float, kp: int) -> int | None:
        if kp not in KP_CHOICES:
            raise GuardError(f"kp は {KP_CHOICES} から選んでください")
        previous = self.active if self.active not in (None, servo_id) else None
        self.active = servo_id
        self._baseline = position_rad
        return previous

    def jog(self, servo_id: int, current_rad: float, direction: int) -> float:
        if self.active != servo_id:
            raise GuardError("この軸にはトルクが入っていません")
        if direction not in (1, -1):
            raise GuardError("direction は +1 か -1 です")
        target = current_rad + direction * STEP_RAD
        if abs(target - self._baseline) > MAX_TRAVEL_RAD + 1e-9:
            raise GuardError("累計の移動が ±0.3 rad を超えます")
        return target

    def torque_off(self, servo_id: int) -> None:
        if self.active == servo_id:
            self.active = None
