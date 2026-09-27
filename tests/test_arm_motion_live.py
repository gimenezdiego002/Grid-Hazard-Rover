import asyncio
import builtins
from copy import deepcopy
import json
import sys
from types import SimpleNamespace

import pytest

from robotcode.arm.motion import append_pose, encode_joint_move, load_json, new_recording, save_recording
from robotcode.arm.motion_live import (
    MotionUncertain, _checked_pose, _replay_connected, _teach_connected,
    run, send_pose, validate_live_recording,
)


@pytest.fixture
def profile():
    return {"schema_version": "1", "profile_id": "test-only", "controller_family": "LSC",
            "units": "microseconds", "reviewed_by": "test-fixture",
            "joint_bounds_us": [[1000, 2000] for _ in range(6)]}


@pytest.fixture
def recording(profile):
    record = new_recording("test", profile, initial_pose=[1500] * 6)
    return append_pose(record, [1550] * 6, 1000)


class FakeClient:
    def __init__(self, fail_at=None, cancel=False):
        self.writes, self.fail_at, self.cancel = [], fail_at, cancel

    async def write_gatt_char(self, characteristic, frame, response):
        self.writes.append(frame)
        if len(self.writes) == self.fail_at:
            if self.cancel:
                raise asyncio.CancelledError
            raise OSError("ambiguous partial write")


async def no_wait(seconds):
    assert seconds >= 1


def test_single_joint_matches_official_protocol_example(profile):
    assert encode_joint_move(1, 2000, 1000, profile) == bytes.fromhex("55 55 08 03 01 e8 03 01 d0 07")


def test_initial_reference_is_explicit_unmeasured_and_roundtrips(recording, tmp_path):
    path = tmp_path / "record.json"
    save_recording(path, recording)
    assert validate_live_recording(load_json(path)) == recording
    assert recording["initial_pose"]["source"] == "operator_commanded_reference"
    assert recording["initial_pose"]["measured"] is False
    invalid = deepcopy(recording)
    invalid["initial_pose"]["measured"] = True
    with pytest.raises(ValueError):
        validate_live_recording(invalid)


@pytest.mark.parametrize("previous,pulses,duration", [
    ([1500] * 6, [1601] * 6, 1000), ([1500] * 6, [1550] * 6, 999),
    ([1500] * 6, [999] * 6, 1000), ([True] * 6, [1500] * 6, 1000),
])
def test_invalid_live_step_never_writes(profile, previous, pulses, duration):
    client = FakeClient()
    with pytest.raises(ValueError):
        asyncio.run(send_pose(client, object(), profile=profile, previous=previous,
                              pulses_us=pulses, duration_ms=duration, wait=no_wait))
    assert client.writes == []


def test_repeat_seam_is_validated_before_first_write(profile):
    record = new_recording("test", profile, initial_pose=[1500] * 6)
    for value in (1600, 1700, 1800):
        record = append_pose(record, [value] * 6, 1000)
    assert validate_live_recording(record, 1) == record
    with pytest.raises(ValueError):
        validate_live_recording(record, 2)


def test_missing_reference_prevents_live_replay(profile):
    record = append_pose(new_recording("test", profile), [1500] * 6, 1000)
    with pytest.raises(ValueError):
        validate_live_recording(record)


def test_sends_six_small_frames_then_waits_without_claiming_motion(profile):
    client, waits = FakeClient(), []
    async def wait(seconds):
        waits.append(seconds)
        assert len(client.writes) == 6
    receipt = asyncio.run(send_pose(client, object(), profile=profile, previous=[1500] * 6,
                                    pulses_us=[1550] * 6, duration_ms=1000, wait=wait))
    assert [len(frame) for frame in client.writes] == [10] * 6
    assert [frame[7] for frame in client.writes] == list(range(1, 7))
    assert waits == [1.0]
    assert receipt["writes_accepted"] == 6 and receipt["wait_elapsed"]
    assert not receipt["simultaneous"] and receipt["physical_result"] is None


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_write_aborts_without_remaining_frames_or_stop_group(profile, cancel):
    client = FakeClient(fail_at=3, cancel=cancel)
    with pytest.raises(MotionUncertain) as error:
        asyncio.run(send_pose(client, object(), profile=profile, previous=[1500] * 6,
                              pulses_us=[1550] * 6, duration_ms=1000, wait=no_wait))
    assert len(client.writes) == 3
    assert error.value.receipt["writes_accepted"] == 2
    assert error.value.receipt["frames_attempted"] == 3
    assert error.value.receipt["outcome"] == "unknown"


def test_cancel_during_wait_keeps_outcome_unknown(profile):
    async def cancelled_wait(seconds):
        raise asyncio.CancelledError
    with pytest.raises(MotionUncertain) as error:
        asyncio.run(send_pose(FakeClient(), object(), profile=profile, previous=[1500] * 6,
                              pulses_us=[1550] * 6, duration_ms=1000, wait=cancelled_wait))
    assert error.value.receipt["writes_accepted"] == 6
    assert not error.value.receipt["wait_elapsed"]


def test_teaching_saves_only_fully_sent_and_timed_commands(profile, tmp_path):
    record = new_recording("test", profile, initial_pose=[1500] * 6)
    lines = iter(["1550 1550 1550 1550 1550 1550 1000", "1600 1600 1600 1600 1600 1600 1000"])
    path, client = tmp_path / "record.json", FakeClient(fail_at=8)
    result = asyncio.run(_teach_connected(client, object(), record, path,
                        read_line=lambda _: next(lines), wait=no_wait))
    assert result["outcome"] == "unknown"
    saved = load_json(path)
    assert len(saved["waypoints"]) == 1 and saved["waypoints"][0]["pulses_us"] == [1550] * 6
    assert saved["initial_pose"] == record["initial_pose"]


def test_replay_failure_stops_later_waypoints(recording):
    record = append_pose(recording, [1600] * 6, 1000)
    client = FakeClient(fail_at=2)
    result = asyncio.run(_replay_connected(client, object(), record, 2, wait=no_wait))
    assert result["outcome"] == "unknown" and len(client.writes) == 2


def test_default_teach_and_replay_never_import_bluetooth_or_save(recording, tmp_path, monkeypatch):
    profile_path, record_path, new_path = tmp_path / "profile.json", tmp_path / "record.json", tmp_path / "new.json"
    profile_path.write_text(json.dumps(recording["profile"]))
    save_recording(record_path, recording)
    original = builtins.__import__
    def blocked(name, *args, **kwargs):
        assert name != "bleak"
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", blocked)
    args = SimpleNamespace(command="teach", profile=profile_path, start_pulses=[1500] * 6,
                           recording=new_path, name="test", live=False)
    assert asyncio.run(run(args))["motion_commands_sent"] == 0
    assert not new_path.exists()
    args = SimpleNamespace(command="replay", recording=record_path, repeats=1, live=False)
    preview = asyncio.run(run(args))
    assert preview["mode"] == "dry_run" and not preview["simultaneous"]
    assert "frame_hex" not in preview["events"][0]
    assert [len(bytes.fromhex(frame)) for frame in preview["events"][0]["joint_frames_hex"]] == [10] * 6


def test_live_gates_reject_missing_operator_confirmation(recording, tmp_path):
    path = tmp_path / "record.json"
    save_recording(path, recording)
    for present, confirmed in ((False, False), (True, False), (False, True)):
        args = SimpleNamespace(command="replay", recording=path, repeats=1, live=True,
                               operator_present=present, initial_pose_confirmed=confirmed)
        with pytest.raises(ValueError):
            asyncio.run(run(args))


def test_disconnect_hang_is_bounded_after_replay(recording, tmp_path, monkeypatch):
    import robotcode.arm.motion_live as module
    path = tmp_path / "record.json"
    save_recording(path, recording)
    client = FakeClient()
    async def connect():
        pass
    async def disconnect():
        await asyncio.Future()
    async def discover(*args, **kwargs):
        return object()
    async def preflight(*args):
        return object(), 7800
    async def replay(*args):
        return {"outcome": "commands_accepted_and_wait_elapsed", "physical_result": None}
    client.connect, client.disconnect = connect, disconnect
    monkeypatch.setattr(module, "DISCONNECT_TIMEOUT", 0.001)
    monkeypatch.setattr(module, "_preflight", preflight)
    monkeypatch.setattr(module, "_replay_connected", replay)
    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(
        BleakClient=lambda *a, **k: client,
        BleakScanner=SimpleNamespace(find_device_by_address=discover)))
    args = SimpleNamespace(command="replay", recording=path, repeats=1, live=True,
                           operator_present=True, initial_pose_confirmed=True, address="fixture", handle=24)
    result = asyncio.run(run(args))
    assert result["outcome"] == "unknown" and result["reason"] == "disconnect_failed"
