import urllib.error
import urllib.request

from conftest import post, read_first_sse_event

from tools.bench.hardware import FakeHardware
from tools.bench.server import BenchState, main


def test_stop_all_only_after_last_client():
    hw = FakeHardware()
    st = BenchState(hw)
    st.client_connected()
    st.client_connected()
    st.client_disconnected()
    assert ("stop_all",) not in hw.calls
    st.client_disconnected()
    assert ("stop_all",) in hw.calls


def test_set_pull_rejects_reserved_pin(server_url):
    r = post(server_url, "set_pull", {"bcm": 14, "pull": "pu"})
    assert r.status == 400 and "予約" in r.json()["error"]


def test_set_pull_rejects_in_use_pin(server_url):
    r = post(server_url, "set_pull", {"bcm": 22, "pull": "pd"})
    assert r.status == 400 and "使用中" in r.json()["error"]


def test_set_pull_free_pin(server_url, fake_hw):
    assert post(server_url, "set_pull", {"bcm": 5, "pull": "pu"}).status == 200
    assert ("set_pull", 5, "pu") in fake_hw.calls


def test_servo_jog_flow(server_url, fake_hw):
    assert post(server_url, "servo_torque_on", {"id": 22, "kp": 8}).status == 200
    assert post(server_url, "servo_jog", {"id": 22, "direction": 1}).status == 200
    assert post(server_url, "servo_torque_on", {"id": 22, "kp": 32}).status == 400


def test_torque_on_other_axis_turns_previous_off(server_url, fake_hw):
    post(server_url, "servo_torque_on", {"id": 22, "kp": 8})
    post(server_url, "servo_torque_on", {"id": 13, "kp": 8})
    assert ("servo_torque_off", 22) in fake_hw.calls


def test_jog_refused_past_limit_over_http(server_url):
    post(server_url, "servo_torque_on", {"id": 22, "kp": 8})
    codes = [post(server_url, "servo_jog", {"id": 22, "direction": 1}).status for _ in range(7)]
    assert codes == [200] * 6 + [400]


def test_unknown_action_is_400(server_url):
    assert post(server_url, "launch_rocket", {}).status == 400


def test_led_auto_off_after_30s():
    hw = FakeHardware()
    t = [0.0]
    st = BenchState(hw, clock=lambda: t[0])
    st.handle("led", {"name": "左目", "duty": 100})
    t[0] = 29.9
    st.tick()
    assert hw.calls[-1] == ("set_led", "左目", 100)
    t[0] = 30.1
    st.tick()
    assert hw.calls[-1] == ("set_led", "左目", 0)


def test_ear_value_clamped_to_limit():
    hw = FakeHardware()
    BenchState(hw, ear_limit=0.5).handle("ear", {"side": "左", "value": 0.9})
    assert hw.calls[-1] == ("set_ear", "左", 0.5, 0.5)


def test_servo_read_error_does_not_crash_stream():
    hw = FakeHardware()
    hw.fail_servos = True
    snap = BenchState(hw).snapshot()
    assert snap["servo_error"] and "pins" in snap


def test_imu_error_counted():
    hw = FakeHardware()
    hw.fail_imu = True
    st = BenchState(hw)
    st.snapshot()
    snap = st.snapshot()
    assert snap["imu"]["errors"] == 2


def test_feet_edges_recorded():
    hw = FakeHardware()
    st = BenchState(hw)
    hw.read_feet = lambda: {"左足": 1, "右足": 1}
    st.poll_feet(now=0.0)
    hw.read_feet = lambda: {"左足": 0, "右足": 1}
    st.poll_feet(now=1.0)
    assert st.snapshot()["edges"][-1] == [1.0, "左足", 1, 0]


def test_events_stream_sends_json(server_url):
    first = read_first_sse_event(server_url + "/events")
    assert {"pins", "feet", "imu", "servos", "status"} <= set(first)


def test_index_served(server_url):
    with urllib.request.urlopen(server_url + "/", timeout=5) as r:
        assert r.status == 200 and b"<title>" in r.read()


def test_static_path_traversal_blocked(server_url):
    try:
        urllib.request.urlopen(server_url + "/static/..%2Fserver.py", timeout=5)
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_ear_limit_above_one_rejected():
    assert main(["--fake", "--ear-limit", "1.5"]) == 2
