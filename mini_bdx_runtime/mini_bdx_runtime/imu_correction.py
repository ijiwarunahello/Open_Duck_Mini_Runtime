"""
Corrections applied to the IMU readings before they reach the policy.

The policy expects the IMU frame used in training: X forward, Y left, Z up,
with the accelerometer reading about +9.8 on Z when the robot stands still.

- flip_xy: negates X and Y of both the gyro and the accelerometer. Use it when
  tilting the robot forward gives a positive accelerometer X (the IMU is turned
  180 degrees in the horizontal plane compared with what `imu_upside_down`
  expects).
- accel_bias: added to the accelerometer after the flip. A positive X makes the
  policy believe the robot leans backward, so it leans forward to compensate.
"""

import numpy as np

FLIP_XY = np.array([-1.0, -1.0, 1.0])


def correct_imu(gyro, accelero, flip_xy=False, accel_bias=(0.0, 0.0, 0.0)):
    gyro = np.asarray(gyro, dtype=float)
    accelero = np.asarray(accelero, dtype=float)
    if flip_xy:
        gyro = gyro * FLIP_XY
        accelero = accelero * FLIP_XY
    accelero = accelero + np.asarray(accel_bias, dtype=float)
    return gyro, accelero
