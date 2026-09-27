"""Offline composition tests: the complete mission must not contact providers."""

from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from relay_gateway.integrations import audio_receipt, ledger
from relay_gateway.integrations.workflow import run_integration_demo
from relay_gateway.models import default_scenario


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Integrated demo attempted live I/O or spending-ledger access")
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(audio_receipt, "_post", denied)
    monkeypatch.setattr(ledger.SpendLedger, "__init__", denied)


def test_default_workflow_completes_all_six_mock_stages():
    result = run_integration_demo()
    assert result["status"] == "completed"
    assert result["mode"] == "mock" and result["simulated"] is True
    assert result["network_requests"] == 0
    assert result["production_spend_ledger_modified"] is False
    assert result["actual_paid_usd"] == "0.000000"
    assert [step["provider"] for step in result["steps"]] == [
        "snowflake", "gemini", "tiger", "mongodb", "elevenlabs", "solana"]
    assert all(step["mode"] == "mock" and step["simulated"] and not step["remote_verified"] for step in result["steps"])
    assert all(step["status"] == "completed" for step in result["steps"])
    assert result["telemetry_persistence"] == {"inserted": 3, "replay_inserted": 0, "readback_count": 3, "verified": True}
    assert result["mission_persistence"]["verified"] is True
    assert result["findings"][0]["cited_reference_ids"]
    ids = {reference["reference_id"] for reference in result["references"]}
    assert set(result["findings"][0]["cited_reference_ids"]).issubset(ids)
    assert len(result["services"]) == 9
    assert not any(service["remote_verified"] for service in result["services"])
    assert {service["provider"] for service in result["services"] if service["demo_status"] == "not_exercised"} == {"digitalocean", "godaddy", "gcp"}


def test_workflow_does_not_turn_mock_review_into_human_or_chain_claim():
    result = run_integration_demo()
    assert result["report"]["review"]["human_review_performed"] is False
    assert result["report"]["finalization"]["status"] == "simulated_finalization"
    assert result["briefing"]["audio_path"] is None and result["briefing"]["request_sent"] is False
    assert result["receipt"]["signature"] is None and result["receipt"]["chain_verified"] is False
    assert result["receipt_verification"]["valid"] is True
    assert result["tamper_verification"]["valid"] is False
    assert result["tamper_verification"]["status"] == "report_changed"
    assert result["actuation_enabled"] is False


def test_keys_live_flags_and_hostile_store_env_do_not_enable_external_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secret = "SENTINEL_SECRET_NOT_FOR_OUTPUT"
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "MONGODB_URI", "POLLARD_MONGODB_URI",
                 "TIGER_DATABASE_URL", "SNOWFLAKE_TOKEN", "ELEVENLABS_API_KEY",
                 "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "SOLANA_RPC_URL"):
        monkeypatch.setenv(name, secret)
    for name in ("RELAY_ALLOW_LIVE_GEMINI", "RELAY_ALLOW_ELEVENLABS", "RELAY_ALLOW_SOLANA_DEVNET"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("RELAY_PROVIDER", "gemini")
    monkeypatch.setenv("RELAY_STORE_PATH", "mongodb")
    state = tmp_path / ".state"
    state.mkdir()
    live_ledger = state / "spend.sqlite"
    live_ledger.write_bytes(b"existing-ledger-sentinel")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = run_integration_demo()
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after
    assert secret not in json.dumps(result)
    assert result["briefing"]["voice_id"] == "mock-voice"
    assert result["briefing"]["model_id"] == "mock-model"


def test_supplied_two_robot_scenario_is_copied_and_explicitly_simulated():
    scenario = default_scenario().model_dump(mode="json")
    scenario["simulated"] = False
    for observation in scenario["observations"]:
        observation["simulated"] = False
    scenario["observations"][-1]["robot_id"] = "rover-b"
    before = deepcopy(scenario)
    result = run_integration_demo(scenario)
    assert scenario == before
    assert all(row["simulated"] for row in result["telemetry"])
    assert {row["robot_id"] for row in result["telemetry"]} == {"station-a", "rover-b"}
    assert [row["observed_at"] for row in result["telemetry"]] == [
        "2026-09-26T18:00:00Z", "2026-09-26T18:00:10Z", "2026-09-26T18:00:20Z"]
    assert "ground_truth_hazard" not in json.dumps(result["report"])


def test_report_and_receipt_are_stable_across_identical_replays():
    first, second = run_integration_demo(), run_integration_demo()
    assert first["report"] == second["report"]
    assert first["receipt"] == second["receipt"]
    assert first["briefing"] == second["briefing"]


def test_budget_denial_remains_needs_review_in_the_completed_rehearsal():
    scenario = default_scenario().model_dump(mode="json")
    scenario["budget"]["max_requests"] = 0
    result = run_integration_demo(scenario)
    assert result["status"] == "completed"
    assert result["mission_outcome"] == "needs_review"
    assert any(finding["status"] == "needs_review" for finding in result["findings"])
    assert result["accounting"]["new_requests"] == 0


def test_unknown_sensor_has_no_fabricated_reference_or_clear_finding():
    scenario = default_scenario().model_dump(mode="json")
    for observation in scenario["observations"]:
        observation["kind"] = "unsupported-sensor"
    result = run_integration_demo(scenario)
    assert result["references"] == []
    assert result["mission_outcome"] == "needs_review"
    assert all(finding["status"] == "needs_review" for finding in result["findings"])


def test_empty_scenario_is_validated_not_replaced_with_default():
    with pytest.raises(ValueError):
        run_integration_demo({})


def test_timestamp_overflow_rejected_before_workflow_stages():
    scenario = default_scenario().model_dump(mode="json")
    scenario["observations"][-1]["timestamp_seconds"] = 10 ** 30
    with pytest.raises(ValueError, match="fixture timeline"):
        run_integration_demo(scenario)
