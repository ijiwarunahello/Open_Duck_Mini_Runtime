import json

import numpy as np
import pytest

from mini_bdx_runtime.mini_bdx_runtime.duck_config import DuckConfig
from mini_bdx_runtime.mini_bdx_runtime.imu_correction import correct_imu


def test_no_correction_by_default():
    gyro, acc = correct_imu([0.1, -0.2, 0.3], [1.0, 2.0, 9.8])
    np.testing.assert_allclose(gyro, [0.1, -0.2, 0.3])
    np.testing.assert_allclose(acc, [1.0, 2.0, 9.8])


def test_flip_xy_negates_x_and_y_only():
    # measured on the duck: tilting forward gave acc X +3.0 and gyro Y negative
    gyro, acc = correct_imu([0.27, -0.3, 0.05], [3.0, -0.8, 9.4], flip_xy=True)
    np.testing.assert_allclose(gyro, [-0.27, 0.3, 0.05])
    np.testing.assert_allclose(acc, [-3.0, 0.8, 9.4])


def test_bias_is_added_after_flip():
    gyro, acc = correct_imu(
        [0.0, 0.0, 0.0], [1.0, 0.0, 9.8], flip_xy=True, accel_bias=[0.5, 0.0, 0.0]
    )
    np.testing.assert_allclose(acc, [-0.5, 0.0, 9.8])
    np.testing.assert_allclose(gyro, [0.0, 0.0, 0.0])


def write_config(tmp_path, data):
    path = tmp_path / "duck_config.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_duck_config_reads_imu_correction(tmp_path):
    cfg = DuckConfig(
        write_config(tmp_path, {"imu_flip_xy": True, "imu_accel_bias": [0.5, 0, 0]})
    )
    assert cfg.imu_flip_xy is True
    assert cfg.imu_accel_bias == [0.5, 0, 0]


def test_duck_config_imu_correction_defaults(tmp_path):
    cfg = DuckConfig(write_config(tmp_path, {}))
    assert cfg.imu_flip_xy is False
    assert cfg.imu_accel_bias == [0.0, 0.0, 0.0]


def test_duck_config_rejects_bad_bias(tmp_path):
    with pytest.raises(ValueError):
        DuckConfig(write_config(tmp_path, {"imu_accel_bias": [0.5]}))
