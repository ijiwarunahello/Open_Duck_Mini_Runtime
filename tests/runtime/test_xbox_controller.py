import sys
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

# xbox_controller imports "mini_bdx_runtime.buttons" (the installed inner package);
# with pythonpath "." the outer directory shadows it, so alias the module.
import mini_bdx_runtime.mini_bdx_runtime.buttons as buttons_module

sys.modules.setdefault("mini_bdx_runtime.buttons", buttons_module)

from mini_bdx_runtime.mini_bdx_runtime import xbox_controller as xc  # noqa: E402


class FakeJoystick:
    # Numbers measured on the duck (W13): left stick axes 0/1, right 2/3, RT 4, LT 5
    def __init__(self, device_index, instance_id=None):
        self.device_index = device_index
        self.instance_id = device_index if instance_id is None else instance_id
        self.axes = [0.0, 0.0, 0.0, 0.0, -1.0, -1.0]

    def init(self):
        pass

    def get_instance_id(self):
        return self.instance_id

    def get_numaxes(self):
        return len(self.axes)

    def get_axis(self, i):
        return self.axes[i]

    def get_button(self, i):
        return False

    def get_hat(self, i):
        return (0, 0)


@pytest.fixture
def fake_pygame(monkeypatch):
    state = SimpleNamespace(count=1, events=[], opened=[], event_errors=0)

    def make_joystick(device_index):
        j = FakeJoystick(device_index, instance_id=len(state.opened))
        state.opened.append(j)
        return j

    def get_events():
        if state.event_errors:
            # pygame 2.6.0 raises this when a joystick is added, removed and
            # added again before the events are read (first connection after
            # boot, while the kernel rebinds hid-generic to hid-microsoft).
            state.event_errors -= 1
            state.events = []
            raise SystemError("<built-in function get> returned a result with an exception set")
        events, state.events = state.events, []
        return events

    monkeypatch.setattr(pygame, "init", lambda: None)
    monkeypatch.setattr(pygame.event, "get", get_events)
    monkeypatch.setattr(pygame.joystick, "get_count", lambda: state.count)
    monkeypatch.setattr(pygame.joystick, "Joystick", make_joystick)
    return state


def make_controller():
    return xc.XBoxController(20, start_worker=False)


def test_forward_stick_gives_forward_command(fake_pygame):
    c = make_controller()
    c.p1.axes[1] = -1.0  # left stick up
    cmds = c.get_commands()[0]
    assert cmds[0] == pytest.approx(0.15)


def test_waits_for_controller_at_startup(fake_pygame, monkeypatch):
    fake_pygame.count = 0
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 3:
            fake_pygame.count = 1  # controller turned on while waiting

    monkeypatch.setattr(xc.time, "sleep", fake_sleep)
    c = make_controller()
    assert c.p1 is not None
    assert len(sleeps) == 3


def test_disconnect_gives_zero_commands_and_reconnect_restores_input(fake_pygame):
    c = make_controller()
    c.p1.axes[1] = -1.0
    assert c.get_commands()[0][0] == pytest.approx(0.15)

    fake_pygame.count = 0
    fake_pygame.events = [SimpleNamespace(type=pygame.JOYDEVICEREMOVED, instance_id=0)]
    out = c.get_commands()
    assert c.p1 is None
    np.testing.assert_allclose(out[0], np.zeros(7))
    assert out[7] == 0.0 and out[8] == 0.0

    # still disconnected: stays at zero
    np.testing.assert_allclose(c.get_commands()[0], np.zeros(7))

    fake_pygame.count = 1
    fake_pygame.events = [SimpleNamespace(type=pygame.JOYDEVICEADDED, device_index=0)]
    c.get_commands()
    assert c.p1 is fake_pygame.opened[1]
    c.p1.axes[2] = -1.0  # right stick left
    assert c.get_commands()[0][2] == pytest.approx(1.0)


def test_removal_of_another_device_is_ignored(fake_pygame):
    c = make_controller()
    fake_pygame.events = [SimpleNamespace(type=pygame.JOYDEVICEREMOVED, instance_id=99)]
    c.get_commands()
    assert c.p1 is fake_pygame.opened[0]


def test_watchdog_zeroes_commands_when_no_fresh_command(fake_pygame, monkeypatch):
    c = make_controller()
    c.p1.axes[1] = -1.0
    now = [1000.0]
    monkeypatch.setattr(xc.time, "time", lambda: now[0])

    c.cmd_queue.put(c.get_commands())
    assert c.get_last_command()[0][0] == pytest.approx(0.15)

    now[0] += xc.WATCHDOG_TIMEOUT / 2
    assert c.get_last_command()[0][0] == pytest.approx(0.15)  # within the timeout

    now[0] += xc.WATCHDOG_TIMEOUT
    np.testing.assert_allclose(c.get_last_command()[0], np.zeros(7))


def test_event_error_while_waiting_still_connects(fake_pygame, monkeypatch):
    fake_pygame.count = 0
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 2:
            fake_pygame.count = 1
            fake_pygame.event_errors = 1

    monkeypatch.setattr(xc.time, "sleep", fake_sleep)
    c = make_controller()
    assert c.p1 is fake_pygame.opened[0]


def test_event_error_hiding_reconnect_is_recovered_from_count(fake_pygame):
    c = make_controller()
    fake_pygame.count = 0
    fake_pygame.events = [SimpleNamespace(type=pygame.JOYDEVICEREMOVED, instance_id=0)]
    c.get_commands()
    assert c.p1 is None

    # the JOYDEVICEADDED event is lost in the failing event.get()
    fake_pygame.count = 1
    fake_pygame.event_errors = 1
    c.get_commands()
    c.get_commands()
    assert c.p1 is fake_pygame.opened[1]


def test_event_error_hiding_disconnect_is_recovered_from_count(fake_pygame):
    c = make_controller()
    c.p1.axes[1] = -1.0
    fake_pygame.count = 0
    fake_pygame.event_errors = 1  # the JOYDEVICEREMOVED event is lost
    out = c.get_commands()
    assert c.p1 is None
    np.testing.assert_allclose(out[0], np.zeros(7))
