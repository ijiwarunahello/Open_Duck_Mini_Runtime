import board
import pwmio
import math
import time
from pathlib import Path

LEFT_ANTENNA_PIN = board.D13
RIGHT_ANTENNA_PIN = board.D12
LEFT_SIGN = 1
RIGHT_SIGN = -1
MIN_UPDATE_INTERVAL = 1 / 50  # 20ms

# Hardware PWM (fork addition). With
#   dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
# in /boot/firmware/config.txt, GPIO12 is PWM0 and GPIO13 is PWM1 of the
# BCM283x PWM block, driven through /sys/class/pwm. The pulses no longer
# jitter with the CPU load (the software PWM made the SG90 ears twitch while
# holding still) and the pulse width is set in ns instead of 1 % duty steps.
# Without the overlay the ears fall back to the software PWM below.
PWM_ROOT = Path("/sys/class/pwm")
PWM_DEVICE_SUFFIX = "20c000.pwm"  # 3f20c000 (Pi 2/3/Zero 2) and fe20c000 (Pi 4)
LEFT_ANTENNA_CHANNEL = 1  # GPIO13
RIGHT_ANTENNA_CHANNEL = 0  # GPIO12
PERIOD_NS = 20_000_000  # 50 Hz
EXPORT_TIMEOUT = 2.0  # s, udev sets the group permissions after the export


def value_to_pulse_ns(v):
    pulse_ns = int(round(1_500_000 + v * 500_000))  # 1ms to 2ms
    return min(max(pulse_ns, 1_000_000), 2_000_000)


def value_to_duty_cycle(v):
    pulse_width_ms = 1.5 + (v * 0.5)  # 1ms to 2ms
    duty_cycle = int((pulse_width_ms / 20) * 65535)
    return min(max(duty_cycle, 3277), 6553)


def find_pwm_chip(root=PWM_ROOT):
    root = Path(root)
    if not root.is_dir():
        return None
    for chip in sorted(root.glob("pwmchip*")):
        try:
            device = (chip / "device").resolve().name
            npwm = int((chip / "npwm").read_text())
        except (OSError, ValueError):
            continue
        if device.endswith(PWM_DEVICE_SUFFIX) and npwm >= 2:
            return chip
    return None


class HardwarePWM:
    def __init__(self, chip, channel, pulse_ns):
        self.chip = Path(chip)
        self.channel = channel
        self.dir = self.chip / f"pwm{channel}"
        if not self.dir.exists():
            self._write(self.chip / "export", channel)
        self._wait_writable()
        # duty_cycle must not exceed period: lower it first
        self._write(self.dir / "duty_cycle", 0)
        self._write(self.dir / "period", PERIOD_NS)
        self._pulse_ns = None
        self.set_pulse_ns(pulse_ns)
        self._write(self.dir / "enable", 1)

    def _write(self, path, value):
        path.write_text(str(value))

    def _wait_writable(self):
        end = time.monotonic() + EXPORT_TIMEOUT
        while True:
            try:
                self._write(self.dir / "enable", 0)
                return
            except (PermissionError, FileNotFoundError):
                if time.monotonic() > end:
                    raise
                time.sleep(0.05)

    def set_pulse_ns(self, pulse_ns):
        if pulse_ns != self._pulse_ns:
            self._write(self.dir / "duty_cycle", pulse_ns)
            self._pulse_ns = pulse_ns

    def disable(self):
        self._write(self.dir / "enable", 0)


class Antennas:
    def __init__(self, pwm_root=PWM_ROOT):
        self.hardware = False
        chip = find_pwm_chip(pwm_root)
        if chip is not None:
            try:
                neutral = value_to_pulse_ns(0)
                self.pwm_left = HardwarePWM(chip, LEFT_ANTENNA_CHANNEL, neutral)
                self.pwm_right = HardwarePWM(chip, RIGHT_ANTENNA_CHANNEL, neutral)
                self.hardware = True
            except OSError as e:
                print(f"Antennas: hardware PWM failed ({e}), using software PWM")
        else:
            print("Antennas: no hardware PWM (pwm-2chan overlay), using software PWM")
        if not self.hardware:
            neutral_duty = value_to_duty_cycle(0)
            self.pwm_left = pwmio.PWMOut(LEFT_ANTENNA_PIN, frequency=50, duty_cycle=neutral_duty)
            self.pwm_right = pwmio.PWMOut(RIGHT_ANTENNA_PIN, frequency=50, duty_cycle=neutral_duty)

    def set_position_left(self, position):
        self.set_position(self.pwm_left, position, LEFT_SIGN)

    def set_position_right(self, position):
        self.set_position(self.pwm_right, position, RIGHT_SIGN)

    def set_position(self, pwm, value, sign=1):
        # if value == 0:
        #     return
        if -1 <= value <= 1:
            if self.hardware:
                pwm.set_pulse_ns(value_to_pulse_ns(value * sign))
            else:
                duty_cycle = value_to_duty_cycle(value * sign) # Convert value to duty cycle (1ms-2ms)
                pwm.duty_cycle = duty_cycle
        else:
            print("Invalid input! Enter a value between -1 and 1.")

    def stop(self):
        time.sleep(MIN_UPDATE_INTERVAL)
        self.set_position_left(0)
        self.set_position_right(0)
        time.sleep(MIN_UPDATE_INTERVAL)
        if self.hardware:
            self.pwm_left.disable()
            self.pwm_right.disable()
        else:
            self.pwm_left.deinit()
            self.pwm_right.deinit()


if __name__ == "__main__":
    antennas = Antennas()

    try:
        start_time = time.monotonic()
        current_time = start_time

        while current_time - start_time < 5:
            value = math.sin(2 * math.pi * 1 * current_time)
            antennas.set_position_left(value)
            antennas.set_position_right(value)
            time.sleep(MIN_UPDATE_INTERVAL)
            current_time = time.monotonic()

    finally:
        antennas.stop()
