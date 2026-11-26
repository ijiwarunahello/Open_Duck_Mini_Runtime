"""
Yaw trim: a constant yaw rate added to the command while the duck walks, to
cancel a steady turn (left/right asymmetry of the legs, feet or floor).

The trim is applied only when the forward or lateral command is non-zero. With
all walking commands at zero the policy stands still; a trim alone (above about
0.01) would make it step in place and turn.
"""

import numpy as np

YAW_LIMIT = 1.0  # rad/s, range of the yaw command seen in training


def apply_yaw_trim(commands, yaw_trim):
    """Return a copy of commands ([lin_x, lin_y, yaw, head...]) with the trim."""
    commands = np.array(commands, dtype=float)
    if yaw_trim == 0.0:
        return commands
    if commands[0] == 0.0 and commands[1] == 0.0:
        return commands
    commands[2] = np.clip(commands[2] + yaw_trim, -YAW_LIMIT, YAW_LIMIT)
    return commands
