"""Navigation, review, economy and control invariants for the offline scene."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import math

import pytest

from relay_gateway.simulator import Simulator, SimulatorConflict, default_world, plan_path, point_free, segment_free


def command(sim, action, **params):
    command.sequence += 1
    return sim.apply(sim.run_id, f"test-{command.sequence}", action, **params)


command.sequence = 0


def until_boundary(sim):
    for _ in range(200):
        if sim.status != "running":
            return sim.snapshot()
        command(sim, "step", dt_s=0.5, steps=20)
    pytest.fail("Simulation failed to reach a bounded mission boundary")


def test_astar_routes_around_inflated_obstacles_and_rejects_unreachable():
    world = default_world()
    start, target = {"x": 2, "y": 8}, {"x": 20, "y": 8}
    path = plan_path(world, start, target)
    assert path and path[-1] == target
    assert all(point_free(world, p) for p in path)
    assert all(segment_free(world, a, b) for a, b in zip([start] + path, path))
    assert sum(math.dist((a["x"], a["y"]), (b["x"], b["y"])) for a, b in zip(path, path[1:])) > 18
    world["obstacles"].append({"id": "wall", "x": 12, "y": 0, "width": 1, "height": 16})
    assert plan_path(world, start, target) is None
    assert plan_path(world, start, {"x": 9, "y": 8}) is None
    assert plan_path(world, start, {"x": 0, "y": 1}) is None


def test_full_preset_review_boundary_and_return_have_traceable_economy():
    sim = Simulator()
    command(sim, "start")
    reviewed = until_boundary(sim)
    assert reviewed["status"] == "needs_review" and reviewed["stage"] == "human_review"
    assert reviewed["review"]["acknowledged"] is False
    rover, crawler = reviewed["robots"]
    assert math.hypot(rover["x"] - crawler["x"], rover["y"] - crawler["y"]) >= 0.8
    assert reviewed["arm_handoff"]["proposal"]["inspection"]["source_id"] == "freenove-hexapod"
    before = sim.snapshot()
    with pytest.raises(SimulatorConflict):
        command(sim, "step", steps=20)
    assert sim.snapshot() == before
    command(sim, "review", decision="acknowledge")
    result = until_boundary(sim)
    assert result["status"] == "completed"
    assert result["robots"][0]["x"] == 2 and result["robots"][0]["y"] == 2
    assert result["robots"][1]["x"] == 3 and result["robots"][1]["y"] == 12
    assert result["robots"][1]["payload_id"] is None
    assert result["review"]["environment_safety"] == "not_established"
    assert result["arm_handoff"]["actuation_enabled"] is False
    assert result["arm_handoff"]["proposal"]["commands_dispatched"] == 0
    assert not result["arm_handoff"]["proposal"]["human_review_performed"]
    metrics = result["metrics"]
    assert metrics["observations"] == metrics["eligible_observations"] + metrics["routine_filtered"]
    assert metrics["eligible_observations"] == metrics["governed_requests"] + metrics["duplicates_filtered"]
    assert metrics["baseline_requests"] == metrics["observations"]
    assert 0 < metrics["governed_requests"] < metrics["baseline_requests"]
    assert metrics["avoided_requests"] == metrics["baseline_requests"] - metrics["governed_requests"]
    assert metrics["governed_input_tokens"] == metrics["governed_requests"] * 1800
    assert metrics["actual_model_calls"] == metrics["actual_api_cost_usd"] == result["network_requests"] == 0
    assert metrics["energy_measured"] is False
    for robot in result["robots"]:
        assert robot["distance_m"] > 10 and robot["battery_pct"] < 100
        assert all(point_free(result["world"], point) for point in robot["trail"])
        assert len(robot["trail"]) <= 256


def test_two_runs_are_deterministic_at_same_step_and_clear_target_is_not_hazard():
    first, second = Simulator(), Simulator()
    for sim in (first, second):
        command(sim, "direct", target={"x": 5.0, "y": 4.0})
        command(sim, "step", dt_s=0.5, steps=10)
    a, b = first.snapshot(), second.snapshot()
    assert a["robots"] == b["robots"] and a["metrics"] == b["metrics"]
    assert any(o["finding"] == "directed_inspection" for o in a["observations"])
    assert not any(o["finding"] == "suspected_hazard" for o in a["observations"])


@pytest.mark.parametrize("target", [{"x": 9, "y": 8}, {"x": 0, "y": 0},
                                    {"x": 5, "y": float("inf")}, {"x": True, "y": 2},
                                    {"x": 2, "y": 3, "z": 4}, None])
def test_invalid_target_cannot_mutate_scene(target):
    sim = Simulator()
    before = sim.snapshot()
    with pytest.raises(ValueError):
        command(sim, "direct", target=target)
    assert sim.snapshot() == before


def test_pause_replay_stop_reset_and_stale_request_controls():
    sim = Simulator()
    command(sim, "start")
    before = sim.apply(sim.run_id, "one-step", "step", dt_s=1, steps=4)
    repeated = sim.apply(sim.run_id, "one-step", "step", dt_s=1, steps=4)
    assert repeated.pop("replayed") is True and repeated == before
    with pytest.raises(SimulatorConflict):
        sim.apply(sim.run_id, "one-step", "step", dt_s=1, steps=5)
    command(sim, "pause")
    paused = sim.snapshot()
    stepped = command(sim, "step", dt_s=0.5, steps=2)
    assert stepped["status"] == "paused" and stepped["elapsed_s"] == paused["elapsed_s"] + 1
    command(sim, "resume")
    command(sim, "stop")
    with pytest.raises(SimulatorConflict):
        command(sim, "resume")
    old = sim.run_id
    reset = sim.apply(old, "reset-one", "reset")
    assert reset["run_id"] != old and reset["elapsed_s"] == 0
    assert sim.apply(old, "reset-one", "reset")["run_id"] == reset["run_id"]
    with pytest.raises(SimulatorConflict):
        sim.apply(old, "late-step", "step")


@pytest.mark.parametrize("fault", ["sensor_dropout", "blocked_path", "low_battery"])
def test_fault_freezes_fleet_then_requires_explicit_recovery_and_resume(fault):
    sim = Simulator()
    command(sim, "start")
    command(sim, "step", steps=10)
    faulted = command(sim, "inject_fault", robot_id="rover", fault=fault)
    assert faulted["status"] == "faulted"
    before = sim.snapshot()
    with pytest.raises(SimulatorConflict):
        command(sim, "step")
    assert sim.snapshot() == before
    recovered = command(sim, "clear_fault")
    assert recovered["status"] == "paused"
    assert recovered["elapsed_s"] == before["elapsed_s"]
    assert all(robot["fault"] is None for robot in recovered["robots"])
    command(sim, "resume")
    assert until_boundary(sim)["stage"] == "human_review"


def test_modeled_allowance_refusal_cannot_be_overridden_by_review():
    sim = Simulator()
    command(sim, "start")
    command(sim, "inject_fault", robot_id="rover", fault="budget_exhausted")
    result = until_boundary(sim)
    assert result["status"] == "needs_review"
    assert result["metrics"]["budget_refused"] is True
    assert result["metrics"]["governed_requests"] == 0
    assert result["actual_model_calls"] == 0
    before = sim.snapshot()
    with pytest.raises(SimulatorConflict):
        command(sim, "review", decision="acknowledge")
    assert sim.snapshot() == before
    assert command(sim, "review", decision="abort")["status"] == "stopped"


def test_same_action_concurrently_advances_only_once_and_snapshots_are_copies():
    sim = Simulator()
    command(sim, "start")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: sim.apply(sim.run_id, "parallel", "step", steps=10), range(8)))
    assert all(result["elapsed_s"] == 5 for result in results)
    result = sim.snapshot()
    result["robots"][0]["x"] = -100
    result["world"]["obstacles"].clear()
    assert sim.snapshot()["robots"][0]["x"] >= 2
    assert sim.snapshot()["world"]["obstacles"]


@pytest.mark.parametrize("params", [{"dt_s": float("nan")}, {"dt_s": 3}, {"steps": 0},
                                    {"steps": True}, {"steps": 21}, {"dt_s": True}, {"live": True}])
def test_step_bounds_are_validated_before_motion(params):
    sim = Simulator()
    command(sim, "start")
    before = deepcopy(sim.snapshot())
    with pytest.raises(ValueError):
        command(sim, "step", **params)
    assert sim.snapshot() == before


def test_receipt_capacity_does_not_block_reset():
    sim = Simulator()
    sim.MAX_ACTIONS = 2
    command(sim, "start")
    command(sim, "pause")
    with pytest.raises(SimulatorConflict):
        command(sim, "resume")
    assert command(sim, "stop")["status"] == "stopped"
    assert command(sim, "reset")["status"] == "idle"


def test_paused_step_preserves_human_review_boundary():
    sim = Simulator()
    command(sim, "direct", target={"x": 5, "y": 4})
    command(sim, "pause")
    for _ in range(100):
        result = command(sim, "step", dt_s=2, steps=20)
        if result["status"] != "paused":
            break
    assert result["status"] == "needs_review" and result["stage"] == "human_review"
    assert "step" not in result["allowed_actions"]


def test_clear_fault_cannot_hide_replanning_failure():
    sim = Simulator()
    command(sim, "start")
    command(sim, "inject_fault", robot_id="rover", fault="sensor_dropout")
    # A persistent fixture obstruction still blocks the route after sensor recovery.
    sim.world["obstacles"].append({"id": "persistent-wall", "x": 4, "y": 0, "width": 1, "height": 16})
    result = command(sim, "clear_fault")
    assert result["status"] == "faulted"
    assert result["robots"][0]["fault"] == "blocked_path"
    assert "resume" not in result["allowed_actions"]


@pytest.mark.parametrize("target", [{"x": 0.4, "y": 0.4}, {"x": 23.6, "y": 15.6},
                                    {"x": 7.6, "y": 6}, {"x": 11.4, "y": 10.5},
                                    {"x": 3, "y": 12}])
def test_edge_and_obstacle_adjacent_targets_have_reachable_distinct_close_views(target):
    sim = Simulator()
    command(sim, "direct", target=target)
    result = until_boundary(sim)
    assert result["status"] == "needs_review" and result["stage"] == "human_review"
    rover, crawler = result["robots"]
    assert math.hypot(rover["x"] - crawler["x"], rover["y"] - crawler["y"]) >= 0.8
    assert point_free(result["world"], crawler)
