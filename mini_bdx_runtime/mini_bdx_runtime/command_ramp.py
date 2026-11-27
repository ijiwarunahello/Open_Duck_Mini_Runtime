"""
Deceleration ramp for the walk commands (lin_vel_x, lin_vel_y, ang_vel_yaw).

Releasing the stick drops the command from full speed to zero within one or two
control cycles. The policy rarely saw such a stop in training (the command
changes once per episode and is all-zero only 10% of the time), and the duck
rocks when it stops. The ramp brings the command toward zero at a limited rate.

- Speeding up (same sign, larger magnitude) passes through unchanged.
- Slowing down, stopping, or reversing moves at most full_scale * dt / decel_time
  per cycle, so a full-scale command reaches zero in decel_time seconds.
- decel_time <= 0 disables the ramp.

Head commands (indices 3 and up) pass through unchanged.
"""

import numpy as np

# Same as the controller ranges (xbox_controller.py) and the training ranges
WALK_FULL_SCALE = (0.15, 0.2, 1.0)


def step_toward(current, target, max_step):
    if current * target >= 0 and abs(target) >= abs(current):
        return target
    if current * target < 0:
        # Reversing: stop first, then speed up the other way next cycle
        target = 0.0
    # Tolerance so that float rounding does not leave a tiny residue for one
    # more cycle
    if abs(target - current) <= max_step * (1 + 1e-9):
        return target
    return current + max_step * np.sign(target - current)


class DecelRamp:
    def __init__(self, decel_time, dt, full_scale=WALK_FULL_SCALE):
        if decel_time > 0:
            self.max_step = [s * dt / decel_time for s in full_scale]
        else:
            self.max_step = None
        self.current = [0.0] * len(full_scale)

    def apply(self, commands):
        # Returns a new list: the controller reuses the list it hands out.
        commands = [float(c) for c in commands]
        if self.max_step is None:
            return commands
        for i, max_step in enumerate(self.max_step):
            self.current[i] = float(step_toward(self.current[i], commands[i], max_step))
            commands[i] = self.current[i]
        return commands
