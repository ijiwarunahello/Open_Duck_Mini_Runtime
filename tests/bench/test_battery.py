from tools.bench.battery import summarize


def test_median_and_levels():
    assert summarize([7.1] * 4 + [7.2] * 10) == {"volts": 7.2, "level": "low"}
    assert summarize([8.0, 8.1, None]) == {"volts": 8.05, "level": "ok"}
    assert summarize([7.0, 6.9, 7.0])["level"] == "critical"
    assert summarize([7.3])["level"] == "ok"


def test_all_none():
    assert summarize([None, None]) == {"volts": None, "level": None}
    assert summarize([]) == {"volts": None, "level": None}
