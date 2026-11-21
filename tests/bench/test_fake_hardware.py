import pytest

from tools.bench.hardware import FakeHardware, ImuSample
from tools.bench.servo_logic import JOINTS


def test_fake_records_stop_all_and_led():
    hw = FakeHardware()
    hw.set_led("左目", 50)
    hw.stop_all()
    assert ("set_led", "左目", 50) in hw.calls and ("stop_all",) in hw.calls


def test_fake_servos_cover_all_joints():
    assert {r.id for r in FakeHardware().read_servos()} == set(JOINTS)


def test_fake_failures_raise():
    hw = FakeHardware()
    hw.fail_imu = True
    with pytest.raises(Exception):
        hw.read_imu()
    hw.fail_servos = True
    with pytest.raises(Exception):
        hw.read_servos()


def test_fake_imu_reads_standing_gravity():
    s = FakeHardware().read_imu()
    assert isinstance(s, ImuSample) and s.accel[2] == pytest.approx(-9.85, abs=0.2)


def test_fake_torque_on_returns_position_and_marks_torque():
    hw = FakeHardware()
    pos = hw.servo_torque_on(22, 8)
    assert isinstance(pos, float)
    assert next(r for r in hw.read_servos() if r.id == 22).torque
    hw.servo_move(22, pos + 0.05)
    assert next(r for r in hw.read_servos() if r.id == 22).position_rad == pytest.approx(pos + 0.05)
