"""Protocol fixtures verify an offline recorder; no values are hardware defaults."""

from copy import deepcopy
import json

import pytest

from robotcode.arm.motion import (
    append_pose, encode_action_group, encode_servo_move, load_json, main,
    new_recording, replace_pose, replay_preview, save_recording, validate_profile,
    validate_recording,
)


@pytest.fixture
def profile():
    # Test-only bounds, not approved limits or taught positions for a real arm.
    return {"schema_version": "1", "profile_id": "test-fixture", "controller_family": "LSC",
            "units": "microseconds", "reviewed_by": "test-fixture",
            "joint_bounds_us": [[1000, 2000] for _ in range(6)]}


@pytest.fixture
def recording(profile):
    return append_pose(new_recording("test-recording", profile), [1500] * 6, 1000)


def test_lsc_frame_length_servo_order_and_little_endian_duration_and_targets(profile):
    frame = encode_servo_move([1000, 1100, 1200, 1300, 1400, 2000], 1000, profile)
    assert frame == bytes.fromhex("55 55 17 03 06 e8 03 01 e8 03 02 4c 04 03 b0 04 04 14 05 05 78 05 06 d0 07")
    assert frame[2] == len(frame) - 2


def test_documented_action_group_example_and_no_infinite_loop():
    assert encode_action_group(8) == bytes.fromhex("55 55 05 06 08 01 00")
    for count in (0, -1, 6, True, 1.0):
        with pytest.raises(ValueError):
            encode_action_group(8, count)


def test_repeat_preview_is_finite_and_does_not_claim_execution(recording):
    original = deepcopy(recording)
    second = append_pose(recording, [1600] * 6, 500)
    result = replay_preview(second, repeats=2)
    assert recording == original
    assert [event["starts_at_ms"] for event in result["events"]] == [0, 1000, 1500, 2500]
    assert result["total_duration_ms"] == 3000
    assert result["commands_dispatched"] == result["api_cloud_cost_usd"] == 0
    assert result["simulated"] and not result["actuation_enabled"]
    assert not result["physical_positions_measured"] and result["physical_result"] is None
    assert replay_preview(second, 2) == result


def test_editor_preserves_input_and_rechecks_joint_bounds(recording):
    original = deepcopy(recording)
    edited = replace_pose(recording, 0, [1700] * 6, 500)
    assert edited["waypoints"][0]["pulses_us"] == [1700] * 6
    assert recording == original
    with pytest.raises(ValueError):
        replace_pose(recording, 0, [2100] * 6, 500)
    assert recording == original


@pytest.mark.parametrize("pulses,duration", [([1500] * 5, 1000), ([1500] * 7, 1000),
    ([999] * 6, 1000), ([2001] * 6, 1000), ([True] * 6, 1000), ([1500.0] * 6, 1000),
    ([1500] * 6, 99), ([1500] * 6, 10_001), ([1500] * 6, True),
    ([1500] * 6, float("nan"))])
def test_invalid_command_targets_are_rejected_before_encoding(profile, pulses, duration):
    with pytest.raises(ValueError):
        encode_servo_move(pulses, duration, profile)


@pytest.mark.parametrize("change", [
    {"reviewed_by": ""}, {"units": "degrees"}, {"controller_family": "LeArm_AI"},
    {"joint_bounds_us": []}, {"joint_bounds_us": [[2000, 1000]] * 6},
    {"joint_bounds_us": [[0, 65536]] * 6}, {"actuation_enabled": True},
])
def test_profile_requires_explicit_bounded_reviewed_joint_values(profile, change):
    with pytest.raises(ValueError):
        validate_profile(profile | change)


def test_serialization_rejects_physical_feedback_claims_and_unknown_instructions(recording):
    for changes in ({"physical_positions_measured": True}, {"physical_positions_measured": 0},
                    {"physical_result": "success"}, {"recording_kind": "measured_trajectory"}):
        with pytest.raises(ValueError):
            validate_recording(recording | changes)
    changed = deepcopy(recording)
    changed["waypoints"][0]["command"] = "calibrate"
    with pytest.raises(ValueError):
        validate_recording(changed)


def test_recording_and_repeat_capacity_are_enforced(profile):
    empty = new_recording("test", profile)
    with pytest.raises(ValueError):
        replay_preview(empty)
    long = empty
    for _ in range(12):
        long = append_pose(long, [1500] * 6, 10000)
    assert replay_preview(long)["total_duration_ms"] == 120_000
    with pytest.raises(ValueError):
        append_pose(long, [1500] * 6, 100)
    with pytest.raises(ValueError):
        replay_preview(long, 2)
    many = empty
    for _ in range(60):
        many = append_pose(many, [1500] * 6, 100)
    with pytest.raises(ValueError):
        append_pose(many, [1500] * 6, 100)


def test_json_roundtrip_exclusive_create_and_invalid_edit_preservation(recording, tmp_path):
    path = tmp_path / "recording.json"
    save_recording(path, recording)
    original = path.read_bytes()
    assert validate_recording(load_json(path)) == recording
    with pytest.raises(FileExistsError):
        save_recording(path, recording)
    with pytest.raises(ValueError):
        save_recording(path, recording | {"physical_positions_measured": True}, replace=True)
    assert path.read_bytes() == original
    updated = replace_pose(recording, 0, [1600] * 6, 800)
    save_recording(path, updated, replace=True)
    assert load_json(path) == updated


@pytest.mark.parametrize("contents", ['{"a":1,"a":2}', '{"a":NaN}', " " * 65537],
                         ids=["duplicate-field", "nonfinite-value", "oversized-file"])
def test_json_loading_rejects_duplicates_nonfinite_and_oversized_input(tmp_path, contents):
    path = tmp_path / "input.json"
    path.write_text(contents)
    with pytest.raises(ValueError):
        load_json(path)


def test_cli_create_add_edit_and_preview_is_offline(profile, tmp_path, capsys):
    profile_path, path = tmp_path / "profile.json", tmp_path / "recording.json"
    profile_path.write_text(json.dumps(profile))
    main(["create", "--profile", str(profile_path), "--name", "demo", "--recording", str(path)])
    main(["add", "--recording", str(path), "--pulses", *(["1500"] * 6), "--duration-ms", "1000"])
    main(["edit", "--recording", str(path), "--index", "0", "--pulses", *(["1600"] * 6), "--duration-ms", "800"])
    capsys.readouterr()
    main(["preview", "--recording", str(path), "--repeats", "2"])
    preview = json.loads(capsys.readouterr().out)
    assert preview["total_duration_ms"] == 1600 and preview["commands_dispatched"] == 0
    with pytest.raises(SystemExit) as error:
        main(["preview", "--recording", str(path), "--repeats", "0"])
    assert error.value.code == 2
