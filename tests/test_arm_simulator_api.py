"""Offline arm HTTP validation and independence from fleet/hardware runtime."""

import builtins
from fastapi.testclient import TestClient
import pytest

from relay_gateway import api
from relay_gateway.arm_simulator import ArmSimulator
from relay_gateway.simulator import Simulator


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "_arm_simulator", ArmSimulator())
    monkeypatch.setattr(api, "_simulator", Simulator())
    original = builtins.__import__
    def no_hardware(name, *args, **kwargs):
        assert not name.startswith(("bleak", "robotcode.arm.motion_live", "serial", "gpiozero"))
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_hardware)
    with TestClient(api.app) as instance:
        yield instance


def post(client, action, **fields):
    before = client.get("/api/simulator/arm").json()
    post.sequence += 1
    return client.post("/api/simulator/arm/actions", json={"run_id": before["run_id"],
                       "action_id": f"http-{post.sequence}", "action": action, **fields})


post.sequence = 0


def test_arm_preset_is_independent_and_never_loads_hardware(client):
    fleet = client.get("/api/simulator").json()
    assert post(client, "start").status_code == 200
    result = post(client, "step", dt_s=1, steps=20).json()
    assert result["status"] == "completed" and result["payload"]["state"] == "placed"
    assert result["physical_connected"] is False and result["physical_result"] is None
    assert result["commands_dispatched"] == result["network_requests"] == 0
    assert client.get("/api/simulator").json() == fleet


@pytest.mark.parametrize("fields", [{"live": True}, {"joints_deg": [90] * 5},
                                    {"joints_deg": [190] * 6}, {"steps": 21},
                                    {"repeats": True}, {"fault": "motor"}])
def test_invalid_http_inputs_are_rejected_before_mutation(client, fields):
    before = client.get("/api/simulator/arm").json()
    assert post(client, "start", **fields).status_code == 422
    assert client.get("/api/simulator/arm").json() == before


def test_http_manual_teach_repeat_and_action_specific_rejection(client):
    assert post(client, "start", duration_s=2).status_code == 400
    assert post(client, "pose", joints_deg=[80, 60, 100, 100, 80, 20], duration_s=1).status_code == 200
    assert post(client, "step", dt_s=1).json()["status"] == "completed"
    assert post(client, "capture", name="pose-a", duration_s=1).status_code == 200
    assert post(client, "replay", repeats=2).status_code == 200
    assert post(client, "step", dt_s=1, steps=2).json()["status"] == "completed"


def test_http_grip_loss_requires_explicit_recovery(client):
    post(client, "start")
    assert post(client, "inject_fault", fault="grip_loss").json()["status"] == "faulted"
    assert post(client, "step").status_code == 409
    assert post(client, "resume").status_code == 409
    assert post(client, "clear_fault").json()["status"] == "paused"
