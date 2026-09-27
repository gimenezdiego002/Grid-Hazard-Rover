"""Status decoding must not mistake partial or malformed BLE frames for feedback."""

from robotcode.arm.ble_diagnostics import parse_response, BATTERY_QUERY, POSITIONS_QUERY


def test_voltage_decodes_observed_lsc_reply():
    assert BATTERY_QUERY == bytes.fromhex("55 55 02 0f")
    assert parse_response(bytes.fromhex("55 55 04 0f c9 1e"), "battery") == {"voltage_mv": 7881}


def test_partial_or_unrelated_notifications_are_not_feedback():
    for frame in (b"", bytes.fromhex("55 55 04 0f c9"), bytes.fromhex("55 55 02 07")):
        assert parse_response(frame, "battery") is None
        assert parse_response(frame, "positions") is None


def test_position_frame_requires_all_six_unique_ids():
    assert POSITIONS_QUERY == bytes.fromhex("55 55 09 15 06 01 02 03 04 05 06")
    frame = bytes.fromhex("55 55 15 15 06") + b"".join(bytes([i]) + (1200 + i).to_bytes(2, "little") for i in range(1, 7))
    assert parse_response(frame, "positions")["controller_reported_positions"] == {i: 1200 + i for i in range(1, 7)}
    assert parse_response(frame[:-1], "positions") is None
    duplicate = bytearray(frame)
    duplicate[8] = 1
    assert parse_response(duplicate, "positions") is None
    invalid = bytearray(frame)
    invalid[8] = 7
    assert parse_response(invalid, "positions") is None


def test_noise_prefix_does_not_change_voltage():
    assert parse_response(b"noise" + bytes.fromhex("55 55 04 0f c9 1e"), "battery")["voltage_mv"] == 7881
