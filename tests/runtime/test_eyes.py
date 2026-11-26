import importlib.util
import sys
import time
import types
from pathlib import Path

import pytest

EYES = (
    Path(__file__).resolve().parents[2] / "mini_bdx_runtime" / "mini_bdx_runtime" / "eyes.py"
)


class FakePin:
    def __init__(self, pin):
        self.value = False
        self.direction = None

    def deinit(self):
        pass


@pytest.fixture
def eyes_module(monkeypatch):
    board = types.ModuleType("board")
    board.D23, board.D24 = 23, 24
    digitalio = types.ModuleType("digitalio")
    digitalio.DigitalInOut = FakePin
    digitalio.Direction = types.SimpleNamespace(OUTPUT="out")
    monkeypatch.setitem(sys.modules, "board", board)
    monkeypatch.setitem(sys.modules, "digitalio", digitalio)
    spec = importlib.util.spec_from_file_location("eyes_under_test", EYES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lit(eyes):
    return eyes.left_eye.value and eyes.right_eye.value


def dark(eyes):
    return not eyes.left_eye.value and not eyes.right_eye.value


def wait_until(condition, timeout=1.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.005)
    return False


def test_cycle_goes_blink_on_off_and_back(eyes_module):
    eyes = eyes_module.Eyes(blink_duration=0.01, min_interval=0.02, max_interval=0.03)
    try:
        assert eyes.mode == "blink"
        assert eyes.cycle_mode() == "on"
        assert eyes.cycle_mode() == "off"
        assert eyes.cycle_mode() == "blink"
    finally:
        eyes.stop()


def test_on_mode_stays_lit(eyes_module):
    eyes = eyes_module.Eyes(blink_duration=0.01, min_interval=0.02, max_interval=0.03)
    try:
        eyes.cycle_mode()  # on
        assert wait_until(lambda: lit(eyes))
        # longer than several blink periods: never turns off
        end = time.time() + 0.2
        while time.time() < end:
            assert lit(eyes)
            time.sleep(0.005)
    finally:
        eyes.stop()


def test_off_mode_turns_eyes_off_at_once(eyes_module):
    # long interval: the change must not wait for the next blink
    eyes = eyes_module.Eyes(blink_duration=0.01, min_interval=10, max_interval=10)
    try:
        assert wait_until(lambda: lit(eyes))
        eyes.cycle_mode()  # on
        eyes.cycle_mode()  # off
        assert wait_until(lambda: dark(eyes), timeout=0.2)
    finally:
        eyes.stop()


def test_back_to_blink_blinks_again(eyes_module):
    eyes = eyes_module.Eyes(blink_duration=0.01, min_interval=0.02, max_interval=0.03)
    try:
        eyes.cycle_mode()
        eyes.cycle_mode()  # off
        assert wait_until(lambda: dark(eyes))
        eyes.cycle_mode()  # blink
        assert wait_until(lambda: lit(eyes))
        assert wait_until(lambda: dark(eyes))  # a blink
    finally:
        eyes.stop()


def test_stop_returns_quickly_and_turns_off(eyes_module):
    eyes = eyes_module.Eyes(blink_duration=0.01, min_interval=10, max_interval=10)
    assert wait_until(lambda: lit(eyes))
    t = time.time()
    eyes.stop()
    assert time.time() - t < 0.5
    assert dark(eyes)
