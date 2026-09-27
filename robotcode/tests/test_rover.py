import pytest

from robotcode.quarky_intellio_rover import RoverController
from robotcode.runtime import SimulatedIO


def scan(robot, command_id="scan", **overrides):
    return robot.command(command_id, "scan", **{
        "obstacle_cm": 100, "hazard_detected": False,
        "evidence_ref": "synthetic-image-1", **overrides})


def test_patrol_moves_only_with_scan_and_hazard_stops_and_reports_once():
    rover = RoverController()
    rover.command("patrol", "patrol", waypoints=["a", "b"])
    assert not any(r["action"] == "move_toward" for r in rover.io.records)
    scan(rover)
    rover.command("arrive", "arrive", target="a")
    result = scan(rover, "detection", hazard_detected=True)
    assert result["state"] == "reported"
    assert rover.io.records[-1]["action"] == "stop"
    assert len(rover.reports) == 1
    assert scan(rover, "detection", hazard_detected=True) == result
    assert len(rover.reports) == 1
    with pytest.raises(ValueError):
        scan(rover, "move-after-detection")
    rover.command("ack", "acknowledge_report", report_id="report-1")
    assert rover.state == "idle"


def test_directed_retask_requires_correct_arrival_and_inspection():
    rover = RoverController()
    rover.command("patrol", "patrol", waypoints=["a"])
    rover.command("direct", "investigate", target="b")
    with pytest.raises(ValueError):
        rover.command("early", "complete_inspection", evidence_ref="fixture")
    with pytest.raises(ValueError):
        rover.command("wrong", "arrive", target="a")
    scan(rover)
    rover.command("arrival", "arrive", target="b")
    result = rover.command("inspect", "complete_inspection", evidence_ref="fixture")
    assert result["reports"][-1]["target"] == "b"


def test_obstacle_and_timeout_stop_movement():
    rover = RoverController()
    rover.command("patrol", "patrol", waypoints=["a"])
    scan(rover, obstacle_cm=0)
    assert rover.state == "blocked"
    assert rover.io.records[-1]["reason"] == "obstacle"
    rover.command("direct", "investigate", target="b")
    rover.command("tick", "tick", elapsed_s=30)
    assert rover.state == "stopped"
    with pytest.raises(ValueError):
        rover.command("resume-without-reset", "patrol", waypoints=["a"])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "25", None])
def test_invalid_sensors_cannot_issue_movement(value):
    rover = RoverController()
    rover.command("patrol", "patrol", waypoints=["a"])
    with pytest.raises(ValueError):
        scan(rover, obstacle_cm=value)
    assert not any(r["action"] == "move_toward" for r in rover.io.records)
    assert rover.state == "stopped"


def test_invalid_sensor_after_motion_stops_before_rejection():
    rover = RoverController()
    rover.command("patrol", "patrol", waypoints=["a"])
    scan(rover)
    with pytest.raises(ValueError):
        scan(rover, "bad-sensor", obstacle_cm=None)
    assert rover.io.records[-1]["action"] == "stop"
    assert rover.state == "stopped"


def test_conflicting_command_and_full_cache_cannot_repeat_motion():
    rover = RoverController()
    rover.command("same", "patrol", waypoints=["a"])
    with pytest.raises(ValueError):
        rover.command("same", "patrol", waypoints=["b"])
    rover.MAX_COMMANDS = 1
    with pytest.raises(ValueError):
        scan(rover)
    assert rover.state == "stopped"
    rover.command("stop", "stop")
    assert rover.state == "stopped"


@pytest.mark.parametrize("failure", [RuntimeError, ValueError])
def test_io_exception_stops_and_latches_fault(failure):
    class FailedIO(SimulatedIO):
        def perform(self, action, **details):
            if action == "move_toward":
                raise failure("Synthetic adapter error")
            super().perform(action, **details)

    rover = RoverController(io=FailedIO())
    rover.command("patrol", "patrol", waypoints=["a"])
    with pytest.raises(RuntimeError):
        scan(rover)
    assert rover.state == "stopped"
    assert rover.io.records[-1]["action"] == "stop"


def test_retried_stop_stops_after_reset_and_new_motion():
    rover = RoverController()
    rover.command("stop", "stop")
    rover.command("reset", "reset")
    rover.command("patrol", "patrol", waypoints=["a"])
    scan(rover)
    assert rover.state == "patrolling"
    assert rover.command("stop", "stop")["state"] == rover.state == "stopped"


def test_full_cache_stops_even_if_watchdog_tick_cannot_be_recorded():
    rover = RoverController()
    rover.command("patrol", "patrol", waypoints=["a"])
    scan(rover)
    rover.MAX_COMMANDS = 2
    with pytest.raises(ValueError):
        rover.command("tick", "tick", elapsed_s=30)
    assert rover.state == "stopped"
    assert rover.io.records[-1]["action"] == "stop"
