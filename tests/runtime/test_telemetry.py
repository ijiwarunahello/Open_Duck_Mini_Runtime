import json
import socket

import numpy as np

from mini_bdx_runtime.mini_bdx_runtime.telemetry import Telemetry, parse_address

IMU = {"accelero": np.array([0.1, -0.2, 9.8]), "gyro": np.array([0.0, 0.01, -0.02])}


def listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(2)
    return s


def test_parse_address():
    assert parse_address("127.0.0.1:8092") == ("127.0.0.1", 8092)
    assert parse_address(":8092") == ("127.0.0.1", 8092)


def test_sends_state_at_most_rate_hz():
    rx = listener()
    now = [0.0]
    tx = Telemetry(rx.getsockname(), rate_hz=10, clock=lambda: now[0])
    tx.send(False, [0.15, 0, 0.5, 0, 0, 0, 0], IMU)
    msg = json.loads(rx.recv(4096))
    assert msg["paused"] is False and msg["cmd"][0] == 0.15 and msg["acc"][2] == 9.8

    now[0] = 0.05
    assert not tx.due()
    tx.send(True, [0] * 7, IMU)  # too soon: dropped
    now[0] = 0.1
    assert tx.due()
    tx.send(True, [0] * 7, IMU)
    assert json.loads(rx.recv(4096))["paused"] is True


def test_never_raises_without_listener_or_with_bad_values():
    tx = Telemetry(("127.0.0.1", 9), rate_hz=1000)
    tx.send(False, [0] * 7, IMU)  # nobody listening
    tx.send(False, [0] * 7, {"accelero": None, "gyro": None})  # malformed sample
