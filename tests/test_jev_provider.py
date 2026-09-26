"""Offline proof of official API shape, fail-closed admission and reconciliation."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from urllib.error import HTTPError, URLError

import pytest

from relay_gateway.integrations.ledger import LedgerBusy, SpendLedger
from relay_gateway.jev_provider import (
    FixtureJevProvider, JEV_MODEL, JevProvider, MAX_STATE_BYTES,
    RESERVATION_USD, RESERVED_INPUT_TOKENS, _LiveTransport, _NoRedirect,
)


CHOICES = ("hold", "continue_monitoring")
STATE = '{"health":"fresh","local_alarm":false,"changed":true}'


def answer(**changes):
    result = {
        "model": JEV_MODEL,
        "answers": {"next_action": {"type": "choice", "choice": "continue_monitoring",
                                    "confidence": 0.8,
                                    "probabilities": {"hold": 0.1, "continue_monitoring": 0.9}}},
        "usage": {"input_tokens": 300, "output_tokens": 30},
    }
    result.update(changes)
    return result


@pytest.fixture
def ledger(tmp_path):
    return SpendLedger(tmp_path / "fixture.sqlite", history_path=None)


def test_exact_shape_and_settlement_before_completed_choice(ledger):
    seen = []

    def transport(payload, timeout):
        assert ledger.snapshot()["operations"][0]["status"] == "dispatched"
        assert 0 < timeout <= 5
        seen.append(payload)
        return answer()

    provider = JevProvider(offline_transport=transport, spend_ledger=ledger)
    result = provider.decide(STATE, CHOICES, "jev:mission-1:attempt-0")
    assert result.status == "completed"
    assert result.choice == "continue_monitoring"
    assert seen[0]["model"] == JEV_MODEL
    assert seen[0]["state"] == STATE
    assert seen[0]["questions"]["next_action"]["type"] == "choice"
    assert set(seen[0]["questions"]["next_action"]["criteria"]) == set(CHOICES)
    assert result.metrics["calls"] == result.metrics["dispatches"] == 1
    assert result.metrics["input_tokens"] == 300
    assert Decimal(result.metrics["estimated_usd"]) == Decimal("0.0000126")
    assert result.metrics["provider_reported_cost_usd"] is None
    assert result.metrics["reservation_held_usd"] == "0.000000"
    snapshot = ledger.snapshot()
    assert snapshot["settled_estimated_usd"] == "0.000013"
    assert snapshot["reserved_usd"] == "0.000000"
    assert result.simulated and result.as_dict()["model"] == JEV_MODEL


@pytest.mark.parametrize("changes", [
    {"state": "x" * (MAX_STATE_BYTES + 1)}, {"state": ""},
    {"choices": ("motor_forward",)}, {"choices": ("hold", "hold")},
    {"choices": ["hold"]}, {"choices": ()},
    {"timeout_seconds": 0}, {"timeout_seconds": float("nan")},
    {"timeout_seconds": 31}, {"timeout_seconds": True},
    {"operation_id": "bad\nidentifier"},
], ids=["oversize", "empty", "actuation", "duplicate-choices", "list", "no-choices",
        "zero-time", "nan-time", "long-time", "bool-time", "bad-id"])
def test_invalid_request_never_reserves_or_dispatches(ledger, changes):
    provider = JevProvider(offline_transport=lambda *args: pytest.fail("dispatch"), spend_ledger=ledger)
    args = dict(state=STATE, choices=CHOICES, operation_id="jev:valid", timeout_seconds=5)
    args.update(changes)
    result = provider.decide(**args)
    assert result.status == "blocked" and result.choice is None
    assert result.metrics["calls"] == 0
    assert ledger.snapshot()["operations"] == []


def test_duplicate_id_across_concurrent_providers_dispatches_once(ledger):
    def invoke(_):
        return JevProvider(offline_transport=lambda *args: answer(), spend_ledger=ledger).decide(
            STATE, CHOICES, "jev:concurrent")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(invoke, range(8)))
    assert sum(item.metrics["dispatches"] for item in results) == 1
    assert sum(item.status == "completed" for item in results) == 1
    assert sum(item.reason == "duplicate_operation" for item in results) == 7
    assert len(ledger.snapshot()["operations"]) == 1


def test_existing_unresolved_spending_denies_dispatch(ledger):
    prior = ledger.reserve("other-provider", "Existing provider", "15")
    ledger.mark_dispatched(prior)
    ledger.mark_unknown(prior.operation_id, reason="timeout")
    provider = JevProvider(offline_transport=lambda *args: pytest.fail("dispatch"), spend_ledger=ledger)
    result = provider.decide(STATE, CHOICES, "jev:budget")
    assert result.reason == "budget_exhausted"
    assert result.choice is None and result.metrics["calls"] == 0
    assert ledger.snapshot()["unknown_reserved_usd"] == "15.000000"


@pytest.mark.parametrize("error,reason", [
    (TimeoutError("private credential"), "provider_timeout"),
    (URLError("private credential"), "provider_connection_error"),
    (HTTPError("private credential", 429, "private credential", {}, None), "provider_http_error"),
    (RuntimeError("private credential"), "provider_failure"),
])
def test_provider_failure_retains_full_reservation_and_never_retries(ledger, error, reason):
    calls = []

    def transport(*args):
        calls.append(1)
        raise error

    result = JevProvider(offline_transport=transport, spend_ledger=ledger).decide(STATE, CHOICES, "jev:failure")
    assert result.status == "unknown" and result.reason == reason
    assert result.choice is None and len(calls) == 1
    assert "private credential" not in json.dumps(result.as_dict())
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.002753"


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": True, "output_tokens": 0},
                                   {"input_tokens": -1, "output_tokens": 1},
                                   {"input_tokens": 1, "output_tokens": "2"}])
def test_unreliable_usage_blocks_choice_and_preserves_unknown(ledger, usage):
    provider = JevProvider(offline_transport=lambda *args: answer(usage=usage), spend_ledger=ledger)
    result = provider.decide(STATE, CHOICES, "jev:usage")
    assert result.reason == "missing_or_invalid_usage" and result.choice is None
    assert ledger.snapshot()["operations"][0]["unknown_reason"] == "missing_usage"


@pytest.mark.parametrize("change", ["choice", "confidence", "probabilities", "type", "sum", "maximum"])
def test_invalid_answer_is_settled_but_rejected(ledger, change):
    response = answer()
    selected = response["answers"]["next_action"]
    if change == "sum":
        selected["probabilities"]["hold"] = 0.5
    elif change == "maximum":
        selected["choice"] = "hold"
    else:
        selected[change] = {"choice": "motor_forward", "confidence": float("nan"),
                            "probabilities": {}, "type": "noul"}[change]
    result = JevProvider(offline_transport=lambda *args: response, spend_ledger=ledger).decide(
        STATE, CHOICES, "jev:invalid")
    assert result.status == "failed" and result.choice is None
    assert ledger.snapshot()["operations"][0]["status"] == "settled"


def test_changed_model_retains_reservation_due_to_unknown_price(ledger):
    result = JevProvider(offline_transport=lambda *args: answer(model="jev-latest"),
                         spend_ledger=ledger).decide(STATE, CHOICES, "jev:model")
    assert result.reason == "model_mismatch" and result.choice is None
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.002753"


def test_late_valid_answer_reconciles_cost_but_discards_choice(ledger):
    now = [10.0]

    def transport(*args):
        now[0] = 16.0
        return answer()

    provider = JevProvider(offline_transport=transport, spend_ledger=ledger, clock=lambda: now[0])
    result = provider.decide(STATE, CHOICES, "jev:late", timeout_seconds=5)
    assert result.reason == "deadline_expired" and result.choice is None
    assert result.metrics["latency_ms"] == 6000
    assert ledger.snapshot()["reserved_usd"] == "0.000000"


def test_deadline_consumed_in_admission_cancels_without_dispatch(ledger):
    now = [0.0]

    class SlowLedger:
        def reserve(self, *args):
            ticket = ledger.reserve(*args)
            now[0] = 6
            return ticket

        def __getattr__(self, name):
            return getattr(ledger, name)

    provider = JevProvider(offline_transport=lambda *args: pytest.fail("dispatch"),
                           spend_ledger=SlowLedger(), clock=lambda: now[0])
    result = provider.decide(STATE, CHOICES, "jev:slow-ledger", timeout_seconds=5)
    assert result.reason == "deadline_expired" and result.metrics["calls"] == 0
    assert ledger.snapshot()["operations"][0]["status"] == "cancelled"


def test_settlement_failure_retains_dispatched_cost(ledger):
    class FailingLedger:
        def settle(self, *args):
            raise LedgerBusy("private data")

        def __getattr__(self, name):
            return getattr(ledger, name)

    result = JevProvider(offline_transport=lambda *args: answer(), spend_ledger=FailingLedger()).decide(
        STATE, CHOICES, "jev:settlement")
    assert result.reason == "settlement_unavailable" and result.choice is None
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.002753"


def test_usage_above_reservation_records_overrun_then_rejects(ledger):
    result = JevProvider(offline_transport=lambda *args: answer(usage={
        "input_tokens": RESERVED_INPUT_TOKENS + 1000, "output_tokens": 1}), spend_ledger=ledger).decide(
            STATE, CHOICES, "jev:overrun")
    assert result.reason == "input_limit_exceeded" and result.choice is None
    operation = ledger.snapshot()["operations"][0]
    assert operation["status"] == "settled"
    assert Decimal(operation["reservation_overrun_usd"]) > 0


def test_credentials_alone_never_enable_live(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-private-key")
    monkeypatch.setenv("RELAY_ALLOW_LIVE_JEV", "1")
    with pytest.raises(ValueError, match="explicit opt-in"):
        JevProvider.from_environment()
    monkeypatch.delenv("RELAY_ALLOW_LIVE_JEV")
    with pytest.raises(ValueError, match="explicit opt-in"):
        JevProvider.from_environment(allow_live=True)


def test_live_refuses_isolated_ledger_or_test_task_facade(monkeypatch, ledger):
    from relay_gateway.jev_budget import JevTaskLedger
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-private-key")
    monkeypatch.setenv("RELAY_ALLOW_LIVE_JEV", "1")
    for supplied in (ledger, JevTaskLedger.for_test(ledger)):
        with pytest.raises(ValueError, match="canonical"):
            JevProvider.from_environment(allow_live=True, spend_ledger=supplied)
    assert ledger.snapshot()["operations"] == []


def test_task_facade_tracks_canonical_operation_id_in_metrics(ledger):
    from relay_gateway.jev_budget import JevTaskLedger, TASK_PREFIX
    facade = JevTaskLedger.for_test(ledger)
    result = JevProvider(offline_transport=lambda *args: answer(), spend_ledger=facade).decide(
        STATE, CHOICES, "jev:facade")
    assert result.status == "completed"
    assert result.metrics["shared_spend_operation_id"].startswith(TASK_PREFIX)
    assert ledger.snapshot()["operations"][0]["operation_id"] == result.metrics["shared_spend_operation_id"]


def test_native_transport_fixed_endpoint_one_post_and_redirect_rejection(monkeypatch):
    from relay_gateway import jev_provider
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, amount):
            assert amount == 65537
            return json.dumps(answer()).encode()

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return Response()

    monkeypatch.setattr(jev_provider, "build_opener", lambda *args: Opener())
    result = _LiveTransport("fixture-private-key")({"state": STATE}, 3)
    assert result["model"] == JEV_MODEL and len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == "https://api.typesafe.ai/v1/systemone"
    assert request.get_method() == "POST" and timeout == 3
    assert _NoRedirect().redirect_request(None, None, 307, None, None, "https://elsewhere") is None


@pytest.mark.parametrize("state,expected", [
    ({"health": "fresh", "local_alarm": False}, "continue_monitoring"),
    ({"health": "fresh", "local_alarm": True}, "escalate_gemini"),
    ({"health": "conflicting"}, "escalate_gemini"),
    ({"health": "missing"}, "request_evidence"),
])
def test_fixture_is_explicitly_simulated_and_has_zero_paid_cost(state, expected):
    provider = FixtureJevProvider()
    result = provider.decide(json.dumps(state),
        ("hold", "continue_monitoring", "escalate_gemini", "request_evidence"), "fixture")
    assert result.choice == expected and result.simulated
    assert result.metrics["actual_paid_usd"] == "0"
    assert result.metrics["cost_basis"] == "illustrative_fixture_estimate"


def test_fixture_bad_choice_never_returns_action():
    result = FixtureJevProvider(choice_override="motor_forward").decide(STATE, CHOICES, "fixture")
    assert result.reason == "invalid_choice" and result.choice is None
