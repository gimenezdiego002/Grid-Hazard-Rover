import socket
import pytest

from robotcode.demo import DemoMission, run_demo
from robotcode.runtime import SimulatedIO
from robotcode.hexapod import HexapodController


@pytest.mark.parametrize("workflow", ["basic", "directed", "inspection-only", "report-only"])
def test_workflows_are_finite_offline_and_payload_is_conserved(workflow, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Robot simulation attempted a network connection")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setenv("RELAY_ALLOW_LIVE", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-unused-key")
    result = run_demo(workflow)
    assert result["simulated"] is True
    assert result["model_calls"] == result["api_cloud_cost_usd"] == 0
    assert result["hardware_connected"] is False
    assert 1 <= len(result["events"]) < 60
    assert result["needs_review"] is False
    rover, hexapod, arm = result["robots"]
    assert rover["reports"]
    assert arm["inventory"] == ["inspection-kit"]
    assert hexapod["payload_id"] is None
    transfers = [event for event in result["events"] if event["action"] == "prepare_transfer"]
    assert len(transfers) == (4 if workflow in {"basic", "directed"} else 0)


def test_failed_station_handshake_stops_fleet_and_requires_review():
    mission = DemoMission()
    mission.travel("wrong-station")
    with pytest.raises(ValueError):
        mission.transfer("load")
    assert mission.needs_review
    assert all(robot.state == "stopped" for robot in (mission.arm, mission.rover, mission.hexapod))
    assert mission.arm.snapshot()["inventory"] == ["inspection-kit"]
    with pytest.raises(ValueError):
        mission.send(mission.hexapod, "reset")


def test_watchdog_stop_receipt_aborts_entire_mission():
    mission = DemoMission()
    mission.send(mission.hexapod, "dispatch", target="suspect-area")
    with pytest.raises(RuntimeError, match="requires review"):
        mission.send(mission.hexapod, "tick", elapsed_s=120)
    assert mission.needs_review
    assert all(robot.state == "stopped" for robot in (mission.arm, mission.rover, mission.hexapod))


def test_partial_handoff_failure_never_releases_carrier():
    class ConfirmationFailure(SimulatedIO):
        def perform(self, action, **details):
            if action == "transfer_acknowledged":
                raise ValueError("Synthetic failure after arm confirmation")
            super().perform(action, **details)

    mission = DemoMission()
    mission.hexapod = HexapodController(io=ConfirmationFailure())
    mission.travel("station-a")
    with pytest.raises(RuntimeError):
        mission.transfer("load")
    assert mission.needs_review
    assert mission.hexapod.transfer_reconciliation_required
    assert mission.hexapod.state == "stopped"
    assert not any(record["action"] == "undock" for record in mission.hexapod.io.records)
    assert mission.arm.last_transfer["outcome"] == "confirmed"
    assert mission.hexapod.transfer["transfer_id"] == mission.arm.last_transfer["transfer_id"]
