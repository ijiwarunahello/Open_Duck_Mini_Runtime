"""The walk script must not touch the servos before the controller is connected.

Under systemd the script starts at power-on; the duck should stay limp until the
operator connects the controller.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "v2_rl_walk_mujoco.py"


def install_fakes(monkeypatch, events):
    class FakeHWI:
        def __init__(self, duck_config, serial_port):
            events.append("hwi")
            self.joints = {f"j{i}": i for i in range(14)}
            self.init_pos = {name: 0.0 for name in self.joints}

        def set_kps(self, kps):
            events.append("set_kps")

        def set_kds(self, kds):
            events.append("set_kds")

        def turn_on(self):
            events.append("turn_on")

    class FakeController:
        def __init__(self, command_freq):
            events.append("controller")

    class FakeDuckConfig:
        def __init__(self, config_json_path=None):
            self.imu_upside_down = False
            self.imu_flip_xy = False
            self.imu_accel_bias = [0.0, 0.0, 0.0]
            self.start_paused = False
            self.phase_frequency_factor_offset = 0.0
            self.eyes = self.projector = self.speaker = self.antennas = False

    class Noop:
        def __init__(self, *args, **kwargs):
            pass

    fakes = {
        "rustypot_position_hwi": {"HWI": FakeHWI},
        "onnx_infer": {"OnnxInfer": Noop},
        "raw_imu": {"Imu": Noop},
        "poly_reference_motion": {"PolyReferenceMotion": Noop},
        "xbox_controller": {"XBoxController": FakeController},
        "feet_contacts": {"FeetContacts": Noop},
        "eyes": {"Eyes": Noop},
        "sounds": {"Sounds": Noop},
        "antennas": {"Antennas": Noop},
        "projector": {"Projector": Noop},
        "rl_utils": {"make_action_dict": Noop, "LowPassActionFilter": Noop},
        "duck_config": {"DuckConfig": FakeDuckConfig},
    }
    package = types.ModuleType("mini_bdx_runtime")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "mini_bdx_runtime", package)
    for name, attrs in fakes.items():
        module = types.ModuleType(f"mini_bdx_runtime.{name}")
        for attr, value in attrs.items():
            setattr(module, attr, value)
        monkeypatch.setitem(sys.modules, f"mini_bdx_runtime.{name}", module)


def load_walk_module(monkeypatch, events):
    install_fakes(monkeypatch, events)
    spec = importlib.util.spec_from_file_location("walk_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    return module


@pytest.fixture
def events():
    return []


def test_controller_connects_before_servos_are_touched(monkeypatch, events):
    walk = load_walk_module(monkeypatch, events)

    walk.RLWalk("model.onnx", commands=True)

    assert events[0] == "controller"
    assert events.index("controller") < events.index("hwi")
    assert events.index("controller") < events.index("turn_on")


def test_without_commands_torque_still_turns_on(monkeypatch, events):
    walk = load_walk_module(monkeypatch, events)

    walk.RLWalk("model.onnx", commands=False)

    assert "controller" not in events
    assert "turn_on" in events
