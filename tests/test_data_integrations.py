"""Contract tests exercise provider-shaped mocks and never contact an account."""

from copy import deepcopy
import json
import socket
import sys
from types import SimpleNamespace

import pytest

from relay_gateway.integrations.data import (
    INSERT_TELEMETRY, SELECT_REFERENCES, SELECT_TELEMETRY, SELECT_TELEMETRY_IDENTITIES, MongoMissionStore,
    MockMongoClient, MockSnowflakeClient, MockTigerClient, SnowflakeReferenceStore,
    TigerTelemetryStore, _Response,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Tests must not open a socket")
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def event(event_id="event-1", **changes):
    return {"mission_id": "demo-mission", "event_id": event_id, "robot_id": "robot-a",
            "observed_at": "2026-09-26T16:00:00Z", "kind": "water", "value_milli": 850,
            "simulated": True, **changes}


def test_present_credentials_do_not_enable_network(monkeypatch):
    for name in ("MONGODB_URI", "POLLARD_MONGODB_URI", "TIGER_DATABASE_URL", "SNOWFLAKE_TOKEN"):
        monkeypatch.setenv(name, "secret-invalid-live-configuration")
    mongo = MongoMissionStore.from_environment()
    assert mongo.upsert_mission({"mission_id": "m"})["mode"] == "mock"
    tiger = TigerTelemetryStore.from_environment()
    assert tiger.insert_telemetry([event()])["mode"] == "mock"
    snow = SnowflakeReferenceStore.from_environment()
    result = snow.retrieve("standing_water")
    assert result["mode"] == "mock" and result["simulated"] is True
    assert result["status"] == "completed"
    assert result["actual_billed_usd"] == "0.000000"


def test_mongo_atomic_snapshot_idempotency_and_readback():
    client = MockMongoClient()
    store = MongoMissionStore(client=client)
    mission = {"mission_id": "mission-a", "simulated": True, "review_status": "pending"}
    first = store.upsert_mission(mission)
    repeat = store.upsert_mission(mission)
    assert first["inserted"] is True
    assert repeat["inserted"] is False and repeat["modified_count"] == 0
    mission["review_status"] = "reviewed"
    assert store.upsert_mission(mission)["modified_count"] == 1
    restored = MongoMissionStore(client=client).get_mission("mission-a")
    assert restored["mission"] == mission
    assert len(client.documents) == 1
    operation, query, update, upsert = client.requests[0]
    assert operation == "update_one" and query == {"_id": "mission-a"} and upsert is True
    assert set(update) == {"$set"}
    assert store.get_mission("absent")["mission"] is None


def test_mongo_live_connection_forces_verified_tls_bounded_no_retry(monkeypatch):
    received = {}
    client = MockMongoClient()
    def factory(uri, **kwargs):
        received.update(kwargs)
        return client
    monkeypatch.setitem(sys.modules, "pymongo", SimpleNamespace(MongoClient=factory))
    store = MongoMissionStore("mongodb+srv://user:password@approved.example/", live=True)
    assert not received  # Client construction itself is lazy.
    assert store.upsert_mission({"mission_id": "m", "simulated": True})["status"] == "completed"
    assert received["tls"] is True
    assert received["tlsAllowInvalidCertificates"] is False
    assert received["tlsAllowInvalidHostnames"] is False
    assert received["timeoutMS"] == 5000
    assert received["retryReads"] is False and received["retryWrites"] is False
    assert received["w"] == "majority"


@pytest.mark.parametrize("option", ["tls=false", "tlsInsecure=true", "tlsAllowInvalidCertificates=true",
                                  "tlsAllowInvalidHostnames=true", "tlsInsecure=false&tlsInsecure=true"])
def test_mongo_rejects_insecure_tls(option):
    with pytest.raises(ValueError, match="TLS"):
        MongoMissionStore(f"mongodb://host/?{option}", live=True)


def test_mongo_errors_do_not_expose_uri_or_native_exception():
    class Broken(MockMongoClient):
        def update_one(self, *args, **kwargs):
            raise RuntimeError("credential=super-secret")
    result = MongoMissionStore("mongodb://host/", live=True, client=Broken()).upsert_mission({"mission_id": "m"})
    assert result["status"] == "unknown"
    assert result["estimated_usd"] is None
    assert "super-secret" not in json.dumps(result)


def test_tiger_batch_idempotency_range_boundaries_and_parameter_binding():
    client = MockTigerClient()
    store = TigerTelemetryStore(client=client)
    first, later = event(), event("event-2", observed_at="2026-09-26T16:00:10Z")
    assert store.insert_telemetry([first, later])["inserted"] == 2
    replay = store.insert_telemetry([first, later])
    assert replay["inserted"] == 0 and replay["evidence"]["duplicate_events"] == 2
    found = store.query_range("demo-mission", "2026-09-26T12:00:00-04:00", "2026-09-26T16:00:10Z")
    assert [row["event_id"] for row in found["rows"]] == ["event-1"]
    assert found["rows"][0]["observed_at"] == "2026-09-26T16:00:00Z"
    injection = "x'; DROP TABLE relay_telemetry; --"
    assert store.query_range(injection, "2026-09-26T16:00:00Z", "2026-09-26T17:00:00Z")["rows"] == []
    assert client.requests[0][0] == INSERT_TELEMETRY
    assert client.requests[-1][0] == SELECT_TELEMETRY
    assert injection not in client.requests[-1][0] and client.requests[-1][1][0] == injection
    options = client.connections[0]
    assert options["sslmode"] == "verify-full"
    assert options["sslrootcert"] == "system"
    assert options["connect_timeout"] == 5
    assert "statement_timeout=5000" in options["options"]


@pytest.mark.parametrize("bad", [
    event(observed_at="2026-09-26T16:00:00"), event(simulated="false"),
    event(latitude=float("nan")), event(longitude=200), event(value_milli=True),
])
def test_tiger_invalid_events_are_rejected_before_connect(bad):
    client = MockTigerClient()
    with pytest.raises(ValueError):
        TigerTelemetryStore(client=client).insert_telemetry([bad])
    assert client.connections == []


def test_tiger_rejects_oversize_or_conflicting_batch():
    store = TigerTelemetryStore()
    with pytest.raises(ValueError):
        store.insert_telemetry([event(str(i)) for i in range(101)])
    with pytest.raises(ValueError, match="Conflicting"):
        store.insert_telemetry([event(), event(value_milli=5)])
    with pytest.raises(ValueError):
        store.query_range("m", "2026-09-26T16:00:00Z", "2026-09-26T17:00:00Z", limit=101)


def test_tiger_connection_failure_is_unknown_without_secret():
    class Broken(MockTigerClient):
        def connect(self, *args, **kwargs):
            raise RuntimeError("postgresql://user:password@host/db")
    result = TigerTelemetryStore("postgresql://host/db", live=True, client=Broken()).insert_telemetry([event()])
    assert result["status"] == "unknown"
    assert "password" not in json.dumps(result)


@pytest.mark.parametrize("changes", [
    {"value_milli": 900}, {"observed_at": "2026-09-26T16:01:00Z"},
    {"robot_id": "different-robot"}, {"simulated": False}, {"latitude": 25.5},
])
def test_tiger_changed_persisted_payload_fails_and_original_survives(changes):
    client = MockTigerClient()
    store = TigerTelemetryStore(client=client)
    original = event(value_milli=100)
    assert store.insert_telemetry([original])["inserted"] == 1
    before = deepcopy(client.rows)
    result = store.insert_telemetry([{**original, **changes}])
    assert result["status"] == "failed"
    assert result["error"] == "telemetry_identity_conflict"
    assert result["inserted"] == 0
    assert result["evidence"]["conflicting_events"] == [{"mission_id": "demo-mission", "event_id": "event-1"}]
    assert result["evidence"]["batch_rolled_back"] is True
    assert client.rows == before
    restored = store.query_range("demo-mission", "2026-09-26T16:00:00Z", "2026-09-26T17:00:00Z")
    assert restored["rows"][0]["value_milli"] == 100


def test_tiger_conflict_rolls_back_other_new_rows_and_identical_replay_still_succeeds():
    client = MockTigerClient()
    store = TigerTelemetryStore(client=client)
    original = event(value_milli=100)
    store.insert_telemetry([original])
    before = deepcopy(client.rows)
    result = store.insert_telemetry([event("new-event"), event(value_milli=900)])
    assert result["status"] == "failed"
    assert client.rows == before
    assert store.insert_telemetry([original])["inserted"] == 0
    assert store.insert_telemetry([event("new-event")])["inserted"] == 1
    identity_queries = [request for request in client.requests if request[0] == SELECT_TELEMETRY_IDENTITIES]
    assert identity_queries
    assert "%s::text[]" in identity_queries[0][0]
    assert identity_queries[0][1] == (["demo-mission"], ["event-1"])


def test_tiger_event_identity_is_scoped_to_mission():
    store = TigerTelemetryStore()
    assert store.insert_telemetry([event()])["inserted"] == 1
    other_mission = event(mission_id="other-mission", value_milli=100)
    assert store.insert_telemetry([other_mission])["inserted"] == 1


def test_snowflake_sql_api_body_headers_bindings_and_determinism():
    client = MockSnowflakeClient()
    store = SnowflakeReferenceStore(client=client)
    first = store.retrieve("standing_water", limit=1)
    assert first == store.retrieve("standing_water", limit=1)
    assert len(first["references"]) == 1
    assert first["references"][0]["simulated"] is True
    request = client.requests[0]
    assert request["url"].startswith("https://mock-account.snowflakecomputing.com/api/v2/statements?requestId=")
    assert request["json"]["statement"] == SELECT_REFERENCES
    assert request["json"]["timeout"] == 5 and request["timeout"] == 10
    assert request["json"]["bindings"] == {"1": {"type": "TEXT", "value": "standing_water"},
                                            "2": {"type": "FIXED", "value": "1"}}
    assert request["headers"]["X-Snowflake-Authorization-Token-Type"] == "PROGRAMMATIC_ACCESS_TOKEN"
    injection = "water' OR 1=1 --"
    assert store.retrieve(injection)["references"] == []
    assert injection not in client.requests[-1]["json"]["statement"]
    assert client.requests[-1]["json"]["bindings"]["1"]["value"] == injection


def test_snowflake_live_config_is_explicit_and_result_never_contains_token():
    client = MockSnowflakeClient()
    store = SnowflakeReferenceStore("org-account", "secret-token", "RELAY", "PUBLIC", "DEMO_WH",
                                   "RELAY_READER", live=True, client=client)
    result = store.retrieve("standing_water")
    assert result["mode"] == "live" and result["estimated_usd"] is None
    assert "secret-token" not in json.dumps(result)
    assert client.requests[0]["json"]["warehouse"] == "DEMO_WH"
    assert client.requests[0]["json"]["role"] == "RELAY_READER"
    with pytest.raises(ValueError):
        SnowflakeReferenceStore("https://attacker.example", "secret", "D", "S", "W", live=True)
    with pytest.raises(ValueError):
        SnowflakeReferenceStore("org-account", "secret", "D", "S", live=True)


@pytest.mark.parametrize("status,payload", [(202, {"statementHandle": "pending-handle"}),
                                           (429, {"message": "secret-token"}),
                                           (500, {"message": "secret-token"})])
def test_snowflake_pending_or_http_failure_is_not_retried(status, payload):
    class ResponseClient(MockSnowflakeClient):
        calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            return _Response(status, payload)
    client = ResponseClient()
    result = SnowflakeReferenceStore(client=client).retrieve("standing_water")
    assert client.calls == 1 and result["status"] == "unknown"
    assert "secret-token" not in json.dumps(result)
    if status == 202:
        assert result["evidence"]["statement_handle"] == "pending-handle"


def test_snowflake_does_not_report_partial_partition_as_complete():
    class Partial(MockSnowflakeClient):
        def post(self, *args, **kwargs):
            response = super().post(*args, **kwargs)
            response.body["resultSetMetaData"]["numRows"] = 10
            return response
    assert SnowflakeReferenceStore(client=Partial()).retrieve("standing_water")["status"] == "unknown"


def test_mock_mode_rejects_unmarked_injected_network_client():
    for constructor in (MongoMissionStore, TigerTelemetryStore, SnowflakeReferenceStore):
        with pytest.raises(ValueError, match="relay_mock"):
            constructor(client=object())
