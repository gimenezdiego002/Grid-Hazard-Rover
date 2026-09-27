"""Virtual joint interpolation, teaching, payload and fault lifecycle checks."""

from concurrent.futures import ThreadPoolExecutor
import pytest

from relay_gateway.arm_simulator import ArmSimulator, ArmSimulatorConflict, HOME, PICK


def action(sim, verb, **params):
    action.sequence += 1
    return sim.apply(sim.run_id, f"test-{action.sequence}", verb, **params)


action.sequence = 0


def finish(sim):
    for _ in range(100):
        if sim.status != "running":
            return sim.snapshot()
        action(sim, "step", dt_s=0.5, steps=20)
    pytest.fail("Virtual arm did not finish a finite routine")


def test_preset_visits_grasp_release_and_home_without_physical_claims():
    sim = ArmSimulator()
    action(sim, "start")
    result = finish(sim)
    assert result["status"] == "completed" and result["elapsed_s"] == 14
    assert result["joints_deg"] == HOME
    assert result["payload"]["state"] == "placed" and result["progress"] == 1
    assert any(event["kind"] == "virtual_grasp" for event in result["events"])
    assert any(event["kind"] == "virtual_release" for event in result["events"])
    assert not result["physical_connected"] and not result["actuation_enabled"]
    assert result["commands_dispatched"] == result["network_requests"] == result["model_calls"] == result["api_cloud_cost_usd"] == 0
    assert result["physical_result"] is None


def test_manual_interpolation_capture_and_replay_preserve_explicit_angles_and_durations():
    sim = ArmSimulator()
    action(sim, "capture", name="home", duration_s=1)
    target = [110, 80, 100, 120, 60, 40]
    action(sim, "pose", joints_deg=target, duration_s=2)
    midway = action(sim, "step", dt_s=1)
    assert midway["joints_deg"] == [(a + b) / 2 for a, b in zip(HOME, target)]
    assert midway["waypoint_progress"] == 0.5 and midway["status"] == "running"
    result = action(sim, "step", dt_s=1)
    assert result["joints_deg"] == target and result["status"] == "completed"
    assert result["payload"]["state"] == "at_source"  # Arbitrary poses do not invent marker contact.
    captured = action(sim, "capture", name="inspection", duration_s=1.5)
    assert captured["recorded_routine"][-1]["joints_deg"] == target
    action(sim, "replay", repeats=3)
    replay = finish(sim)
    assert replay["repeat_index"] == replay["repeats"] == 3
    assert replay["joints_deg"] == target
    assert replay["elapsed_s"] == 9.5
    assert replay["recording"]["schema_version"] == "arm-simulation/1"
    assert replay["recording"]["angle_unit"] == "degrees"
    assert "profile" not in replay["recording"] and "initial_pose" not in replay["recording"]


def test_manual_grip_requires_proximity_and_release_away_from_destination_is_dropped():
    sim = ArmSimulator()
    action(sim, "pose", joints_deg=[*HOME[:5], 110], duration_s=1)
    assert finish(sim)["payload"]["state"] == "at_source"
    action(sim, "pose", joints_deg=[*PICK[:5], 110], duration_s=1)
    assert finish(sim)["payload"]["state"] == "held"
    action(sim, "pose", joints_deg=PICK, duration_s=1)
    result = finish(sim)
    assert result["payload"]["state"] == "dropped"


@pytest.mark.parametrize("fault", ["joint_stall", "grip_loss"])
def test_injected_fault_latches_until_explicit_recovery_then_resume(fault):
    sim = ArmSimulator()
    action(sim, "start")
    action(sim, "step", dt_s=1, steps=5)
    before = sim.snapshot()
    assert before["payload"]["state"] == "held"
    faulted = action(sim, "inject_fault", fault=fault)
    assert faulted["status"] == "faulted"
    if fault == "grip_loss":
        assert faulted["payload"]["state"] == "dropped"
    for verb in ("step", "resume", "start"):
        with pytest.raises(ArmSimulatorConflict):
            action(sim, verb)
    assert sim.snapshot() == faulted
    recovered = action(sim, "clear_fault")
    assert recovered["status"] == "paused" and recovered["payload"] == before["payload"]
    assert recovered["elapsed_s"] == before["elapsed_s"]
    assert recovered["joints_deg"] == before["joints_deg"]
    action(sim, "resume")
    assert finish(sim)["payload"]["state"] == "placed"


def test_paused_step_stays_paused_until_terminal_and_stop_preserves_evidence():
    sim = ArmSimulator()
    action(sim, "start")
    action(sim, "pause")
    step = action(sim, "step", dt_s=0.5, steps=2)
    assert step["status"] == "paused" and step["elapsed_s"] == 1
    action(sim, "capture", name="paused-pose")
    stopped = action(sim, "stop")
    assert stopped["elapsed_s"] == 1 and len(stopped["recorded_routine"]) == 1
    with pytest.raises(ArmSimulatorConflict):
        action(sim, "resume")
    reset = action(sim, "reset")
    assert reset["status"] == "idle" and not reset["recorded_routine"]
    action(sim, "start")
    action(sim, "pause")
    assert action(sim, "step", dt_s=1, steps=20)["status"] == "completed"


@pytest.mark.parametrize("verb,params", [
    ("pose", {"joints_deg": [90] * 5}), ("pose", {"joints_deg": [True] * 6}),
    ("pose", {"joints_deg": [181] * 6}), ("pose", {"joints_deg": [float("nan")] * 6}),
    ("pose", {"joints_deg": HOME, "duration_s": 0}), ("start", {"repeats": True}),
    ("start", {"repeats": 6}), ("capture", {"name": "bad\nname"}),
    ("start", {"physical": True}),
])
def test_invalid_commands_do_not_mutate_scene(verb, params):
    sim = ArmSimulator()
    before = sim.snapshot()
    with pytest.raises(ValueError):
        action(sim, verb, **params)
    assert sim.snapshot() == before


def test_recording_limits_and_total_duration_rejection_are_transactional():
    sim = ArmSimulator()
    for index in range(20):
        action(sim, "capture", name=f"pose-{index}", duration_s=10)
    before = sim.snapshot()
    with pytest.raises(ArmSimulatorConflict):
        action(sim, "capture")
    assert sim.snapshot() == before
    with pytest.raises(ValueError):
        action(sim, "replay")
    assert sim.snapshot() == before
    assert action(sim, "clear_recording")["recorded_routine"] == []


def test_action_retry_concurrency_conflict_and_reset_staleness():
    sim = ArmSimulator()
    action(sim, "start")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: sim.apply(sim.run_id, "same", "step", dt_s=1), range(6)))
    assert all(result["elapsed_s"] == 1 for result in results)
    with pytest.raises(ArmSimulatorConflict):
        sim.apply(sim.run_id, "same", "step", dt_s=2)
    old = sim.run_id
    fresh = sim.apply(old, "reset", "reset")
    assert fresh["run_id"] != old
    assert sim.apply(old, "reset", "reset")["run_id"] == fresh["run_id"]
    with pytest.raises(ArmSimulatorConflict):
        sim.apply(old, "stale", "start")


def test_finite_session_and_action_capacity_keep_stop_and_reset_available():
    sim = ArmSimulator()
    sim.MAX_ELAPSED_S = 1.5
    action(sim, "start")
    result = action(sim, "step", dt_s=2)
    assert result["elapsed_s"] == 1.5 and result["status"] == "stopped"
    action(sim, "reset")
    sim.MAX_ACTIONS = 1
    action(sim, "start")
    with pytest.raises(ArmSimulatorConflict):
        action(sim, "step")
    assert action(sim, "stop")["status"] == "stopped"
    assert action(sim, "reset")["status"] == "idle"
