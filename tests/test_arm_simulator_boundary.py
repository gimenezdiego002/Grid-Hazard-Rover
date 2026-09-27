"""Virtual teaching exports cannot become physical LeArm command recordings."""

import json

import pytest

from relay_gateway.arm_simulator import ArmSimulator
from robotcode.arm.motion import validate_recording
from robotcode.arm.motion_live import validate_live_recording


def test_captured_virtual_routine_is_rejected_by_physical_recording_parsers():
    arm = ArmSimulator()
    initial = arm.snapshot()
    arm.apply(initial["run_id"], "capture-virtual", "capture", name="virtual-home", duration_s=2)
    # Match a downloaded/exported JSON round trip, not only an internal object.
    exported = json.loads(json.dumps(arm.snapshot()["recording"]))
    assert len(exported["poses"]) == 1
    assert exported["schema_version"] == "arm-simulation/1"
    assert exported["recording_kind"] == "simulated_joint_angles"
    assert exported["angle_unit"] == "degrees"
    assert exported["simulated"] is True and exported["actuation_enabled"] is False
    assert not {"profile", "joint_bounds_us", "initial_pose", "pulses_us"} & exported.keys()
    for parser in (validate_recording, validate_live_recording):
        with pytest.raises(ValueError):
            parser(exported)


def test_entire_scene_export_cannot_be_read_as_physical_motion_even_when_completed():
    arm = ArmSimulator()
    run_id = arm.snapshot()["run_id"]
    arm.apply(run_id, "start-virtual", "start")
    completed = arm.apply(run_id, "finish-virtual", "step", dt_s=2, steps=20)
    assert completed["status"] == "completed"
    assert completed["payload"]["state"] == "placed"
    assert completed["physical_result"] is None
    assert completed["commands_dispatched"] == 0
    assert completed["physical_connected"] is False
    with pytest.raises(ValueError):
        validate_live_recording(json.loads(json.dumps(completed)))
