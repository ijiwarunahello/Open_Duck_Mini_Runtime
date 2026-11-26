import importlib.util
import sys
import types
from pathlib import Path

import pytest

ANTENNAS = (
    Path(__file__).resolve().parents[2]
    / "mini_bdx_runtime"
    / "mini_bdx_runtime"
    / "antennas.py"
)


@pytest.fixture
def antennas_module(monkeypatch):
    board = types.ModuleType("board")
    board.D12, board.D13 = 12, 13
    pwmio = types.ModuleType("pwmio")

    class FakePWMOut:
        instances = []

        def __init__(self, pin, frequency, duty_cycle):
            self.pin, self.frequency, self.duty_cycle = pin, frequency, duty_cycle
            FakePWMOut.instances.append(self)

        def deinit(self):
            pass

    pwmio.PWMOut = FakePWMOut
    monkeypatch.setitem(sys.modules, "board", board)
    monkeypatch.setitem(sys.modules, "pwmio", pwmio)
    spec = importlib.util.spec_from_file_location("antennas_under_test", ANTENNAS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FakePWMOut = FakePWMOut
    return module


def make_sysfs(root, exported=False):
    """Fake /sys/class/pwm with the BCM283x PWM (pwm-2chan overlay)."""
    device = root / "devices" / "3f20c000.pwm"
    device.mkdir(parents=True)
    chip = root / "class" / "pwmchip0"
    chip.mkdir(parents=True)
    (chip / "device").symlink_to(device)
    (chip / "npwm").write_text("2\n")
    (chip / "export").write_text("")
    (chip / "unexport").write_text("")
    for ch in (0, 1):
        if exported:
            make_channel(chip, ch)
    return root / "class", chip


def make_channel(chip, ch):
    d = chip / f"pwm{ch}"
    d.mkdir()
    for name, value in (("period", "0"), ("duty_cycle", "0"), ("enable", "0")):
        (d / name).write_text(value)


def read(chip, ch, name):
    return int((chip / f"pwm{ch}" / name).read_text())


def test_uses_hardware_pwm_when_available(antennas_module, tmp_path):
    root, chip = make_sysfs(tmp_path, exported=True)
    a = antennas_module.Antennas(pwm_root=root)
    assert a.hardware
    # GPIO12 is PWM0 (right ear), GPIO13 is PWM1 (left ear)
    for ch in (0, 1):
        assert read(chip, ch, "period") == 20_000_000
        assert read(chip, ch, "duty_cycle") == 1_500_000  # neutral
        assert read(chip, ch, "enable") == 1
    assert antennas_module.FakePWMOut.instances == []


def test_positions_map_to_pulse_width_in_ns(antennas_module, tmp_path):
    root, chip = make_sysfs(tmp_path, exported=True)
    a = antennas_module.Antennas(pwm_root=root)
    a.set_position_left(1.0)  # LEFT_SIGN = 1
    assert read(chip, 1, "duty_cycle") == 2_000_000
    a.set_position_right(1.0)  # RIGHT_SIGN = -1
    assert read(chip, 0, "duty_cycle") == 1_000_000
    a.set_position_left(0.25)
    assert read(chip, 1, "duty_cycle") == 1_625_000  # finer than 1 % steps


def test_same_value_is_not_rewritten(antennas_module, tmp_path):
    root, chip = make_sysfs(tmp_path, exported=True)
    a = antennas_module.Antennas(pwm_root=root)
    a.set_position_left(0.5)
    (chip / "pwm1" / "duty_cycle").write_text("marker")
    a.set_position_left(0.5)
    assert (chip / "pwm1" / "duty_cycle").read_text() == "marker"


def test_exports_channels(antennas_module, tmp_path, monkeypatch):
    root, chip = make_sysfs(tmp_path)
    exported = []

    def fake_export(self, path, value):
        if path.name == "export":
            exported.append(int(value))
            make_channel(chip, int(value))
        else:
            path.write_text(str(value))

    monkeypatch.setattr(antennas_module.HardwarePWM, "_write", fake_export)
    a = antennas_module.Antennas(pwm_root=root)
    assert a.hardware
    assert sorted(exported) == [0, 1]


def test_stop_goes_neutral_and_disables(antennas_module, tmp_path):
    root, chip = make_sysfs(tmp_path, exported=True)
    a = antennas_module.Antennas(pwm_root=root)
    a.set_position_left(1.0)
    a.stop()
    for ch in (0, 1):
        assert read(chip, ch, "duty_cycle") == 1_500_000
        assert read(chip, ch, "enable") == 0


def test_falls_back_to_software_pwm_without_overlay(antennas_module, tmp_path):
    a = antennas_module.Antennas(pwm_root=tmp_path / "missing")
    assert not a.hardware
    pins = sorted(p.pin for p in antennas_module.FakePWMOut.instances)
    assert pins == [12, 13]
