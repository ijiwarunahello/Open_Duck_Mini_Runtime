from tools.bench.pins import HEADER, PinState, can_set_pull, parse_pinctrl


def test_header_maps_known_pins():
    assert HEADER[15] == 22 and HEADER[13] == 27 and HEADER[8] == 14
    assert HEADER[2] == "5V" and HEADER[6] == "GND" and HEADER[1] == "3V3"
    assert sum(1 for v in HEADER.values() if isinstance(v, int)) == 28


def test_parse_pinctrl_lines():
    text = (
        "22: ip    pu | hi // GPIO22 = input\n"
        "24: op -- -- | hi\n"
        "20: a0    -- | lo // GPIO20 = PCM_DIN\n"
    )
    s = parse_pinctrl(text)
    assert s[22] == PinState(22, "ip", "pu", 1)
    assert s[24] == PinState(24, "op", "--", 1)
    assert s[20] == PinState(20, "a0", "--", 0)


def test_can_set_pull_only_free_pins():
    assert can_set_pull(5) and can_set_pull(26)
    assert not any(can_set_pull(b) for b in (0, 1, 4, 14, 15, 2, 22, 23, 27))
