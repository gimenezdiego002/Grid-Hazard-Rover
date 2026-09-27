import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from relay_gateway.fleet_gateway import (
    FleetConfig, MAX_ENVELOPE_BYTES, TelemetryCache, TelemetryEnvelope,
    create_app, fixture_events, send_fixture,
)


EVENT = {"schema_version": "1", "event_id": "water-040", "mission_id": "leak-demo",
         "source_id": "station-a", "station_id": "station-a", "kind": "water_reading",
         "timestamp_seconds": 40, "simulated": True, "value_milli": 850}
TOKEN = "unit-test-token-0123456789-abcdefghijk"


def local_client(config=None, cache=None):
    return TestClient(create_app(config or FleetConfig(), cache=cache), client=("127.0.0.1", 12345))


def test_telemetry_accept_duplicate_and_conflicting_identity():
    with local_client() as client:
        first = client.post("/telemetry", json=EVENT)
        duplicate = client.post("/telemetry", json=EVENT)
        conflict = client.post("/telemetry", json={**EVENT, "value_milli": 900})
        assert first.status_code == 202 and first.json()["accepted"] is True
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
        assert duplicate.json()["sequence"] == first.json()["sequence"]
        assert conflict.status_code == 409
        retained = client.get("/events").json()
        assert len(retained["events"]) == 1
        assert retained["events"][0]["event"]["value_milli"] == 850
        assert retained["durability"] == "process_memory"


def test_live_config_fails_closed_without_strong_secret():
    for token in (None, "short", "a" * 31 + "\n"):
        with pytest.raises(ValueError):
            FleetConfig(mode="live", api_token=token)
    assert TOKEN not in repr(FleetConfig(mode="live", api_token=TOKEN))


def test_live_writes_and_reads_require_bearer_token():
    with local_client(FleetConfig(mode="live", api_token=TOKEN)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").json()["auth_required"] is True
        assert client.post("/telemetry", json=EVENT).status_code == 401
        assert client.get("/events").status_code == 401
        assert client.post("/telemetry", json=EVENT, headers={"Authorization": "Bearer wrong"}).status_code == 401
        auth = {"Authorization": "Bearer " + TOKEN}
        assert client.post("/telemetry", json=EVENT, headers=auth).status_code == 202
        assert len(client.get("/events", headers=auth).json()["events"]) == 1


def test_mock_rejects_remote_and_real_measurements():
    with TestClient(create_app(FleetConfig()), client=("203.0.113.7", 1234)) as remote:
        assert remote.post("/telemetry", json=EVENT).status_code == 403
        assert remote.get("/events").status_code == 403
    with local_client() as client:
        assert client.post("/telemetry", json={**EVENT, "simulated": False}).status_code == 403
        assert client.get("/health").json()["model_calls_enabled"] is False
        assert client.get("/health").json()["actuation_enabled"] is False


@pytest.mark.parametrize("change", [{"value_milli": 1001}, {"value_milli": -1},
    {"value_milli": "850"}, {"simulated": "true"}, {"timestamp_seconds": -1},
    {"event_id": "../outside"}, {"event_id": "x" * 97},
    {"kind": "move_robot"}, {"api_key": "must-not-be-reflected"},
    {"kind": "inspection_observation", "value_milli": None}])
def test_envelope_validation_does_not_reflect_input(change):
    with local_client() as client:
        response = client.post("/telemetry", json={**EVENT, **change})
        assert response.status_code == 422
        assert "must-not-be-reflected" not in response.text
        assert client.get("/events").json()["events"] == []


def test_request_body_and_read_page_limits():
    with local_client() as client:
        oversized = client.post("/telemetry", content=b"x" * (MAX_ENVELOPE_BYTES + 1), headers={"Content-Type": "application/json"})
        assert oversized.status_code == 413
        assert client.get("/events?limit=101").status_code == 422
        assert client.get("/events?after_sequence=-1").status_code == 422


def test_ttl_capacity_and_cursor_gap_are_explicit():
    now = [0.0]
    config = FleetConfig(ttl_seconds=60, max_events=1)
    cache = TelemetryCache(config, clock=lambda: now[0])
    with local_client(config, cache) as client:
        assert client.post("/telemetry", json=EVENT).status_code == 202
        next_event = {**EVENT, "event_id": "water-050", "timestamp_seconds": 50}
        assert client.post("/telemetry", json=next_event).status_code == 503
        assert len(client.get("/events").json()["events"]) == 1
        now[0] = 61
        assert client.post("/telemetry", json=next_event).status_code == 202
        result = client.get("/events").json()
        assert result["gap_detected"] is True
        assert result["retained_from_sequence"] == 2
        assert result["next_after_sequence"] == 2
        assert client.get("/events?after_sequence=2").json()["events"] == []


def test_restart_identity_and_source_namespacing():
    first = TelemetryCache(FleetConfig())
    second = TelemetryCache(FleetConfig())
    assert first.stream_id != second.stream_id
    with local_client(cache=first) as client:
        assert client.post("/telemetry", json=EVENT).status_code == 202
        assert client.post("/telemetry", json={**EVENT, "source_id": "station-b"}).status_code == 202
        assert len(client.get("/events").json()["events"]) == 2


def test_existing_scenario_generates_station_rover_fixture_received_locally():
    path = Path(__file__).resolve().parents[1] / "scenarios" / "leak.json"
    scenario = json.loads(path.read_text())
    fixture = fixture_events(scenario)
    assert len(fixture) == 13
    assert {event.source_id for event in fixture} == {"station-a", "intellio-rover"}
    assert all(event.simulated for event in fixture)
    with local_client() as client:
        for event in fixture:
            assert client.post("/telemetry", json=event.model_dump(mode="json", exclude_none=True)).status_code == 202
        page = client.get("/events?limit=100").json()
        assert len(page["events"]) == 13
        rover = [item for item in page["events"] if item["event"]["source_id"] == "intellio-rover"]
        assert rover[0]["event"]["timestamp_seconds"] == 41
        assert rover[0]["event"]["kind"] == "inspection_observation"


@pytest.mark.parametrize("url", ["http://remote.example", "https://remote.example", "file:///tmp/data", "https://name:secret@remote.example", "http://127.0.0.1:8787/?token=secret"])
def test_fixture_sender_rejects_unsafe_targets_before_network(url):
    with pytest.raises(ValueError):
        send_fixture({}, url)
