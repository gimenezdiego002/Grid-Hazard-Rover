"""CLI opt-in, proof-file handling and admission checks with offline doubles."""

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from types import SimpleNamespace

import pytest

from relay_gateway import jev_budget, jev_cli, jev_gemini, jev_provider
from relay_gateway.integrations.ledger import SpendLedger
from relay_gateway.jev_budget import JevTaskLedger


def live_args(output, operation="smoke-test"):
    return ["live-smoke", "--live", "--provider", "jev", "--operation-id", operation,
            "--output", str(output)]


@pytest.mark.parametrize("command", [["demo"], ["compare"]])
def test_default_command_ignores_all_live_keys_and_switches(monkeypatch, tmp_path, capsys, command):
    for name in ("RELAY_ALLOW_LIVE_JEV", "RELAY_ALLOW_LIVE_GEMINI"):
        monkeypatch.setenv(name, "1")
    for name in ("TYPESAFE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(name, "private-fixture-key")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Live constructor called")

    monkeypatch.setattr(jev_provider.JevProvider, "from_environment", forbidden)
    monkeypatch.setattr(jev_gemini.GeminiRoleProvider, "from_environment", forbidden)
    monkeypatch.setattr(jev_budget.JevTaskLedger, "__init__", forbidden)
    destination = tmp_path / "fixture.json"
    assert jev_cli.main(command + ["--output", str(destination)]) == 0
    assert calls == []
    result = json.loads(destination.read_text())
    assert result["run_kind"] == "fixture_replay"
    assert "private-fixture-key" not in capsys.readouterr().out


def test_live_subcommand_requires_explicit_flag_before_construction(tmp_path):
    args = live_args(tmp_path / "proof.json")
    args.remove("--live")
    with pytest.raises(SystemExit) as caught:
        jev_cli.main(args)
    assert caught.value.code == 2


def test_existing_live_proof_blocks_before_ledger_or_provider(monkeypatch, tmp_path, capsys):
    output = tmp_path / "existing.json"
    output.write_text('{"original":true}')
    calls = []
    monkeypatch.setattr(jev_budget.JevTaskLedger, "__init__", lambda *args: calls.append("ledger"))
    monkeypatch.setattr(jev_provider.JevProvider, "from_environment", lambda **kwargs: calls.append("provider"))
    assert jev_cli.main(live_args(output)) == 2
    assert calls == []
    assert output.read_text() == '{"original":true}'
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_invalid_operation_id_is_refused_before_live_setup(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(jev_budget.JevTaskLedger, "__init__", lambda *args: called.append(1))
    assert jev_cli.main(live_args(tmp_path / "proof.json", "secret/key")) == 2
    assert called == []


def test_invalid_output_parent_blocks_before_live_setup(monkeypatch, tmp_path):
    parent = tmp_path / "ordinary-file"
    parent.write_text("retained")
    called = []
    monkeypatch.setattr(jev_budget.JevTaskLedger, "__init__", lambda *args: called.append(1))
    assert jev_cli.main(live_args(parent / "proof.json")) == 2
    assert called == [] and parent.read_text() == "retained"


def test_missing_credentials_and_native_admission_never_leak_errors(monkeypatch, tmp_path, capsys):
    def unavailable(*args, **kwargs):
        raise RuntimeError("private-provider-key-and-body")

    monkeypatch.setattr(jev_budget.JevTaskLedger, "__init__", unavailable)
    assert jev_cli.main(live_args(tmp_path / "proof.json")) == 2
    output = capsys.readouterr().out
    assert "private-provider" not in output
    assert json.loads(output)["status"] == "blocked"


def test_live_factory_rejects_test_ledger_even_when_credentials_exist(monkeypatch, tmp_path):
    fixture = JevTaskLedger.for_test(SpendLedger(tmp_path / "fixture.sqlite", history_path=None))

    def isolated_init(instance):
        instance.__dict__.update(fixture.__dict__)

    monkeypatch.setattr(JevTaskLedger, "__init__", isolated_init)
    monkeypatch.setenv("RELAY_ALLOW_LIVE_JEV", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-fixture-key")
    calls = []
    monkeypatch.setattr(jev_provider, "_LiveTransport", lambda *args: calls.append(1))
    assert jev_cli.main(live_args(tmp_path / "proof.json")) == 2
    assert calls == [] and fixture.snapshot()["operations"] == []


@pytest.mark.parametrize("missing", ["switch", "key"])
def test_live_prerequisite_missing_prevents_native_transport(monkeypatch, tmp_path, missing):
    monkeypatch.setenv("RELAY_ALLOW_LIVE_JEV", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-fixture-key")
    monkeypatch.delenv("RELAY_ALLOW_LIVE_JEV" if missing == "switch" else "TYPESAFE_API_KEY")
    monkeypatch.setattr(jev_budget, "JevTaskLedger", lambda: object())
    calls = []
    monkeypatch.setattr(jev_provider, "_LiveTransport", lambda *args: calls.append(1))
    assert jev_cli.main(live_args(tmp_path / "proof.json")) == 2
    assert calls == []


def test_exhausted_combined_task_cap_is_preserved_in_cli_proof(monkeypatch, tmp_path):
    shared = SpendLedger(tmp_path / "fixture.sqlite", history_path=None)
    facade = JevTaskLedger.for_test(shared)
    pending = facade.reserve("earlier-gemini", "Gemini", "0.50")
    facade.mark_dispatched(pending)
    facade.mark_unknown(pending.operation_id, reason="timeout")
    calls = []
    adapter = jev_provider.JevProvider(offline_transport=lambda *args: calls.append(1), spend_ledger=facade)
    monkeypatch.setattr(jev_budget, "JevTaskLedger", lambda: facade)
    monkeypatch.setattr(jev_provider.JevProvider, "from_environment", lambda **kwargs: adapter)
    output = tmp_path / "proof.json"
    assert jev_cli.main(live_args(output)) != 0
    proof = json.loads(output.read_text())
    assert proof["task_outcome"] == "needs_review" and proof["local_alarm"] is True
    assert proof["provider_result"]["reason"] == "budget_exhausted"
    assert proof["provider_result"]["metrics"]["calls"] == 0
    assert proof["task_spending"]["committed_estimated_usd"] == "0.500000"
    assert shared.snapshot()["unknown_reserved_usd"] == "0.500000"
    assert calls == []


def test_one_offline_double_records_live_shape_with_unknown_cost(monkeypatch, tmp_path):
    class Ledger:
        def task_snapshot(self):
            return {"task_cap_usd": "0.50", "committed_estimated_usd": "0.002753"}

    class Provider:
        def decide(self, state, choices, operation_id, timeout_seconds):
            packet = json.loads(state)
            assert packet["simulated"] and packet["local_alarm"]
            assert "continue_monitoring" not in choices
            result = {"choice": None, "status": "unknown", "reason": "provider_timeout",
                      "metrics": {"estimated_usd": None, "provider_reported_cost_usd": None}}
            return SimpleNamespace(status="unknown", as_dict=lambda: result)

    monkeypatch.setattr(jev_budget, "JevTaskLedger", Ledger)
    monkeypatch.setattr(jev_provider.JevProvider, "from_environment", lambda **kwargs: Provider())
    output = tmp_path / "proof.json"
    assert jev_cli.main(live_args(output)) != 0
    proof = json.loads(output.read_text())
    assert proof["run_kind"] == "actual_provider_on_synthetic_observations"
    assert proof["task_outcome"] == "needs_review" and proof["safe_hold"] is True
    assert proof["actuation_enabled"] is False
    assert proof["provider_result"]["metrics"]["estimated_usd"] is None


def test_concurrent_live_runs_cannot_overwrite_same_proof_path(monkeypatch, tmp_path):
    entered, release = Event(), Event()
    calls = []

    class Ledger:
        def task_snapshot(self):
            return {}

    class Provider:
        def decide(self, *args, **kwargs):
            calls.append(1)
            entered.set()
            assert release.wait(5)
            return SimpleNamespace(status="completed", as_dict=lambda: {
                "status": "completed", "choice": "hold", "metrics": {"estimated_usd": "0.00001"}})

    monkeypatch.setattr(jev_budget, "JevTaskLedger", Ledger)
    monkeypatch.setattr(jev_provider.JevProvider, "from_environment", lambda **kwargs: Provider())
    path = tmp_path / "same-proof.json"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(jev_cli.main, live_args(path, "run-one"))
        assert entered.wait(5)
        second = pool.submit(jev_cli.main, live_args(path, "run-two"))
        try:
            # Exclusive proof admission must reject before waiting on a provider.
            assert second.result(timeout=2) == 2
        finally:
            release.set()
        assert first.result(timeout=5) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("status", ["unknown", "failed", "blocked"])
def test_failed_live_result_has_nonzero_exit_and_preserves_proof(monkeypatch, tmp_path, status):
    response = {"run_kind": "actual_provider_on_synthetic_observations", "task_outcome": "needs_review",
                "provider_results": [{"role": "mission", "status": status,
                                      "usage": {"calls": 1, "input_tokens": None},
                                      "estimated_usd": None}], "actuation_enabled": False}
    monkeypatch.setattr(jev_cli, "_live_smoke_body", lambda args: response)
    output = tmp_path / "failure-proof.json"
    assert jev_cli.main(live_args(output)) != 0
    assert json.loads(output.read_text())["provider_results"][0]["status"] == status


def test_completed_live_models_can_leave_hazard_for_review_with_success_exit(monkeypatch, tmp_path):
    response = {"run_kind": "actual_provider_on_synthetic_observations", "task_outcome": "needs_review",
                "provider_results": [{"role": "mission", "status": "completed"},
                                     {"role": "evidence", "status": "completed", "evidence": {"status": "suspected_hazard"}},
                                     {"role": "report", "status": "completed"}],
                "actuation_enabled": False}
    monkeypatch.setattr(jev_cli, "_live_smoke_body", lambda args: response)
    output = tmp_path / "hazard-proof.json"
    assert jev_cli.main(live_args(output)) == 0
    assert json.loads(output.read_text())["task_outcome"] == "needs_review"


def test_fixture_failure_demo_still_has_successful_demo_exit(tmp_path):
    output = tmp_path / "fixture-failure.json"
    assert jev_cli.main(["demo", "--scenario", "network_failure", "--output", str(output)]) == 0
    assert json.loads(output.read_text())["task_outcome"] == "needs_review"
