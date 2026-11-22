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


def test_edge_times_are_wall_clock():
    hw = FakeHardware()
    st = BenchState(hw, clock=lambda: 5.0)
    hw.read_feet = lambda: {"左足": 1, "右足": 1}
    st.poll_feet()
    hw.read_feet = lambda: {"左足": 0, "右足": 1}
    st.poll_feet()
    assert st.snapshot()["edges"][-1][0] > 1_000_000_000


def test_ear_pwm_released_after_idle():
    hw = FakeHardware()
    t = [0.0]
    st = BenchState(hw, clock=lambda: t[0])
    st.handle("ear", {"side": "左", "value": 0.2})
    t[0] = 0.4
    st.tick()
    assert ("release_ear", "左") not in hw.calls
    st.handle("ear", {"side": "左", "value": 0.3})
    t[0] = 0.8
    st.tick()
    assert ("release_ear", "左") not in hw.calls
    t[0] = 0.95
    st.tick()
    assert hw.calls[-1] == ("release_ear", "左")


def test_led_auto_off_without_any_client():
    # Review #1: the 30 s LED limit must not depend on a browser pulling snapshots.
    import time

    hw = FakeHardware()
    t = [0.0]
    st = BenchState(hw, clock=lambda: t[0])
    st.handle("led", {"name": "左目", "duty": 100})
    t[0] = 31.0
    st.start_feet_thread()
    deadline = time.monotonic() + 1.0
    while ("set_led", "左目", 0) not in hw.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ("set_led", "左目", 0) in hw.calls


def test_stream_socket_gives_up_on_silent_peer():
    # Review #1: a client that vanishes without FIN must be dropped within seconds, not ~15 min.
    import socket

    import pytest

    from tools.bench.server import STREAM_USER_TIMEOUT_MS, configure_stream_socket

    if not hasattr(socket, "TCP_USER_TIMEOUT"):
        pytest.skip("TCP_USER_TIMEOUT is Linux-only")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        configure_stream_socket(s)
        assert s.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == STREAM_USER_TIMEOUT_MS
        assert s.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
    assert STREAM_USER_TIMEOUT_MS <= 5000


def test_stop_all_failure_is_reported_and_keeps_active_axis(server_url, fake_hw):
    # Review #2: a failed torque release must not look like success.
    assert post(server_url, "servo_torque_on", {"id": 10, "kp": 8}).status == 200
    fake_hw.fail_stop = True
    r = post(server_url, "stop_all", {})
    assert r.status == 500 and not r.json()["ok"]
    assert read_first_sse_event(f"{server_url}/events")["active_servo"] == 10


def test_disconnect_survives_stop_all_failure():
    hw = FakeHardware()
    hw.fail_stop = True
    st = BenchState(hw)
    st.client_connected()
    st.client_disconnected()  # must not raise into the handler thread
    assert st._clients == 0


def test_status_and_pins_errors_do_not_end_stream():
    # Review #3: vcgencmd / pinctrl timeouts must not kill the stream (and trigger stop_all).
    hw = FakeHardware()
    hw.fail_status = True
    hw.fail_pins = True
    snap = BenchState(hw).snapshot()
    assert snap["status"]["error"] and snap["pins_error"]
    assert snap["pins"] == {}


def test_tick_tolerates_concurrent_stop_all():
    # Review #4: stop_all clearing the dicts between tick's copy and its delete must not raise.
    hw = FakeHardware()
    t = [0.0]
    st = BenchState(hw, clock=lambda: t[0])
    st.handle("led", {"name": "左目", "duty": 100})
    st.handle("ear", {"side": "左", "value": 0.1})
    t[0] = 100.0
    real_set_led = hw.set_led

    def set_led_then_clear(name, duty):
        real_set_led(name, duty)
        st.led_until.clear()
        st.ear_release_at.clear()

    hw.set_led = set_led_then_clear
    st.led_until["右目"] = 0.0  # second entry: its delete happens after the clear
    st.tick()
