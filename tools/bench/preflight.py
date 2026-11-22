"""Refuse to start while another program holds the servo port or the GPIO."""

import os
import subprocess

RUNTIME_PATTERNS = ("v2_rl_walk_mujoco.py", "head_puppet.py", "find_soft_offsets.py", "check_motors.py")


def find_conflicts(port: str = "/dev/ttyACM0", run=subprocess.run) -> list[str]:
    """Reasons (in Japanese) why the bench must not start. Empty means it may start."""
    reasons: list[str] = []
    me = os.getpid()
    for pattern in RUNTIME_PATTERNS:
        res = run(["pgrep", "-af", pattern], capture_output=True, text=True)
        for line in res.stdout.splitlines():
            pid, _, cmd = line.strip().partition(" ")
            if pid.isdigit() and int(pid) != me:
                reasons.append(f"{pattern} が動いています (PID {pid}: {cmd})")
    res = run(["fuser", port], capture_output=True, text=True)
    pids = res.stdout.split()
    if pids:
        reasons.append(f"{port} を別のプロセスが開いています (PID {' '.join(pids)})")
    return reasons
