"""Local client and mixed-mode CLI checks with in-memory HTTP doubles only."""

import json
from urllib.error import HTTPError
from urllib.request import ProxyHandler

import pytest

from relay_gateway import jev_open_cli as cli, jev_open_client as client_module
from relay_gateway.jev_open_client import LoopbackOpenJevProvider, _NoRedirect
from relay_gateway.jev_provider import JevDecision
from pollard_jev.providers.openjev import REVISION


def health(**changes):
    result = {"service": "relay-local-openjev", "ready": True, "inference_simulated": False,
              "model": LoopbackOpenJevProvider.model, "actuation_enabled": False,
              "hosted_api_requests": 0, "pid": 12345}
    result.update(changes)
    return result


def decision(operation_id="local:1", **changes):
    result = {"choice": "hold", "status": "completed", "reason": "local_nli_choice",
              "confidence": None, "model": LoopbackOpenJevProvider.model,
              "operation_id": operation_id, "simulated": False,
              "metrics": {"revision": REVISION, "api_requests": 0, "local_inference": True,
                          "calls": 1, "dispatches": 1, "input_tokens": None, "output_tokens": None,
                          "estimated_usd": "0", "energy_joules": None}}
    result.update(changes)
    return result


class Reply:
    def __init__(self, data):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        assert limit == 65537
        return self.data[:limit]


class Opener:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.reply, Exception):
            raise self.reply
        return Reply(self.reply)


def make_client(monkeypatch, reply):
    opener = Opener(reply)
    monkeypatch.setattr(client_module, "build_opener", lambda *args: opener)
    return LoopbackOpenJevProvider(allow_local=True), opener


def test_explicit_optin_and_valid_loopback_port_required():
    with pytest.raises(ValueError):
        LoopbackOpenJevProvider()
    for port in (1023, 65536, True, "8770"):
        with pytest.raises(ValueError):
            LoopbackOpenJevProvider(allow_local=True, port=port)


def test_opener_disables_ambient_proxies_and_redirects(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://private-proxy.invalid:8080")
    captured = []
    monkeypatch.setattr(client_module, "build_opener", lambda *handlers: captured.extend(handlers))
    LoopbackOpenJevProvider(allow_local=True)
    assert isinstance(captured[0], ProxyHandler) and captured[0].proxies == {}
    assert isinstance(captured[1], _NoRedirect)
    assert captured[1].redirect_request(None, None, 302, None, None, "https://remote.invalid") is None


def test_health_validates_real_worker_identity_without_model_calls(monkeypatch):
    provider, opener = make_client(monkeypatch, health())
    assert provider.health()["inference_simulated"] is False
    assert opener.calls[0][0].full_url == "http://127.0.0.1:8770/health"
    assert opener.calls[0][0].get_method() == "GET" and provider.calls == 0
    for changes in ({"inference_simulated": True}, {"service": "unrelated"}, {"model": "other"},
                    {"actuation_enabled": True}, {"hosted_api_requests": 1}, {"ready": False}):
        opener.reply = health(**changes)
        with pytest.raises(ValueError):
            provider.health()


def test_valid_decision_is_one_post_with_bound_deadline(monkeypatch):
    provider, opener = make_client(monkeypatch, decision())
    result = provider.decide("{}", ("hold",), "local:1", 3)
    request, timeout = opener.calls[0]
    assert len(opener.calls) == provider.calls == 1
    assert request.full_url == "http://127.0.0.1:8770/decide" and request.get_method() == "POST"
    assert json.loads(request.data) == {"state": "{}", "choices": ["hold"], "operation_id": "local:1", "timeout_seconds": 3}
    assert timeout == 3 and result.status == "completed" and result.simulated is False
    assert result.confidence is None and result.metrics["energy_joules"] is None


def test_malformed_oversize_and_wrong_provenance_responses_are_not_actions(monkeypatch):
    provider, opener = make_client(monkeypatch, decision())
    wrong_revision = decision()
    wrong_revision["metrics"]["revision"] = "other"
    for response in (b"x" * 65537, b"not-json", [], decision(operation_id="other"),
                     decision(choice="drive_forward"), decision(simulated=True),
                     decision(confidence=0.99), wrong_revision):
        opener.reply = response
        result = provider.decide("{}", ("hold",), "local:1")
        assert result.status == "unknown" and result.choice is None
        assert result.metrics["input_tokens"] is None and result.metrics["dispatches"] is None


def test_http_failure_is_sanitized_and_never_retried(monkeypatch):
    error = HTTPError("private-response-key", 503, "private-response-key", {}, None)
    provider, opener = make_client(monkeypatch, error)
    result = provider.decide("{}", ("hold",), "local:1")
    assert len(opener.calls) == 1 and result.status == "unknown"
    assert "private-response-key" not in json.dumps(result.as_dict())
    assert result.metrics["api_requests"] == 0 and result.metrics["energy_joules"] is None


def test_invalid_deadline_never_calls_worker_and_late_reply_is_discarded(monkeypatch):
    provider, opener = make_client(monkeypatch, decision())
    for timeout in (0, 11, float("nan"), True):
        with pytest.raises(ValueError):
            provider.decide("{}", ("hold",), "local:1", timeout)
    assert opener.calls == [] and provider.calls == 0
    now = iter((0.0, 6.0, 6.0))
    monkeypatch.setattr(client_module.time, "monotonic", lambda: next(now))
    result = provider.decide("{}", ("hold",), "local:1", 5)
    assert result.status == "unknown" and result.choice is None
    assert len(opener.calls) == 1


class LocalDouble:
    """Pretends to be a loaded service solely to test orchestration provenance."""
    def __init__(self, response_status="completed", reason="local_nli_choice"):
        self.calls, self.response_status, self.reason = 0, response_status, reason

    def health(self):
        return health()

    def decide(self, state, choices, operation_id, **kwargs):
        self.calls += 1
        choice = ("escalate_gemini" if json.loads(state)["local_alarm"] else "continue_monitoring")
        response = decision(operation_id, status=self.response_status, reason=self.reason,
                            choice=choice if self.response_status == "completed" else None)
        return JevDecision(**response)


def test_demo_labels_local_supervision_and_gemini_fixtures_separately(monkeypatch):
    from relay_gateway.jev_gemini import GeminiRoleProvider
    monkeypatch.setenv("GEMINI_API_KEY", "private-fixture-key")
    monkeypatch.setenv("RELAY_ALLOW_LIVE_GEMINI", "1")
    monkeypatch.setattr(GeminiRoleProvider, "from_environment", lambda **kwargs: pytest.fail("hosted fallback"))
    provider = LocalDouble()
    result = cli.run_demo(provider)
    assert result["run_kind"] == "local_openjev_with_gemini_fixtures"
    assert result["provider_modes"] == {"supervisor": "actual_local_openjev", "mission_evidence_report": "fixture"}
    assert result["mission"]["inference_simulated"] and result["report"]["inference_simulated"]
    assert result["actions_simulated"] and result["observations_simulated"] and not result["actuation_enabled"]
    assert result["cloud_api_requests"] == 0 and result["energy_joules"] is None
    assert result["execution_status"] == "completed" and result["facts"]["review_required"]


def test_unknown_local_call_latches_hold_and_does_not_retry_changed_frame():
    provider = LocalDouble("unknown", "local_worker_unavailable_or_late")
    result = cli.run_demo(provider)
    assert provider.calls == 1 and result["execution_status"] == "incomplete"
    assert result["events"][-1]["local_alarm"] and result["events"][-1]["safe_hold"]
    assert result["report"]["inference_simulated"] is True


def test_nli_abstention_is_review_without_claiming_transport_failure():
    provider = LocalDouble("blocked", "insufficient_nli_support")
    result = cli.run_demo(provider)
    assert provider.calls == 1 and result["execution_status"] == "completed"
    assert result["facts"]["review_required"] is True


def test_cli_requires_local_flag_and_preserves_existing_output(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "LoopbackOpenJevProvider", lambda **kwargs: calls.append(1))
    with pytest.raises(SystemExit) as missing:
        cli.main(["status"])
    assert missing.value.code == 2
    output = tmp_path / "proof.json"
    output.write_text("retained")
    with pytest.raises(SystemExit) as existing:
        cli.main(["demo", "--local", "--output", str(output)])
    assert existing.value.code == 1 and calls == [] and output.read_text() == "retained"


def test_cli_startup_error_is_sanitized_and_preserves_failure_marker(monkeypatch, tmp_path, capsys):
    def bad(**kwargs):
        raise ValueError("private-configuration-key")

    monkeypatch.setattr(cli, "LoopbackOpenJevProvider", bad)
    output = tmp_path / "failure.json"
    with pytest.raises(SystemExit) as caught:
        cli.main(["status", "--local", "--output", str(output)])
    assert caught.value.code == 1
    assert "private-configuration-key" not in capsys.readouterr().err
    assert json.loads(output.read_text())["status"] == "failed_or_unknown"


def test_cli_unknown_response_nonzero_exit_keeps_complete_proof(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "LoopbackOpenJevProvider", lambda **kwargs: LocalDouble("unknown", "local_worker_unavailable_or_late"))
    output = tmp_path / "unknown.json"
    assert cli.main(["demo", "--local", "--output", str(output)]) == 2
    result = json.loads(output.read_text())
    assert result["execution_status"] == "incomplete" and result["facts"]["review_required"]
    assert result["cloud_api_requests"] == 0


def test_cli_status_queries_health_only(monkeypatch, capsys):
    provider = LocalDouble()
    monkeypatch.setattr(cli, "LoopbackOpenJevProvider", lambda **kwargs: provider)
    assert cli.main(["status", "--local"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True and provider.calls == 0
