"""Finite offline/loopback tests; no cloud/provider calls or physical commands."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import threading
import time

import httpx
import pytest
import uvicorn

from relay_gateway import fleet_consumer as module
from relay_gateway.fleet_consumer import FleetConsumer, fixture_page
from relay_gateway.gateway import run_scenario
from relay_gateway.models import Scenario


def scenario():
    return json.loads((Path(__file__).resolve().parents[1] / "scenarios" / "leak.json").read_text())


def page():
    return fixture_page(scenario())


def test_offline_fixture_13_envelopes_12_water_and_opaque_rover(tmp_path):
    consumer = FleetConsumer(workspace_root=tmp_path)
    result = consumer.consume_page(page())
    assert result["status"] == "completed" and result["events_accepted"] == 13
    assert len(result["observations"]) == 12
    assert len(result["opaque_evidence"]) == 1
    assert result["opaque_evidence"][0]["evidence_ref"] == "synthetic-water-040"
    assert result["opaque_evidence"][0]["source_id"] == "intellio-rover"
    assert len(result["scenarios"]) == 1
    parsed = Scenario.model_validate(result["scenarios"][0])
    assert all(observation.kind == "water" and observation.simulated for observation in parsed.observations)
    assert "ground_truth_hazard" not in json.dumps(result)
    assert result["model_calls"] == result["provider_writes"] == 0
    run = run_scenario(parsed, store_path=tmp_path / "mock-proof.sqlite")
    assert run["provider_mode"] == "mock" and run["findings"][0]["status"] == "suspected_hazard"
    assert consumer.path == tmp_path / ".state" / "fleet-consumer.sqlite"


def test_durable_cursor_and_replayed_page_do_not_reemit_observations(tmp_path):
    first = FleetConsumer(workspace_root=tmp_path)
    first.consume_page(page())
    second = FleetConsumer(workspace_root=tmp_path)
    assert second.cursor()["after_sequence"] == 13
    repeated = second.consume_page(page())
    assert repeated["duplicate_events"] == 13
    assert repeated["events_accepted"] == 0 and repeated["observations"] == []
    assert second.cursor()["after_sequence"] == 13


def test_two_pages_advance_once_and_keep_cross_page_evidence(tmp_path):
    consumer = FleetConsumer(workspace_root=tmp_path)
    full = page()
    first = {**full, "events": full["events"][:5], "next_after_sequence": 5}
    later = {**full, "events": full["events"][5:]}
    first_result = consumer.consume_page(first)
    assert first_result["events_accepted"] == 5 and first_result["cursor"]["after_sequence"] == 5
    second_result = FleetConsumer(workspace_root=tmp_path).consume_page(later)
    assert second_result["events_accepted"] == 8
    assert len(first_result["observations"]) + len(second_result["observations"]) == 12
    assert len(second_result["opaque_evidence"]) == 1
    with sqlite3.connect(consumer.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM envelopes").fetchone()[0] == 13


def test_restart_latches_review_across_instances_until_exact_ack(tmp_path):
    consumer = FleetConsumer(workspace_root=tmp_path)
    consumer.consume_page(page())
    restarted = page()
    restarted["stream_id"] = "new-gateway-stream"
    blocked = consumer.consume_page(restarted)
    assert blocked["status"] == "needs_review" and blocked["reason"] == "stream_reset"
    assert blocked["cursor"]["after_sequence"] == 13
    consumer = FleetConsumer(workspace_root=tmp_path)
    assert consumer.consume_page(restarted)["status"] == "needs_review"
    with pytest.raises(ValueError):
        consumer.acknowledge_loss("wrong-stream", 0, "Reviewed gateway restart")
    ack = consumer.acknowledge_loss("new-gateway-stream", 0, "Reviewed restart; accept new stream from its beginning")
    assert ack["status"] == "acknowledged_loss"
    result = consumer.consume_page(restarted)
    assert result["duplicate_events"] == 13 and result["events_accepted"] == 0
    assert result["cursor"]["stream_id"] == "new-gateway-stream"
    with sqlite3.connect(consumer.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM envelopes").fetchone()[0] == 13
        assert connection.execute("SELECT COUNT(*) FROM loss_acknowledgements").fetchone()[0] == 1


def test_retention_gap_requires_ack_and_fresh_page_without_silent_skip(tmp_path):
    consumer = FleetConsumer(workspace_root=tmp_path)
    expired = page()
    expired["events"] = expired["events"][5:]
    expired["retained_from_sequence"] = 6
    expired["gap_detected"] = True
    result = consumer.consume_page(expired)
    assert result["reason"] == "retention_gap" and consumer.cursor()["after_sequence"] == 0
    assert consumer.cursor()["pending_after_sequence"] == 5
    consumer.acknowledge_loss(expired["stream_id"], 5, "Five expired envelopes are unavailable; retain this acknowledged loss")
    refreshed = deepcopy(expired)
    refreshed["gap_detected"] = False
    accepted = consumer.consume_page(refreshed)
    assert accepted["events_accepted"] == 8 and accepted["cursor"]["after_sequence"] == 13


def test_sequence_hole_preserves_prefix_latches_review_and_resumes_after_ack(tmp_path):
    consumer = FleetConsumer(workspace_root=tmp_path)
    missing = page()
    del missing["events"][1]
    result = consumer.consume_page(missing)
    assert result["reason"] == "sequence_gap"
    assert result["status"] == "needs_review"
    assert result["events_accepted"] == result["prefix_sequences_committed"] == 1
    assert result["cursor"]["after_sequence"] == 1
    assert result["cursor"]["pending_after_sequence"] == 2
    assert result["envelopes"][0]["sequence"] == 1
    assert len(result["observations"]) == 1
    consumer = FleetConsumer(workspace_root=tmp_path)
    blocked = consumer.consume_page(missing)
    assert blocked["events_accepted"] == 0 and blocked["cursor"]["after_sequence"] == 1
    prefix = consumer.export_stored(missing["stream_id"])
    assert prefix["exported_events"] == 1 and prefix["cursor"]["review_required"]
    with sqlite3.connect(consumer.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM envelopes").fetchone()[0] == 1
    consumer.acknowledge_loss(missing["stream_id"], 2, "Sequence two is absent; accept only that missing record")
    resumed = consumer.consume_page({**missing, "events": missing["events"][1:]})
    assert resumed["events_accepted"] == 11 and resumed["cursor"]["after_sequence"] == 13
    exported = consumer.export_stored(missing["stream_id"])
    assert [item["sequence"] for item in exported["envelopes"]] == [1, *range(3, 14)]
    assert len(exported["observations"]) == 11 and len(exported["opaque_evidence"]) == 1
    with sqlite3.connect(consumer.path) as connection:
        assert connection.execute("SELECT old_after, new_after FROM loss_acknowledgements").fetchone() == (1, 2)


def test_restart_export_recovers_committed_output_with_bounded_read_only_pages(tmp_path):
    original = page()
    # Simulate a process that commits but loses its returned payload before handoff.
    FleetConsumer(workspace_root=tmp_path).consume_page(original)
    restarted = FleetConsumer(workspace_root=tmp_path)
    before_cursor, before_bytes = restarted.cursor(), restarted.path.read_bytes()
    first = restarted.export_stored(original["stream_id"], limit=5)
    second = restarted.export_stored(original["stream_id"], after_sequence=first["next_after_sequence"], limit=100)
    assert first["replay"] is True and first["export_only"] is True
    assert first["exported_events"] == 5 and second["exported_events"] == 8
    assert first["envelopes"] + second["envelopes"] == original["events"]
    assert len(first["observations"]) + len(second["observations"]) == 12
    assert len(first["opaque_evidence"]) + len(second["opaque_evidence"]) == 1
    for exported in (first, second):
        assert exported["model_calls"] == exported["provider_writes"] == exported["network_requests"] == 0
        assert exported["cursor"] == before_cursor
        assert "ground_truth_hazard" not in json.dumps(exported)
    assert restarted.cursor() == before_cursor and restarted.path.read_bytes() == before_bytes
    assert restarted.consume_page(original)["events_accepted"] == 0


def test_export_preserves_duplicate_sequence_evidence_without_duplicate_observations(tmp_path):
    consumer = FleetConsumer(workspace_root=tmp_path)
    full = page()
    consumer.consume_page(full)
    duplicate = {**full["events"][0], "sequence": 14}
    consumer.consume_page({**full, "latest_sequence": 14, "next_after_sequence": 14, "events": [duplicate]})
    exported = consumer.export_stored(full["stream_id"])
    assert exported["exported_events"] == 14 and exported["exported_unique_events"] == 13
    assert len(exported["observations"]) == 12
    assert exported["envelopes"][-1] == duplicate


def test_export_refuses_corrupt_saved_evidence_without_cursor_changes(tmp_path):
    consumer = FleetConsumer(workspace_root=tmp_path)
    full = page()
    consumer.consume_page(full)
    before = consumer.cursor()
    with sqlite3.connect(consumer.path) as connection:
        connection.execute("UPDATE envelopes SET envelope_json='{}' WHERE event_id=?", (full["events"][0]["event"]["event_id"],))
    exported = consumer.export_stored(full["stream_id"])
    assert exported["reason"] == "stored_evidence_invalid" and exported["status"] == "needs_review"
    assert "envelopes" not in exported and consumer.cursor() == before


@pytest.mark.parametrize("after,limit", [(-1, 100), (0, 101), (0, 0), (0, True)])
def test_export_bounds_are_explicit(tmp_path, after, limit):
    with pytest.raises(ValueError):
        FleetConsumer(workspace_root=tmp_path).export_stored(page()["stream_id"], after_sequence=after, limit=limit)


def test_payload_conflict_blocks_cursor_and_entire_page(tmp_path):
    consumer = FleetConsumer(workspace_root=tmp_path)
    first = page()
    initial = {**first, "events": first["events"][:1], "next_after_sequence": 1}
    assert consumer.consume_page(initial)["events_accepted"] == 1
    changed = deepcopy(first["events"][0])
    changed["sequence"] = 2
    changed["event"]["value_milli"] = 999
    changed["sha256"] = module._digest(changed["event"])
    bad_page = {**first, "events": [changed], "next_after_sequence": 2}
    result = consumer.consume_page(bad_page)
    assert result["reason"] == "event_identity_conflict"
    assert consumer.cursor()["after_sequence"] == 1
    with pytest.raises(ValueError):
        consumer.acknowledge_loss(first["stream_id"], 0, "Cannot skip an identity conflict")


@pytest.mark.parametrize("change", ["digest", "real", "oversize"])
def test_invalid_or_real_input_cannot_advance_cursor(tmp_path, change):
    value = page()
    if change == "digest":
        value["events"][0]["sha256"] = "0" * 64
    elif change == "real":
        value["events"][0]["event"]["simulated"] = False
        value["events"][0]["sha256"] = module._digest(value["events"][0]["event"])
    else:
        value["events"] *= 9
    consumer = FleetConsumer(workspace_root=tmp_path)
    result = consumer.consume_page(value)
    assert result["status"] == "needs_review"
    assert consumer.cursor()["after_sequence"] == 0


def test_empty_page_advanced_cursor_is_rejected(tmp_path):
    value = page()
    value["events"] = []
    consumer = FleetConsumer(workspace_root=tmp_path)
    assert consumer.consume_page(value)["reason"] == "sequence_gap"
    assert consumer.cursor()["after_sequence"] == 0


def test_default_cli_ignores_live_credentials_and_does_not_open_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(module, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setenv("RELAY_FLEET_MODE", "invalid-environment-should-not-affect-offline-consumer")
    monkeypatch.setenv("RELAY_FLEET_API_TOKEN", "sentinel-secret")
    def forbidden(*args, **kwargs):
        raise AssertionError("Default CLI must remain offline")
    monkeypatch.setattr(socket, "socket", forbidden)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(scenario()))
    assert module.main(["--scenario", str(fixture)]) == 0
    output = capsys.readouterr().out
    assert "sentinel-secret" not in output
    assert json.loads(output)["events_accepted"] == 13


def test_explicit_cli_export_for_url_bound_source_is_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(module, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setenv("RELAY_FLEET_API_TOKEN", "sentinel-secret")
    origin = "https://gateway.example"
    original = page()
    consumer = FleetConsumer.from_url(origin, workspace_root=tmp_path)
    consumer.consume_page(original)
    def forbidden(*args, **kwargs):
        raise AssertionError("Stored export must not open a network connection")
    monkeypatch.setattr(socket, "socket", forbidden)
    assert module.main(["--url", origin, "--export-stream", original["stream_id"], "--after-sequence", "5", "--limit", "4"]) == 0
    output = capsys.readouterr().out
    assert "sentinel-secret" not in output
    exported = json.loads(output)
    assert exported["replay"] and exported["export_only"] and exported["exported_events"] == 4
    assert [item["sequence"] for item in exported["envelopes"]] == [6, 7, 8, 9]
    assert exported["cursor"]["after_sequence"] == 13 and exported["network_requests"] == 0


@contextmanager
def server(config, monkeypatch):
    monkeypatch.setenv("RELAY_FLEET_MODE", "mock")
    from relay_gateway.fleet_gateway import create_app
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    service = uvicorn.Server(uvicorn.Config(create_app(config), log_level="critical", lifespan="off"))
    thread = threading.Thread(target=service.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not service.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        service.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def test_real_loopback_gateway_http_13_events_to_12_water_scenario(tmp_path, monkeypatch):
    monkeypatch.delenv("RELAY_FLEET_API_TOKEN", raising=False)
    monkeypatch.setenv("RELAY_FLEET_MODE", "mock")
    from relay_gateway.fleet_gateway import FleetConfig, fixture_events
    with server(FleetConfig(), monkeypatch) as url:
        with httpx.Client(base_url=url, timeout=5, trust_env=False) as client:
            for envelope in fixture_events(scenario()):
                assert client.post("/telemetry", json=envelope.model_dump(mode="json", exclude_none=True)).status_code == 202
        consumer = FleetConsumer.from_url(url, workspace_root=tmp_path)
        result = consumer.fetch_once(url)
        assert result["network_requests"] == 1 and result["events_accepted"] == 13
        assert len(result["scenarios"][0]["observations"]) == 12
        assert len(result["opaque_evidence"]) == 1
        assert consumer.fetch_once(url)["events_accepted"] == 0


def test_authentication_failure_preserves_cursor_and_redacts_token(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_FLEET_MODE", "mock")
    from relay_gateway.fleet_gateway import FleetConfig
    correct = "correct-test-fleet-token-0123456789abcdef"
    wrong = "incorrect-test-fleet-token-0123456789abcdef"
    monkeypatch.setenv("RELAY_FLEET_API_TOKEN", wrong)
    with server(FleetConfig(mode="live", api_token=correct), monkeypatch) as url:
        consumer = FleetConsumer.from_url(url, workspace_root=tmp_path)
        response = consumer.fetch_once(url)
        assert response["status"] == "failed" and response["http_status"] == 401
        assert wrong not in json.dumps(response) and correct not in json.dumps(response)
        assert consumer.cursor()["after_sequence"] == 0
        monkeypatch.setenv("RELAY_FLEET_API_TOKEN", correct)
        authorized = consumer.fetch_once(url)
        assert authorized["status"] == "completed" and authorized["events_accepted"] == 0
        assert correct not in json.dumps(authorized)


@pytest.mark.parametrize("url,allow", [("http://remote.example", True), ("https://remote.example", False)])
def test_remote_requires_explicit_https_before_fetch(tmp_path, url, allow):
    consumer = FleetConsumer.from_url(url, workspace_root=tmp_path)
    with pytest.raises(ValueError):
        consumer.fetch_once(url, allow_remote=allow)


@pytest.mark.parametrize("url", ["https://user:secret@host", "http://127.0.0.1/?token=secret", "file:///secret", "https://host/events"])
def test_url_cannot_contain_credentials_or_query(tmp_path, url):
    with pytest.raises(ValueError):
        FleetConsumer.from_url(url, workspace_root=tmp_path)
