"""All live paths here use fake adapters and isolated temporary ledgers."""

import json
import socket

import pytest

from relay_gateway.integrations import data_cli
from relay_gateway.integrations.ledger import SpendLedger
from relay_gateway.models import normalize_reference_context


def forbidden(*args, **kwargs):
    raise AssertionError("This operation must not run")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setenv("RELAY_ALLOW_LIVE_DATA", "1")
    ledger = SpendLedger(tmp_path / "spend.sqlite", history_path=None)
    return ledger, {"live": True, "operation_id": "synthetic-proof-v1", "max_usd": "0.10",
                    "_ledger_factory": lambda: ledger}


class TrackedAdapter:
    def __init__(self, adapter, ledger, calls, alter=None):
        self.adapter, self.ledger, self.calls, self.alter = adapter, ledger, calls, alter

    def __getattr__(self, name):
        method = getattr(self.adapter, name)
        if name == "close":
            return method
        def invoke(*args, **kwargs):
            snapshot = self.ledger.snapshot()
            assert snapshot["reserved_usd"] == "0.100000"
            assert snapshot["operations"][0]["status"] == "dispatched"
            self.calls.append(name)
            result = method(*args, **kwargs)
            return self.alter(name, result) if self.alter else result
        return invoke


def factory(ledger, calls, alter=None):
    def construct(provider, live):
        assert not ledger.snapshot()["operations"] or ledger.snapshot()["operations"][0]["status"] != "dispatched"
        return tuple(TrackedAdapter(adapter, ledger, calls, alter) for adapter in data_cli._adapters(provider, False))
    return construct


@pytest.mark.parametrize("provider,actions", [("mongodb", 3), ("tiger", 3), ("snowflake", 1)])
def test_mock_is_environment_independent_and_never_initializes_ledger(provider, actions, monkeypatch):
    class NoEnvironment(dict):
        def get(self, *args):
            raise AssertionError("Mock may not consult environment")
    monkeypatch.setattr(data_cli.os, "environ", NoEnvironment())
    result = data_cli.run_data_proof(provider, _ledger_factory=forbidden)
    assert result["status"] == "completed" and result["proof_verified"]
    assert result["mode"] == "mock" and not result["remote_verified"]
    assert result["actual_billed_usd"] == "0.000000"
    assert result["spending"]["status"] == "not_used"
    assert len(result["steps"]) == actions
    if provider == "snowflake":
        assert not result["evidence"]["model_use_verified"]
        assert normalize_reference_context(result["evidence"]["reference_context"])


@pytest.mark.parametrize("provider,expected", [
    ("mongodb", ["upsert_mission", "upsert_mission", "get_mission"]),
    ("tiger", ["insert_telemetry", "insert_telemetry", "query_range"]),
    ("snowflake", ["retrieve"]),
])
def test_live_admission_precedes_every_operation_and_holds_unknown(provider, expected, live):
    ledger, options = live
    calls = []
    result = data_cli.run_data_proof(provider, _adapter_factory=factory(ledger, calls), **options)
    assert calls == expected
    assert result["status"] == "completed" and result["remote_verified"]
    assert result["actual_billed_usd"] is None
    assert result["spending"]["estimated_usd"] is None
    assert result["spending"]["status"] == "unknown"
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.100000"


def test_mongodb_closes_writer_then_uses_distinct_reader(live):
    ledger, options = live
    history = []
    writer, reader = data_cli._adapters("mongodb", False)
    class Writer:
        def upsert_mission(self, mission):
            history.append("write:" + mission["review_status"])
            assert ledger.snapshot()["operations"][0]["status"] == "dispatched"
            return writer.upsert_mission(mission)
        def close(self):
            history.append("close_writer")
    class Reader:
        def get_mission(self, mission_id):
            assert history[-1] == "close_writer"
            history.append("read")
            return reader.get_mission(mission_id)
        def close(self):
            history.append("close_reader")
    result = data_cli.run_data_proof("mongodb", _adapter_factory=lambda *_: (Writer(), Reader()), **options)
    assert result["evidence"]["fresh_adapter_readback_verified"]
    assert history[:4] == ["write:pending", "write:simulated_review", "close_writer", "read"]


@pytest.mark.parametrize("amount", [None, "0", "-1", "1.000001", "NaN", "1e-2", 0.1, "0.0000001"])
def test_invalid_amount_never_builds_adapter_or_ledger(live, amount):
    _, options = live
    options.update(max_usd=amount, _ledger_factory=forbidden)
    with pytest.raises(data_cli.DataCommandError):
        data_cli.run_data_proof("tiger", _adapter_factory=forbidden, **options)


@pytest.mark.parametrize("identifier", [None, "", "x" * 81, "path/secret", "line\nsecret"])
def test_invalid_operation_id_never_builds_adapter_or_ledger(live, identifier):
    _, options = live
    options.update(operation_id=identifier, _ledger_factory=forbidden)
    with pytest.raises(data_cli.DataCommandError):
        data_cli.run_data_proof("tiger", _adapter_factory=forbidden, **options)


def test_live_switch_required_before_configuration(live, monkeypatch):
    _, options = live
    monkeypatch.delenv("RELAY_ALLOW_LIVE_DATA")
    options["_ledger_factory"] = forbidden
    with pytest.raises(data_cli.DataCommandError, match="RELAY_ALLOW_LIVE_DATA"):
        data_cli.run_data_proof("mongodb", _adapter_factory=forbidden, **options)


@pytest.mark.parametrize("provider", data_cli.PROVIDERS)
def test_invalid_configuration_does_not_open_ledger(provider, live, monkeypatch):
    _, options = live
    for name in ("MONGODB_URI", "POLLARD_MONGODB_URI", "TIGER_DATABASE_URL", "SNOWFLAKE_ACCOUNT"):
        monkeypatch.setenv(name, "secret-invalid-configuration")
    options["_ledger_factory"] = forbidden
    with pytest.raises(data_cli.DataCommandError) as caught:
        data_cli.run_data_proof(provider, **options)
    assert "secret-invalid" not in str(caught.value)


@pytest.mark.parametrize("provider", data_cli.PROVIDERS)
def test_duplicate_operation_never_dispatches_again(provider, live):
    ledger, options = live
    calls = []
    build = factory(ledger, calls)
    data_cli.run_data_proof(provider, _adapter_factory=build, **options)
    count = len(calls)
    with pytest.raises(data_cli.DataCommandError, match="duplicate"):
        data_cli.run_data_proof(provider, _adapter_factory=build, **options)
    assert len(calls) == count
    assert len(ledger.snapshot()["operations"]) == 1


def test_budget_denial_and_dispatch_claim_failure_never_call_adapter(live, monkeypatch):
    ledger, options = live
    calls = []
    monkeypatch.setattr(ledger, "mark_dispatched", forbidden)
    with pytest.raises(data_cli.DataCommandError, match="admission"):
        data_cli.run_data_proof("mongodb", _adapter_factory=factory(ledger, calls), **options)
    assert calls == []
    assert ledger.snapshot()["operations"][0]["status"] == "reserved"
    ledger.reserve("other-cloud", "Cloud", "14.9")
    with pytest.raises(data_cli.DataCommandError, match="admission"):
        data_cli.run_data_proof("tiger", _adapter_factory=factory(ledger, calls), **options)
    assert calls == [] and len(ledger.snapshot()["operations"]) == 2


@pytest.mark.parametrize("failure_status", ["unknown", "failed"])
def test_first_step_failure_stops_proof_and_retains_entire_reservation(live, failure_status):
    ledger, options = live
    calls = []
    def alter(name, result):
        return {"status": failure_status, "native_error": "secret-do-not-print"}
    result = data_cli.run_data_proof("tiger", _adapter_factory=factory(ledger, calls, alter), **options)
    assert calls == ["insert_telemetry"]
    assert result["status"] == failure_status and not result["proof_verified"]
    assert "secret-do-not-print" not in json.dumps(result)
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.100000"


def test_unexpected_timeout_stops_after_one_attempt_and_is_sanitized(live):
    ledger, options = live
    calls = []
    def timeout(name, result):
        raise TimeoutError("secret-do-not-print")
    result = data_cli.run_data_proof("mongodb", _adapter_factory=factory(ledger, calls, timeout), **options)
    assert calls == ["upsert_mission"] and result["status"] == "unknown"
    assert "secret-do-not-print" not in json.dumps(result)
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.100000"


@pytest.mark.parametrize("provider", data_cli.PROVIDERS)
def test_successful_operations_with_wrong_proof_are_not_verified(provider, live):
    ledger, options = live
    calls = []
    def alter(name, result):
        if name == "get_mission":
            result["mission"]["review_status"] = "pending"
        if name == "query_range":
            result["rows"][0]["value_milli"] = 1
        if name == "retrieve":
            result["references"] = []
        return result
    result = data_cli.run_data_proof(provider, _adapter_factory=factory(ledger, calls, alter), **options)
    assert result["status"] == "failed" and not result["remote_verified"]
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.100000"


def test_snowflake_pending_preserves_handle_without_retry(live):
    ledger, options = live
    calls = []
    def pending(name, result):
        return {"status": "unknown", "evidence": {"statement_handle": "pending-statement-123"}}
    result = data_cli.run_data_proof("snowflake", _adapter_factory=factory(ledger, calls, pending), **options)
    assert result["status"] == "unknown" and calls == ["retrieve"]
    assert result["steps"][0]["statement_handle"] == "pending-statement-123"


def test_billing_record_failure_retains_dispatched_state(live, monkeypatch):
    ledger, options = live
    monkeypatch.setattr(ledger, "mark_unknown", forbidden)
    result = data_cli.run_data_proof("tiger", _adapter_factory=factory(ledger, []), **options)
    assert result["spending"]["status"] == "dispatched_reconciliation_required"
    assert ledger.snapshot()["operations"][0]["status"] == "dispatched"
    assert ledger.snapshot()["reserved_usd"] == "0.100000"


def test_cli_json_and_sanitized_argument_errors(capsys):
    assert data_cli.main(["mongodb"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "mock"
    assert data_cli.main(["secret-unknown-provider"]) == 2
    assert "secret-unknown-provider" not in capsys.readouterr().out
    assert data_cli.main(["tiger", "--unknown", "secret-argument"]) == 2
    assert "secret-argument" not in capsys.readouterr().out
