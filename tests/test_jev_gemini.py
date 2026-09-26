"""Entirely offline role, accounting, failure and SDK configuration checks."""

from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from relay_gateway.integrations.ledger import SpendLedger
from relay_gateway.jev_budget import JevTaskLedger
from relay_gateway.jev_gemini import (FixtureGeminiRoles, GeminiRoleProvider,
                                     _FixtureRoleProvider, _TimedGeminiProvider)
from relay_gateway.models import Observation
from relay_gateway.providers import Pricing


def water(value=850, event_id="water-1", **kwargs):
    return Observation(event_id=event_id, robot_id="station-a", value_milli=value,
                       unit="wetness", **kwargs)


def native_fixture(tmp_path, *, text=None, error=None, missing_usage=False, budget=None):
    from google.genai import types
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        metadata = None if missing_usage else types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=3, thoughts_token_count=2, total_token_count=15)
        return SimpleNamespace(text=text or '{"intent":"inspect_water","summary":"Offline SDK fixture."}',
                               usage_metadata=metadata)

    ledger = JevTaskLedger.for_test(SpendLedger(tmp_path / "spend.sqlite", history_path=None))
    provider = _TimedGeminiProvider(model="gemini-3.5-flash-lite", pricing=Pricing(),
                                    client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
                                    spend_ledger=ledger)
    roles = GeminiRoleProvider(provider, allow_live=True, budget=budget)
    return roles, ledger, calls


def test_default_never_reads_credentials_or_dispatches_native(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-secret-must-not-leak")
    monkeypatch.setenv("RELAY_ALLOW_LIVE_GEMINI", "1")
    monkeypatch.setenv("RELAY_PROVIDER", "gemini")
    roles = FixtureGeminiRoles()
    try:
        mission = roles.interpret_mission("Inspect water near station A.", "mission-1")
        finding = roles.inspect_evidence([water()], "mission-1", "event-1")
        summary = roles.report_summary({"local_alarm_latched": True}, "mission-1")
        assert mission["evidence"]["intent"] == "inspect_water"
        assert finding["evidence"]["status"] == "suspected_hazard"
        assert summary["evidence"]["status"] == "review_required"
        assert roles.calls == 3
        for result in (mission, finding, summary):
            assert result["status"] == "completed"
            assert result["simulated"] and result["inference_simulated"]
            assert result["usage"]["basis"] == "illustrative_fixture"
            assert result["usage"]["calls"] == 1
            assert result["usage"]["total_tokens"] > 0
            assert result["estimated_usd"] != "0.000000"
            assert result["actual_billed_usd"] == "0.000000"
            assert not result["actuation_enabled"] and not result["alarm_clear_authorized"]
            assert result["pollard_node_id"] and result["prompt_sha256"] and result["result_sha256"]
            assert result["latency_ms"] >= 0
            assert "fixture-secret" not in json.dumps(result)
    finally:
        roles.close()


@pytest.mark.parametrize("observations", [[], [water(None)], [water(850), water(0, "dry")],
                                         [water(1500)], [water(kind="gas")]])
def test_missing_unsupported_and_conflicting_fixture_evidence_need_review(observations):
    roles = FixtureGeminiRoles()
    try:
        result = roles.inspect_evidence(observations, "mission-1", "event-1")
        assert result["evidence"]["status"] == "needs_review"
        assert result["evidence"]["confidence_milli"] == 0
        assert not result["alarm_clear_authorized"]
    finally:
        roles.close()


def test_ground_truth_never_enters_any_role_payload():
    captured = []

    class Capture(_FixtureRoleProvider):
        def __call__(self, payload):
            captured.append(json.dumps(payload))
            return super().__call__(payload)

    roles = GeminiRoleProvider(Capture())
    try:
        roles.inspect_evidence([water(ground_truth_hazard=True)], "mission", "event")
        roles.report_summary({"events": [{"ground_truth_hazard": True}],
                              "groundTruthLeak": True, "evaluation": {"hazard": True},
                              "expected_hazard": True}, "mission")
        assert len(captured) == 2
        for payload in captured:
            assert "ground_truth" not in payload and "groundTruth" not in payload
            assert "evaluation" not in payload and "expected_hazard" not in payload
            assert "untrusted data" in payload
    finally:
        roles.close()


@pytest.mark.parametrize("role,data,operation,timeout", [
    ("mission", {"text": "x" * 2001}, "invalid", 5),
    ("mission", {"text": ""}, "invalid", 5),
    ("evidence", {"observations": [water().evidence()] * 9}, "invalid", 5),
    ("evidence", {"observations": [water(simulated=False).evidence()]}, "real-reading", 5),
    ("report", {"facts": {"long": "x" * 13000}}, "invalid", 5),
    ("report", {"facts": {"bad": float("nan")}}, "invalid", 5),
    ("mission", {"text": "inspect"}, "invalid secret/?", 5),
    ("mission", {"text": "inspect"}, "invalid", float("inf")),
    ("unsupported", {}, "invalid", 5),
])
def test_invalid_input_prevents_dispatch(role, data, operation, timeout):
    roles = FixtureGeminiRoles()
    try:
        result = roles.run(role, data, operation, timeout)
        assert result["status"] == "blocked" and result["reason"] == "invalid_input"
        assert roles.calls == 0
    finally:
        roles.close()


@pytest.mark.parametrize("budget", [{"max_requests": 0}, {"max_tokens": 1}, {"max_usd": "0"}])
def test_pollard_request_token_and_dollar_admission(budget):
    roles = FixtureGeminiRoles(budget=budget)
    try:
        result = roles.interpret_mission("Inspect water.", "limited")
        assert result["status"] == "blocked" and result["reason"] == "budget_exhausted"
        assert roles.calls == 0 and result["usage"]["calls"] == 0
    finally:
        roles.close()


def test_roles_share_allowance_and_duplicate_is_never_dispatched_twice():
    roles = FixtureGeminiRoles(budget={"max_requests": 1})
    try:
        first = roles.interpret_mission("Inspect water", "limited")
        duplicate = roles.interpret_mission("Inspect water", "limited")
        exhausted = roles.report_summary({}, "limited")
        assert first["status"] == "completed"
        assert duplicate["reason"] == "duplicate_operation"
        assert exhausted["reason"] == "budget_exhausted"
        assert roles.calls == 1
    finally:
        roles.close()


def test_zero_deadline_prevents_call_and_late_response_is_discarded(monkeypatch):
    roles = FixtureGeminiRoles()
    try:
        assert roles.run("mission", {"text": "Inspect water"}, "expired", 0)["reason"] == "deadline_expired"
        assert roles.calls == 0
        readings = iter([100.0, 102.0, 102.0])
        monkeypatch.setattr("relay_gateway.jev_gemini.perf_counter", lambda: next(readings))
        result = roles.run("mission", {"text": "Inspect water"}, "late", 1)
        assert result["status"] == "unknown" and result["reason"] == "deadline_expired"
        assert result["evidence"]["intent"] == "needs_review"
        assert result["usage"]["calls"] == 1 and result["usage"]["total_tokens"] > 0
        assert result["latency_ms"] == 2000
    finally:
        roles.close()


def test_sdk_schema_timeout_no_retry_thinking_tokens_and_shared_settlement(tmp_path):
    roles, ledger, calls = native_fixture(tmp_path)
    try:
        result = roles.run("mission", {"text": "Inspect water"}, "sdk:mission", 2.5)
        assert result["status"] == "completed"
        assert len(calls) == 1 and roles.calls == 1
        assert result["simulated"] and not result["inference_simulated"]
        assert result["usage"] == {"calls": 1, "input_tokens": 10, "output_tokens": 5,
                                   "total_tokens": 15, "basis": "provider_reported"}
        assert result["estimated_usd"] == "0.000030" and result["actual_billed_usd"] is None
        assert ledger.snapshot()["settled_estimated_usd"] == "0.000030"
        config = calls[0]["config"]
        assert 0 < config.http_options.timeout <= 2500 and config.http_options.retry_options.attempts == 1
        assert config.thinking_config is None
        assert config.http_options.extra_body == {"generationConfig": {"thinkingConfig": {"thinkingLevel": "minimal"}}}
        assert config.response_mime_type == "application/json"
        assert config.response_json_schema["properties"]["intent"]["enum"] == ["inspect_water", "needs_review"]
        assert config.max_output_tokens == 512 and config.automatic_function_calling.disable
        assert result["shared_spend_operation_id"].startswith("jev-integration-v1:")
    finally:
        roles.close()


@pytest.mark.parametrize("missing_usage", [False, True])
def test_unknown_provider_outcome_retains_reservation_and_sanitizes_error(tmp_path, missing_usage):
    roles, ledger, calls = native_fixture(tmp_path, missing_usage=missing_usage,
                                        error=None if missing_usage else TimeoutError("secret=value native sensitive payload"))
    try:
        result = roles.interpret_mission("Inspect water", "unknown")
        snapshot = ledger.snapshot()
        assert result["status"] == "unknown" and result["evidence"]["intent"] == "needs_review"
        assert len(calls) == 1 and result["usage"]["calls"] == 1
        assert result["usage"]["total_tokens"] is None
        assert "secret=value" not in json.dumps(result)
        assert snapshot["operations"][0]["status"] == "unknown"
        assert Decimal(snapshot["unknown_reserved_usd"]) > 0
        assert result["estimated_usd"] is None
        assert Decimal(result["held_estimated_usd"]) > 0
        # A new role wrapper/Pollard store still cannot redispatch the same paid operation.
        retry = GeminiRoleProvider(roles.provider, allow_live=True)
        try:
            duplicate = retry.interpret_mission("Inspect water", "unknown")
            assert duplicate["reason"] == "duplicate_external_operation"
            assert len(calls) == 1
        finally:
            retry.close()
    finally:
        roles.close()


def test_combined_task_cap_denies_before_provider_dispatch(tmp_path):
    roles, ledger, calls = native_fixture(tmp_path)
    try:
        ledger.reserve("existing-jev-call", "TypeSafe Jev", "0.499999")
        result = roles.interpret_mission("Inspect water", "exhausted")
        assert result["status"] == "blocked" and result["reason"] == "budget_exhausted"
        assert calls == [] and roles.calls == 0
    finally:
        roles.close()


def test_changing_deadline_does_not_authorize_retry_across_role_instances(tmp_path):
    roles, ledger, calls = native_fixture(tmp_path)
    try:
        first = roles.run("mission", {"text": "Inspect water"}, "stable-operation", 2)
        assert first["status"] == "completed"
        second = GeminiRoleProvider(roles.provider, allow_live=True)
        try:
            duplicate = second.run("mission", {"text": "Inspect water"}, "stable-operation", 5)
            assert duplicate["status"] == "blocked" and duplicate["reason"] == "duplicate_external_operation"
            assert len(calls) == 1 and len(ledger.snapshot()["operations"]) == 1
        finally:
            second.close()
    finally:
        roles.close()


@pytest.mark.parametrize("text", ["not json", '{"intent":"drive","summary":"Unsafe choice"}',
                                  '{"intent":"inspect_water","summary":"OK","actuate":true}'])
def test_invalid_structured_output_is_accounted_then_rejected(tmp_path, text):
    roles, ledger, calls = native_fixture(tmp_path, text=text)
    try:
        result = roles.interpret_mission("Inspect water", "invalid-output")
        assert result["status"] == "failed" and result["reason"] == "invalid_response"
        assert result["evidence"]["intent"] == "needs_review"
        assert ledger.snapshot()["settled_estimated_usd"] == "0.000030"
        assert len(calls) == 1
    finally:
        roles.close()


def test_code_fence_parsing_and_report_cannot_clear_alarm(tmp_path):
    roles, _, _ = native_fixture(tmp_path, text='```json\n{"status":"monitoring","summary":"Observation summary."}\n```')
    try:
        result = roles.report_summary({"local_alarm_latched": True}, "latched")
        assert result["status"] == "completed"
        assert result["evidence"]["status"] == "review_required"
        assert result["alarm_clear_authorized"] is False
    finally:
        roles.close()


def test_live_factory_requires_optin_and_canonical_task_facade(tmp_path):
    with pytest.raises(ValueError, match="allow_live"):
        GeminiRoleProvider.from_environment()
    isolated = JevTaskLedger.for_test(SpendLedger(tmp_path / "test.sqlite", history_path=None))
    with pytest.raises(ValueError, match="canonical"):
        GeminiRoleProvider.from_environment(allow_live=True, spend_ledger=isolated)


@pytest.mark.parametrize("model,wire_thinking", [
    ("gemini-3.5-flash-lite", {"thinkingLevel": "minimal"}),
    ("gemini-3.8-flash", {"thinkingLevel": "minimal"}),
    ("gemini-2.5-flash", {"thinkingBudget": 0}),
    ("gemini-2.5-flash-lite", {"thinkingBudget": 0}),
])
@pytest.mark.parametrize("role,data,answer", [
    ("mission", {"text": "Inspect water"}, {"intent": "inspect_water", "summary": "Offline SDK mission."}),
    ("evidence", {"observations": [water().evidence()]}, {
        "status": "suspected_hazard", "hazard_type": "standing_water", "confidence_milli": 800,
        "summary": "Offline SDK metadata finding.", "recommended_action": "Request review.", "cited_reference_ids": []}),
    ("report", {"facts": {"local_alarm_latched": True}}, {"status": "review_required", "summary": "Offline SDK report."}),
])
def test_actual_sdk_serializes_all_role_configs_using_offline_http_transport(tmp_path, monkeypatch, role, data, answer, model, wire_thinking):
    """Exercise SDK serialization, request and usage decoding without a socket."""
    import httpx
    from google import genai
    from google.genai import types

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    captured = []

    def transport(request):
        assert request.headers.get("x-goog-api-key") == "offline-placeholder"
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(answer)}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3,
                              "thoughtsTokenCount": 2, "totalTokenCount": 15},
            "modelVersion": model})

    client = httpx.Client(transport=httpx.MockTransport(transport))
    with genai.Client(api_key="offline-placeholder", vertexai=False,
                      http_options=types.HttpOptions(httpx_client=client)) as sdk:
        ledger = JevTaskLedger.for_test(SpendLedger(tmp_path / "offline-spend.sqlite", history_path=None))
        # Inject the real models object with its explicitly socket-free transport.
        # The wrapper denotes an offline client and keeps native-live ledger rules intact.
        provider = _TimedGeminiProvider(model=model, pricing=Pricing(),
            client=SimpleNamespace(models=sdk.models), spend_ledger=ledger)
        roles = GeminiRoleProvider(provider, allow_live=True)
        try:
            result = roles.run(role, data, "sdk-serialization:" + role)
            assert result["status"] == "completed", result.get("diagnostic")
            assert len(captured) == 1
            config = captured[0]["generationConfig"]
            assert config["responseMimeType"] == "application/json"
            assert config["maxOutputTokens"] == 512
            assert config["responseJsonSchema"]["additionalProperties"] is False
            assert config["thinkingConfig"] == wire_thinking
            assert "thinking_level" not in json.dumps(captured)
            assert "thinking_budget" not in json.dumps(captured)
            assert result["usage"]["total_tokens"] == 15
            assert ledger.snapshot()["settled_estimated_usd"] == "0.000030"
        finally:
            roles.close()


@pytest.mark.parametrize("status_code,exception_type", [(400, "ClientError"), (403, "ClientError"),
                                                        (429, "ClientError"), (500, "ServerError")])
def test_actual_sdk_http_error_has_safe_diagnostic_and_no_retry(tmp_path, monkeypatch, status_code, exception_type):
    import httpx
    from google import genai
    from google.genai import types

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    calls = []

    def transport(request):
        calls.append(True)
        return httpx.Response(status_code, json={"error": {
            "code": status_code, "message": "secret-native-body-and-credential-fixture", "status": "TEST_ERROR"}})

    client = httpx.Client(transport=httpx.MockTransport(transport))
    with genai.Client(api_key="offline-placeholder", vertexai=False,
                      http_options=types.HttpOptions(httpx_client=client)) as sdk:
        ledger = JevTaskLedger.for_test(SpendLedger(tmp_path / "offline-spend.sqlite", history_path=None))
        provider = _TimedGeminiProvider(model="gemini-3.5-flash-lite", pricing=Pricing(),
            client=SimpleNamespace(models=sdk.models), spend_ledger=ledger)
        store = tmp_path / "pollard.sqlite"
        roles = GeminiRoleProvider(provider, allow_live=True, store_path=store)
        try:
            result = roles.run("mission", {"text": "Inspect water"}, "sdk-http-error")
            assert result["status"] == "unknown" and result["reason"] == "provider_or_accounting_failure"
            assert result["diagnostic"] == {"exception_type": exception_type, "http_status": status_code,
                                             "category": "UNCLASSIFIED"}
            assert result["estimated_usd"] is None and Decimal(result["held_estimated_usd"]) > 0
            assert len(calls) == 1
            assert "secret-native-body" not in json.dumps(result)
            assert ledger.snapshot()["operations"][0]["status"] == "unknown"
        finally:
            roles.close()
        assert b"secret-native-body" not in store.read_bytes()


@pytest.mark.parametrize("body,expected", [
    ({"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID", "metadata": {"secret": "value"}}]}, "API_KEY_INVALID"),
    ({"status": "PERMISSION_DENIED", "details": [{"reason": "API_KEY_SERVICE_BLOCKED"}]}, "API_KEY_SERVICE_BLOCKED"),
    ({"status": "PERMISSION_DENIED"}, "PERMISSION_DENIED"),
    ({"status": "INVALID_ARGUMENT", "message": "API key not valid. secret-native-body"}, "API_KEY_INVALID"),
    ({"status": "INVALID_ARGUMENT", "message": "Invalid generationConfig.responseJsonSchema: secret-native-body"}, "INVALID_ARGUMENT_SCHEMA"),
    ({"status": "INVALID_ARGUMENT", "message": "Unsupported thinking_level secret-native-body"}, "INVALID_ARGUMENT_THINKING"),
    ({"status": "INVALID_ARGUMENT", "message": "secret-native-body"}, "INVALID_ARGUMENT"),
    ({"status": "secret-native-status", "message": "secret-native-body", "details": [{"reason": "secret-native-reason"}]}, "UNCLASSIFIED"),
])
def test_provider_error_categories_are_fixed_literals_only(tmp_path, body, expected):
    from google.genai.errors import ClientError

    error = ClientError(400, {"error": {"message": "secret-native-body", **body}})
    roles, ledger, calls = native_fixture(tmp_path, error=error)
    # Use a persistent Pollard store to assert sensitive error content is absent.
    roles.close()
    store = tmp_path / "category-pollard.sqlite"
    roles = GeminiRoleProvider(roles.provider, allow_live=True, store_path=store)
    try:
        result = roles.run("mission", {"text": "Inspect water"}, "category:mission")
        assert result["status"] == "unknown"
        assert result["diagnostic"] == {"exception_type": "ClientError", "http_status": 400,
                                         "category": expected}
        assert "secret-native" not in json.dumps(result)
        assert len(calls) == 1 and ledger.snapshot()["operations"][0]["status"] == "unknown"
    finally:
        roles.close()
    assert b"secret-native" not in store.read_bytes()
