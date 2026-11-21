"""Hardware backend for the Raspberry Pi. Imports Pi-only libraries, so only load it on the Pi."""

import fcntl
import math
import os
import struct
import subprocess
import tempfile
import termios
import threading
import wave

import RPi.GPIO as GPIO

from tools.bench.hardware import ImuSample, ServoRow
from tools.bench.pins import PinState, parse_pinctrl
from tools.bench.servo_logic import JOINTS
from tools.bench.signals import ear_duty_percent

SERVO_PORT = "/dev/ttyACM0"
FEET_PINS = {"左足": 22, "右足": 27}
LED_PINS = {"左目": 24, "右目": 23, "プロジェクター": 25}
LED_PWM_HZ = 500
EAR_PINS = {"左": (13, 1), "右": (12, -1)}  # (BCM, sign) as in mini_bdx_runtime/antennas.py
EAR_PWM_HZ = 50
TONE_SECONDS = 2.0
TONE_RATE = 48000


class RealHardware:
    def __init__(self) -> None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in FEET_PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._led_pwm = {}
        for name, pin in LED_PINS.items():
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            pwm = GPIO.PWM(pin, LED_PWM_HZ)
            pwm.start(0)
            self._led_pwm[name] = pwm
        self._ear_pwm: dict[str, object] = {}  # created on first use so the ears do not move at start
        self._imu = None
        self._io = None
        self._io_lock = threading.Lock()
        self._torque: set[int] = set()

    # --- GPIO ------------------------------------------------------------
    def read_pins(self) -> dict[int, PinState]:
        out = subprocess.run(["pinctrl", "get"], capture_output=True, text=True, timeout=2).stdout
        return parse_pinctrl(out)

    def read_feet(self) -> dict[str, int]:
        return {name: GPIO.input(pin) for name, pin in FEET_PINS.items()}

    def set_pull(self, bcm: int, pull: str) -> None:
        subprocess.run(["pinctrl", "set", str(bcm), "ip", pull], check=True, timeout=2)

    def set_led(self, name: str, duty: float) -> None:
        self._led_pwm[name].ChangeDutyCycle(max(0.0, min(100.0, duty)))

    def set_ear(self, side: str, value: float, limit: float) -> None:
        pin, sign = EAR_PINS[side]
        duty = ear_duty_percent(value, limit, sign)
        pwm = self._ear_pwm.get(side)
        if pwm is None:
            GPIO.setup(pin, GPIO.OUT)
            pwm = GPIO.PWM(pin, EAR_PWM_HZ)
            pwm.start(duty)
            self._ear_pwm[side] = pwm
        else:
            pwm.ChangeDutyCycle(duty)

    def release_ear(self, side: str) -> None:
        """Stop the software PWM; the SG90 holds roughly in place by gear friction, without jitter."""
        pwm = self._ear_pwm.pop(side, None)
        if pwm is not None:
            pwm.stop()

    # --- IMU -------------------------------------------------------------
    def read_imu(self) -> ImuSample:
        if self._imu is None:
            import adafruit_bno055
            import board
            import busio

            imu = adafruit_bno055.BNO055_I2C(busio.I2C(board.SCL, board.SDA))
            imu.mode = adafruit_bno055.IMUPLUS_MODE
            self._imu = imu
        try:
            accel, gyro, euler = self._imu.acceleration, self._imu.gyro, self._imu.euler
        except Exception:
            self._imu = None  # re-initialise on the next read
            raise
        if None in accel or None in gyro:
            raise OSError("BNO055 が値を返しませんでした")
        return ImuSample(tuple(accel), tuple(gyro), tuple(e if e is not None else math.nan for e in euler))

    # --- speaker / camera ------------------------------------------------
    def play_tone(self, freq_hz: int, volume: float) -> None:
        amp = int(32767 * max(0.0, min(1.0, volume)))
        n = int(TONE_RATE * TONE_SECONDS)
        frames = b"".join(
            struct.pack("<h", int(amp * math.sin(2 * math.pi * freq_hz * i / TONE_RATE))) for i in range(n)
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(TONE_RATE)
                w.writeframes(frames)
            subprocess.run(["aplay", "-q", "-D", "plughw:CARD=MAX98357A", path], check=True, timeout=10)
        finally:
            os.unlink(path)

    def capture_jpeg(self) -> bytes:
        res = subprocess.run(
            ["rpicam-still", "-n", "-t", "1000", "--width", "1296", "--height", "972", "-o", "-"],
            capture_output=True,
            timeout=20,
        )
        if res.returncode != 0 or not res.stdout:
            raise OSError(f"rpicam-still が失敗しました: {res.stderr.decode(errors='replace')[-200:]}")
        return res.stdout

    # --- servos ----------------------------------------------------------
    def _servo_io(self):
        if self._io is None:
            from pypot.feetech import FeetechSTS3215IO

            io = FeetechSTS3215IO(SERVO_PORT, baudrate=1000000, use_sync_read=True)
            fcntl.ioctl(io._serial.fileno(), termios.TIOCEXCL)  # keep other programs off the bus
            self._io = io
        return self._io

    def _drop_io(self) -> None:
        try:
            if self._io is not None:
                self._io.close()
        except Exception:
            pass
        self._io = None

    def read_servos(self) -> list[ServoRow]:
        ids = list(JOINTS)
        with self._io_lock:
            try:
                io = self._servo_io()
                pos = io.get_present_position(ids)
                volt = io.get_present_voltage(ids)
                temp = io.get_present_temperature(ids)
                status = io.get_status(ids)
                maxv = io.get_max_voltage_limit(ids)
            except Exception:
                self._drop_io()  # e.g. USB re-plugged; reopen on the next read
                raise
        return [
            ServoRow(
                sid,
                JOINTS[sid],
                math.radians(pos[i]),
                volt[i] * 0.1,
                int(temp[i]),
                int(status[i]),
                maxv[i] * 0.1,
                sid in self._torque,
            )
            for i, sid in enumerate(ids)
        ]

    def servo_torque_on(self, servo_id: int, kp: int) -> float:
        with self._io_lock:
            io = self._servo_io()
            io.set_P_coefficient({servo_id: kp})
            pos_deg = io.get_present_position([servo_id])[0]
            io.set_goal_position({servo_id: pos_deg})
            io.enable_torque([servo_id])
            self._torque.add(servo_id)
        return math.radians(pos_deg)

    def servo_move(self, servo_id: int, target_rad: float) -> None:
        with self._io_lock:
            self._servo_io().set_goal_position({servo_id: math.degrees(target_rad)})

    def servo_torque_off(self, servo_id: int) -> None:
        with self._io_lock:
            self._servo_io().disable_torque([servo_id])
            self._torque.discard(servo_id)

    # --- safety / status -------------------------------------------------
    def stop_all(self) -> None:
        with self._io_lock:
            try:
                self._servo_io().disable_torque(list(JOINTS))
            except Exception:
                self._drop_io()
            self._torque.clear()
        for pwm in self._led_pwm.values():
            pwm.ChangeDutyCycle(0)
        for pwm in self._ear_pwm.values():
            pwm.stop()
        self._ear_pwm.clear()

    def pi_status(self) -> dict:
        throttled = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp = int(f.read().strip()) / 1000
        with open("/proc/uptime") as f:
            uptime = int(float(f.read().split()[0]))
        return {"throttled": throttled.strip().partition("=")[2] or "?", "cpu_temp": temp, "uptime_s": uptime}
