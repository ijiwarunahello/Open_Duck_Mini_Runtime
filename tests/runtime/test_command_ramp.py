import json

import pytest

from mini_bdx_runtime.mini_bdx_runtime.command_ramp import DecelRamp
from mini_bdx_runtime.mini_bdx_runtime.duck_config import DuckConfig

DT = 0.02  # 50 Hz


def run(ramp, commands, cycles):
    return [ramp.apply(commands) for _ in range(cycles)]


def test_speeding_up_passes_through():
    ramp = DecelRamp(0.4, DT)
    out = ramp.apply([0.15, -0.2, 1.0, 0.1, 0.2, 0.3, 0.4])
    assert out == pytest.approx([0.15, -0.2, 1.0, 0.1, 0.2, 0.3, 0.4])


def test_release_reaches_zero_in_decel_time():
    ramp = DecelRamp(0.4, DT)
    ramp.apply([0.15, 0.0, 0.0])
    out = run(ramp, [0.0, 0.0, 0.0], 20)  # 0.4 s
    xs = [o[0] for o in out]
    assert xs[0] == pytest.approx(0.15 - 0.0075)
    assert all(a > b for a, b in zip(xs[:-1], xs[1:]))
    assert xs[-2] > 0
    assert xs[-1] == pytest.approx(0.0)


def test_each_axis_uses_its_own_full_scale():
    ramp = DecelRamp(0.4, DT)
    ramp.apply([0.15, 0.2, 1.0])
    out = ramp.apply([0.0, 0.0, 0.0])
    assert out == pytest.approx([0.15 - 0.0075, 0.2 - 0.01, 1.0 - 0.05])


def test_partial_slowdown_is_limited():
    ramp = DecelRamp(0.4, DT)
    ramp.apply([0.15, 0.0, 0.0])
    assert ramp.apply([0.1, 0.0, 0.0])[0] == pytest.approx(0.1425)


def test_reversal_slows_to_zero_then_jumps():
    ramp = DecelRamp(0.4, DT)
    ramp.apply([0.15, 0.0, 0.0])
    out = run(ramp, [-0.15, 0.0, 0.0], 21)
    xs = [o[0] for o in out]
    assert all(x >= 0 for x in xs[:20])
    assert xs[20] == pytest.approx(-0.15)


def test_head_commands_are_not_ramped():
    ramp = DecelRamp(0.4, DT)
    ramp.apply([0.0, 0.0, 0.0, 0.0, 0.3, 0.5, 0.5])
    out = ramp.apply([0.0] * 7)
    assert out[3:] == [0.0, 0.0, 0.0, 0.0]


def test_zero_disables():
    ramp = DecelRamp(0.0, DT)
    ramp.apply([0.15, 0.2, 1.0])
    assert ramp.apply([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_returns_new_list():
    ramp = DecelRamp(0.4, DT)
    commands = [0.15, 0.0, 0.0]
    ramp.apply(commands)
    ramp.apply([0.0, 0.0, 0.0])
    assert commands == [0.15, 0.0, 0.0]


def test_duck_config_reads_command_decel_time(tmp_path):
    path = tmp_path / "duck_config.json"
    path.write_text(json.dumps({"command_decel_time": 0.6}))
    assert DuckConfig(str(path)).command_decel_time == 0.6


def test_duck_config_default_decel_time(tmp_path):
    path = tmp_path / "duck_config.json"
    path.write_text(json.dumps({}))
    assert DuckConfig(str(path)).command_decel_time == 0.4


def test_duck_config_rejects_negative(tmp_path):
    path = tmp_path / "duck_config.json"
    path.write_text(json.dumps({"command_decel_time": -1}))
    with pytest.raises(ValueError):
        DuckConfig(str(path))
