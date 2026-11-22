import pytest

from tools.bench.servo_logic import JOINTS, GuardError, JogGuard, decode_status


def test_joints_cover_14_axes():
    assert len(JOINTS) == 14 and JOINTS[22] == "left_hip_pitch" and JOINTS[30] == "neck_pitch"


def test_decode_status():
    assert decode_status(0) == []
    assert decode_status(1) == ["電圧"]
    assert decode_status(0b100101) == ["電圧", "温度", "過負荷"]


def test_only_one_axis_holds_torque():
    g = JogGuard()
    assert g.torque_on(22, 0.0, 8) is None
    assert g.torque_on(13, -0.27, 8) == 22
    assert g.active == 13


def test_kp_must_be_a_choice():
    with pytest.raises(GuardError):
        JogGuard().torque_on(22, 0.0, 32)


def test_jog_requires_torque_on_axis():
    with pytest.raises(GuardError):
        JogGuard().jog(22, 0.0, +1)


def test_jog_refuses_beyond_travel_limit():
    g = JogGuard()
    g.torque_on(22, 0.10, 8)
    pos = 0.10
    for _ in range(6):
        pos = g.jog(22, pos, +1)
    assert pos == pytest.approx(0.40)
    with pytest.raises(GuardError):
        g.jog(22, pos, +1)


def test_retorque_resets_baseline():
    g = JogGuard()
    g.torque_on(22, 0.0, 8)
    for i in range(6):
        g.jog(22, 0.05 * i, +1)
    g.torque_off(22)
    g.torque_on(22, 0.30, 8)
    assert g.jog(22, 0.30, +1) == pytest.approx(0.35)


def test_torque_off_clears_active():
    g = JogGuard()
    g.torque_on(22, 0.0, 8)
    g.torque_off(22)
    assert g.active is None
