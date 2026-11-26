import numpy as np

from mini_bdx_runtime.mini_bdx_runtime.command_trim import apply_yaw_trim


def cmds(x=0.0, y=0.0, yaw=0.0):
    return [x, y, yaw, 0.1, 0.0, 0.0, 0.0]


def test_trim_added_while_walking_forward():
    out = apply_yaw_trim(cmds(x=0.1), 0.05)
    np.testing.assert_allclose(out, cmds(x=0.1, yaw=0.05))


def test_trim_added_while_walking_sideways_and_turning():
    out = apply_yaw_trim(cmds(y=-0.2, yaw=0.3), -0.05)
    np.testing.assert_allclose(out, cmds(y=-0.2, yaw=0.25))


def test_no_trim_while_standing_so_the_duck_does_not_step():
    out = apply_yaw_trim(cmds(), 0.05)
    np.testing.assert_allclose(out, cmds())


def test_no_trim_when_only_turning_in_place():
    out = apply_yaw_trim(cmds(yaw=0.5), 0.05)
    np.testing.assert_allclose(out, cmds(yaw=0.5))


def test_trimmed_yaw_stays_in_training_range():
    out = apply_yaw_trim(cmds(x=0.1, yaw=0.99), 0.05)
    assert out[2] == 1.0


def test_input_is_not_modified():
    original = cmds(x=0.1)
    apply_yaw_trim(original, 0.05)
    assert original == cmds(x=0.1)
