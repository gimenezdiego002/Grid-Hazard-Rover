"""HTTP bounds and mock-only semantics for the geometric simulator."""

from fastapi.testclient import TestClient
import pytest

from relay_gateway import api
from relay_gateway.simulator import Simulator


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "_simulator", Simulator())
    monkeypatch.setenv("RELAY_ALLOW_LIVE_GEMINI", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key-must-never-be-used")
    with TestClient(api.app) as instance:
        yield instance


def post(client, action, **extra):
    state = client.get("/api/simulator").json()
    return client.post("/api/simulator/actions", json={"run_id": state["run_id"],
                       "action_id": f"request-{action}-{state['elapsed_s']}", "action": action, **extra})


def test_start_step_pause_stop_http_contract_never_enables_hardware_or_providers(client):
    state = client.get("/api/simulator").json()
    assert state["status"] == "idle" and state["simulated"] is True
    assert post(client, "start").status_code == 200
    step = post(client, "step", dt_s=0.5, steps=10)
    assert step.status_code == 200 and step.json()["elapsed_s"] == 5
    assert step.json()["robots"][0]["distance_m"] > 0
    assert post(client, "pause").json()["status"] == "paused"
    assert post(client, "step").json()["status"] == "paused"
    assert post(client, "stop").json()["status"] == "stopped"
    final = client.get("/api/simulator").json()
    assert final["network_requests"] == final["actual_model_calls"] == final["actual_api_cost_usd"] == 0
    assert final["actuation_enabled"] is False


@pytest.mark.parametrize("extra", [{"live": True}, {"steps": 21}, {"dt_s": 100},
                                   {"steps": True}, {"action": "actuate"},
                                   {"target": {"x": 10, "y": 20}}, {"robot_id": "real-arm"}])
def test_http_rejects_invalid_fields_and_does_not_mutate(client, extra):
    before = client.get("/api/simulator").json()
    response = client.post("/api/simulator/actions", json={"run_id": before["run_id"],
                           "action_id": "bad", "action": "start", **extra})
    assert response.status_code == 422
    assert client.get("/api/simulator").json() == before


def test_http_rejects_action_specific_extras_and_blocked_target(client):
    assert post(client, "start", steps=2).status_code == 400
    assert post(client, "direct", target={"x": 9, "y": 8}).status_code == 400
    response = post(client, "direct", target={"x": 5, "y": 4})
    assert response.status_code == 200
    assert response.json()["mode"] == "directed"


def test_stale_run_and_reused_action_are_conflicts(client):
    old = client.get("/api/simulator").json()["run_id"]
    assert post(client, "reset").status_code == 200
    stale = client.post("/api/simulator/actions", json={"run_id": old, "action_id": "old", "action": "start"})
    assert stale.status_code == 409
    current = client.get("/api/simulator").json()["run_id"]
    body = {"run_id": current, "action_id": "same", "action": "start"}
    assert client.post("/api/simulator/actions", json=body).status_code == 200
    assert client.post("/api/simulator/actions", json=body).json()["replayed"] is True
    assert client.post("/api/simulator/actions", json={**body, "action": "pause"}).status_code == 409


def test_simulator_page_has_clear_missing_asset_error(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    assert client.get("/simulator").status_code == 404
