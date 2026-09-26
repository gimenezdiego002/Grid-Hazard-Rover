"""HTTP contract checks for the offline mission controls."""

from fastapi.testclient import TestClient
import pytest

from relay_gateway import api
from relay_gateway.missions import MissionEngine
from relay_gateway.models import default_scenario


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_mission_engine", MissionEngine())
    monkeypatch.setenv("RELAY_STORE_PATH", str(tmp_path / "mock-pollard.sqlite"))
    monkeypatch.setenv("RELAY_ALLOW_LIVE_GEMINI", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-credential-must-never-be-used")
    with TestClient(api.app) as instance:
        yield instance


def plan(client, **extra):
    response = client.post("/api/missions", json={"mission_id": "http-mission",
                           "action_id": "create-1", **extra})
    assert response.status_code == 200
    return response.json()


def act(client, action, **payload):
    return client.post("/api/missions/http-mission/actions", json={
        "action_id": action + "-" + payload.get("task_id", "1"),
        "action": action, "payload": payload})


def test_directed_workflow_requires_explicit_simulated_review(client):
    mission = plan(client, mode="directed", target_id="north-door", scout_id="intellio-rover")
    assert mission["target_id"] == "north-door"
    assert not mission["actuation_enabled"]
    assert act(client, "start").status_code == 200
    assert act(client, "complete_task", task_id="monitor", outcome="completed").status_code == 200
    observed = act(client, "complete_task", task_id="scout", outcome="suspected_hazard").json()
    assert observed["status"] == "needs_review"
    assert "complete_task" not in observed["allowed_actions"]
    assert act(client, "complete_task", task_id="announce", outcome="completed").status_code == 409
    assert act(client, "simulate_review", decision="acknowledge").json()["status"] == "running"
    completed = act(client, "complete_task", task_id="announce", outcome="completed").json()
    assert completed["status"] == "completed"
    assert completed["environment_safety"] == "not_established"
    assert completed["review"]["human_review_performed"] is False
    assert completed["network_requests"] == 0


def test_budget_refusal_remains_review_even_after_acknowledgement(client):
    plan(client)
    act(client, "start")
    act(client, "complete_task", task_id="monitor", outcome="completed")
    scenario = default_scenario().model_dump(mode="json")
    scenario["budget"]["max_requests"] = 0
    response = client.post("/api/run", json={"scenario": scenario, "strategy": "economy"})
    assert response.status_code == 200
    run = response.json()
    assert run["provider_mode"] == "mock"
    assert run["accounting"]["new_requests"] == 0
    assert any(event["reason"] == "budget_refused" for event in run["events"])
    denied = act(client, "complete_task", task_id="scout", outcome="budget_refused").json()
    assert denied["budget_refused"] is True
    reviewed = act(client, "simulate_review", decision="acknowledge").json()
    assert reviewed["status"] == "needs_review"
    assert "complete_task" not in reviewed["allowed_actions"]


def test_duplicate_action_is_idempotent_and_physical_inputs_are_rejected(client):
    mission = plan(client)
    assert plan(client) == mission
    first = act(client, "start").json()
    assert act(client, "start").json() == first
    before = client.get("/api/missions/http-mission").json()
    invalid = client.post("/api/missions/http-mission/actions", json={
        "action_id": "move-1", "action": "move", "payload": {}})
    assert invalid.status_code == 422
    assert client.get("/api/missions/http-mission").json() == before
    assert client.post("/api/missions", json={"mission_id": "real", "action_id": "create", "live": True}).status_code == 422


def test_inventory_missing_mission_and_cancel_contracts(client):
    inventory = client.get("/api/missions/inventory").json()
    assert inventory["physical_connections_verified"] is False
    assert all(row["simulated"] and not row["physical_connected"] for row in inventory["inventory"])
    assert client.get("/api/missions/missing").status_code == 404
    plan(client)
    act(client, "start")
    assert act(client, "pause").json()["status"] == "paused"
    assert act(client, "resume").json()["status"] == "running"
    cancelled = act(client, "cancel").json()
    assert cancelled["status"] == "cancelled" and cancelled["allowed_actions"] == []
    assert act(client, "complete_task", task_id="monitor", outcome="completed").status_code == 409
