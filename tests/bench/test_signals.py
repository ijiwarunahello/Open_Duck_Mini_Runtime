import pytest

from tools.bench.signals import EdgeLog, ear_duty_percent, to_runtime_frame


def test_edge_log_records_changes_only():
    e = EdgeLog()
    e.update("左足", 1, 0.0)
    e.update("左足", 1, 0.1)
    e.update("左足", 0, 0.2)
    assert e.events == [(0.2, "左足", 1, 0)]


def test_chatter_counts_fast_reversals():
    e = EdgeLog()
    e.update("右足", 1, 0.0)
    e.update("右足", 0, 1.00)
    e.update("右足", 1, 1.02)
    e.update("右足", 0, 1.03)
    e.update("右足", 1, 2.00)
    assert e.chatter["右足"] == 2


def test_edge_log_keeps_only_maxlen_events():
    e = EdgeLog(maxlen=3)
    e.update("x", 0, 0.0)
    for i in range(1, 6):
        e.update("x", i % 2, float(i))
    assert [ev[0] for ev in e.events] == [3.0, 4.0, 5.0]


def test_runtime_frame_matches_2026_11_22_measurements():
    x, y, z = to_runtime_frame((0.33, 0.78, -9.85), upside_down=False)
    assert (x, y, z) == pytest.approx((-0.78, 0.33, -9.85))
    assert to_runtime_frame((0.33, 0.78, -9.85), upside_down=True) == pytest.approx((-0.78, -0.33, 9.85))


def test_ear_duty_clamped_and_signed():
    assert ear_duty_percent(0.0, 0.5, 1) == pytest.approx(7.5)
    assert ear_duty_percent(1.0, 0.5, 1) == pytest.approx(8.75)
    assert ear_duty_percent(0.5, 0.5, -1) == pytest.approx(6.25)
