"""
Measure the IMU at rest and print the gyro bias to put in duck_config.json.

Keep the duck still (standing with torque on, or on a stand) while it runs.
Run it from scripts/ like the walk, so that imu_calib_data.pkl is found.

The readings already include imu_upside_down, imu_flip_xy and the current
imu_accel_bias, but not imu_gyro_bias, so the printed value replaces the
current one.
"""

import argparse
import os
import time

import numpy as np

from mini_bdx_runtime.duck_config import DuckConfig
from mini_bdx_runtime.raw_imu import Imu

HOME_DIR = os.path.expanduser("~")

parser = argparse.ArgumentParser()
parser.add_argument("--duck_config_path", default=f"{HOME_DIR}/duck_config.json")
parser.add_argument("-s", "--seconds", type=float, default=10.0)
args = parser.parse_args()

cfg = DuckConfig(config_json_path=args.duck_config_path)
imu = Imu(
    50,
    upside_down=cfg.imu_upside_down,
    flip_xy=cfg.imu_flip_xy,
    accel_bias=cfg.imu_accel_bias,
)
time.sleep(1.0)  # let the worker start

gyros, accs = [], []
end = time.time() + args.seconds
while time.time() < end:
    data = imu.get_data()
    gyros.append(np.array(data["gyro"], dtype=float))
    accs.append(np.array(data["accelero"], dtype=float))
    time.sleep(1 / 50)

gyros, accs = np.array(gyros), np.array(accs)
mean, std = gyros.mean(axis=0), gyros.std(axis=0)
print(f"{len(gyros)} samples over {args.seconds} s")
print("gyro mean (rad/s)  ", np.round(mean, 4), " std", np.round(std, 4))
print("accel mean (m/s^2) ", np.round(accs.mean(axis=0), 3))
print(f"gyro Z bias {mean[2]:+.4f} rad/s = {np.degrees(mean[2]) * 10:+.1f} deg per 10 s")
print('suggested "imu_gyro_bias":', [round(float(-v), 4) for v in mean])
