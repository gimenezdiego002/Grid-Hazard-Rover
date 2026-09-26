from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import sqlite3
from threading import Barrier
import time

import pytest

import relay_gateway.integrations.ledger as ledger_module
from relay_gateway.integrations.ledger import (
    DispatchDenied, HistoryImportError, LedgerBusy, OperationConflict,
    SettlementConflict, SpendBudgetExceeded, SpendLedger,
)


def history_file(tmp_path, *, settled="0.000179", unresolved="0.000000", entries=None):
    history = {"currency": "USD", "authorization_total": "20.00", "planned_ceiling": "15.00",
               "estimated_new_usage_usd": settled, "unresolved_reservations": unresolved,
               "entries": entries if entries is not None else [
                   {"id": "gemini-smoke", "provider": "Gemini", "reserved_usd": "0.01",
                    "settled_estimated_usd": settled, "status": "completed_provider_usage_recorded"}]}
    path = tmp_path / "history.json"
    path.write_text(json.dumps(history), encoding="utf-8")
    return path


@pytest.fixture
def ledger(tmp_path):
    return SpendLedger(tmp_path / "spend.sqlite", history_path=history_file(tmp_path))


def test_import_history_once_survives_changed_or_missing_source(ledger, tmp_path):
    first = ledger.snapshot()
    assert first["settled_estimated_usd"] == "0.000179"
    assert first["remaining_planned_usd"] == "14.999821"
    path = tmp_path / "history.json"
    path.write_text("invalid later file", encoding="utf-8")
    assert ledger.import_history_once(path) is False
    path.unlink()
    reopened = SpendLedger(ledger.path, history_path=path)
    assert len(reopened.snapshot()["operations"]) == 1
    assert reopened.snapshot()["settled_estimated_usd"] == "0.000179"


def test_default_history_format_matches_existing_setup_record(tmp_path):
    # This reads only the documented spending record; no credentials or live SDKs.
    ledger = SpendLedger(tmp_path / "spend.sqlite", history_path="docs/setup-spend.json")
    snapshot = ledger.snapshot()
    assert snapshot["history_imported"]
    assert Decimal(snapshot["settled_estimated_usd"]) >= Decimal("0.000179")
    assert snapshot["actual_billed_usd"] is None


def test_reserve_dispatch_settle_releases_unused_reservation(ledger):
    ticket = ledger.reserve("speech-1", "ElevenLabs", "1.00")
    assert ticket.created and ticket.claim_token
    assert "claim_token" not in repr(ticket)
    assert ledger.snapshot()["reserved_usd"] == "1.000000"
    ledger.mark_dispatched(ticket)
    settled = ledger.settle("speech-1", "0.25")
    assert settled["status"] == "settled"
    snapshot = ledger.snapshot()
    assert snapshot["reserved_usd"] == "0.000000"
    assert snapshot["settled_estimated_usd"] == "0.250179"
    assert snapshot["remaining_planned_usd"] == "14.749821"


def test_concurrent_duplicate_operation_has_one_dispatch_owner(ledger):
    barrier = Barrier(8)

    def compete(_):
        caller = SpendLedger(ledger.path, history_path=None)
        barrier.wait(timeout=5)
        ticket = caller.reserve("same-op", "Gemini", "0.01")
        try:
            caller.mark_dispatched(ticket)
            return "dispatch"
        except DispatchDenied:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(compete, range(8)))
    assert outcomes.count("dispatch") == 1
    assert outcomes.count("duplicate") == 7
    assert ledger.snapshot()["reserved_usd"] == "0.010000"


def test_concurrent_aggregate_admission_across_providers_and_mission_ids(ledger):
    barrier = Barrier(6)

    def compete(identity):
        caller = SpendLedger(ledger.path, history_path=None)
        barrier.wait(timeout=5)
        try:
            caller.reserve(f"mission-{identity}", f"provider-{identity}", "4.00")
            return "reserved"
        except SpendBudgetExceeded:
            return "denied"

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(compete, range(6)))
    assert outcomes.count("reserved") == 3
    assert outcomes.count("denied") == 3
    assert ledger.snapshot()["committed_estimated_usd"] == "12.000179"


def test_replayed_reservation_cannot_dispatch_or_change_its_parameters(ledger):
    first = ledger.reserve("same-op", "Gemini", "0.01")
    duplicate = ledger.reserve("same-op", "Gemini", Decimal("0.010000"))
    assert not duplicate.created and duplicate.claim_token is None
    with pytest.raises(DispatchDenied):
        ledger.mark_dispatched(duplicate)
    with pytest.raises(OperationConflict):
        ledger.reserve("same-op", "Gemini", "0.02")
    with pytest.raises(OperationConflict):
        ledger.reserve("same-op", "Snowflake", "0.01")
    ledger.mark_dispatched(first)
    with pytest.raises(DispatchDenied):
        ledger.mark_dispatched(first)


def test_unknown_and_dispatched_reservations_never_expire_on_restart(ledger):
    first = ledger.reserve("timed-out", "ElevenLabs", "3.00")
    second = ledger.reserve("process-ended", "Google Cloud", "3.00")
    ledger.mark_dispatched(first)
    ledger.mark_unknown(first.operation_id, reason="timeout")
    ledger.mark_dispatched(second)
    reopened = SpendLedger(ledger.path, history_path=None)
    assert reopened.snapshot()["unknown_reserved_usd"] == "3.000000"
    assert reopened.snapshot()["reserved_usd"] == "6.000000"
    with pytest.raises(SpendBudgetExceeded):
        reopened.reserve("next", "Snowflake", "9.00")
    duplicate = reopened.reserve("process-ended", "Google Cloud", "3.00")
    with pytest.raises(DispatchDenied):
        reopened.mark_dispatched(duplicate)
    reopened.settle("timed-out", "0.20")
    assert reopened.snapshot()["reserved_usd"] == "3.000000"
    assert reopened.snapshot()["settled_estimated_usd"] == "0.200179"


def test_cancellation_only_before_owned_known_undispatched_attempt(ledger):
    ticket = ledger.reserve("cancel-me", "Gemini", "2")
    duplicate = ledger.reserve("cancel-me", "Gemini", "2")
    with pytest.raises(DispatchDenied):
        ledger.cancel_before_dispatch(duplicate)
    ledger.cancel_before_dispatch(ticket)
    assert ledger.snapshot()["reserved_usd"] == "0.000000"
    with pytest.raises(DispatchDenied):
        ledger.mark_dispatched(ticket)
    next_ticket = ledger.reserve("cannot-cancel", "Gemini", "2")
    ledger.mark_dispatched(next_ticket)
    with pytest.raises(DispatchDenied):
        ledger.cancel_before_dispatch(next_ticket)
    assert ledger.snapshot()["reserved_usd"] == "2.000000"


def test_settlement_is_idempotent_but_conflicting_rewrites_are_refused(ledger):
    ticket = ledger.reserve("settle-me", "Gemini", "1")
    with pytest.raises(SettlementConflict):
        ledger.settle(ticket.operation_id, "0.1")
    ledger.mark_dispatched(ticket)
    first = ledger.settle(ticket.operation_id, "0.1")
    assert ledger.settle(ticket.operation_id, Decimal("0.100000")) == first
    with pytest.raises(SettlementConflict):
        ledger.settle(ticket.operation_id, "0.2")
    with pytest.raises(SettlementConflict):
        ledger.mark_unknown(ticket.operation_id)
    assert ledger.snapshot()["settled_estimated_usd"] == "0.100179"


def test_actual_overrun_is_recorded_and_further_work_denied(ledger):
    ticket = ledger.reserve("provider-overrun", "Google Cloud", "1.00")
    ledger.mark_dispatched(ticket)
    row = ledger.settle(ticket.operation_id, "20.50")
    assert row["reservation_overrun_usd"] == "19.500000"
    snapshot = ledger.snapshot()
    assert snapshot["committed_estimated_usd"] == "20.500179"
    assert snapshot["remaining_planned_usd"] == "0.000000"
    assert snapshot["planned_overrun_usd"] == "5.500179"
    assert snapshot["authorization_overrun_usd"] == "0.500179"
    with pytest.raises(SpendBudgetExceeded):
        ledger.reserve("blocked", "Gemini", "0.000001")


@pytest.mark.parametrize("value", [0.01, True, "NaN", "Infinity", "-1"])
def test_non_decimal_invalid_or_negative_amounts_rejected(ledger, value):
    with pytest.raises(ValueError):
        ledger.reserve("invalid", "Gemini", value)


def test_sub_micro_estimates_round_up_and_are_stored_as_integers(ledger):
    ticket = ledger.reserve("tiny", "Gemini", "0.0000001")
    assert ticket.reserved_usd == "0.000001"
    ledger.mark_dispatched(ticket)
    ledger.settle("tiny", "0.00000001")
    with sqlite3.connect(ledger.path) as db:
        stored = db.execute("SELECT settled_micros,typeof(settled_micros) FROM spend_operations WHERE operation_id='tiny'").fetchone()
    assert stored == (1, "integer")


def test_lock_deadline_fails_without_reservation_or_dispatch(ledger):
    bounded = SpendLedger(ledger.path, history_path=None, lock_timeout_ms=30)
    connection = sqlite3.connect(ledger.path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(LedgerBusy):
            bounded.reserve("locked-op", "Gemini", "0.1")
        assert time.monotonic() - started < 1
    finally:
        connection.rollback()
        connection.close()
    assert all(row["operation_id"] != "locked-op" for row in ledger.snapshot()["operations"])


def test_inconsistent_history_fails_closed_without_partial_import(tmp_path):
    path = history_file(tmp_path, settled="1", entries=[
        {"id": "one", "provider": "Gemini", "reserved_usd": "0.1", "settled_estimated_usd": "0.1"}])
    with pytest.raises(HistoryImportError):
        SpendLedger(tmp_path / "spend.sqlite", history_path=path)
    ledger = SpendLedger(tmp_path / "spend.sqlite", history_path=None)
    assert ledger.snapshot()["operations"] == []
    assert ledger.snapshot()["history_imported"] is False


def test_history_import_rolls_back_prior_inserts_on_id_collision(tmp_path):
    ledger = SpendLedger(tmp_path / "spend.sqlite", history_path=None)
    ledger.reserve("collision", "Gemini", "0.1")
    path = history_file(tmp_path, settled="0.2", entries=[
        {"id": "would-be-imported", "provider": "Gemini", "settled_estimated_usd": "0.1"},
        {"id": "collision", "provider": "Gemini", "settled_estimated_usd": "0.1"}])
    with pytest.raises(HistoryImportError):
        ledger.import_history_once(path)
    assert [row["operation_id"] for row in ledger.snapshot()["operations"]] == ["collision"]
    assert ledger.snapshot()["history_imported"] is False


def test_unresolved_historical_reservations_consume_allowance(tmp_path):
    path = history_file(tmp_path, settled="0", unresolved="14", entries=[
        {"id": "old-uncertain", "provider": "Google Cloud", "reserved_usd": "14", "status": "unknown"}])
    ledger = SpendLedger(tmp_path / "spend.sqlite", history_path=path)
    assert ledger.snapshot()["unknown_reserved_usd"] == "14.000000"
    with pytest.raises(SpendBudgetExceeded):
        ledger.reserve("next", "Gemini", "1.000001")


def reviewed_workspace(tmp_path, monkeypatch):
    root = tmp_path / "reviewed-workspace"
    (root / "docs").mkdir(parents=True)
    (root / "AGENTS.md").write_text("Reviewed test workspace", encoding="utf-8")
    (root / "docs" / "budget-policy.md").write_text("USD 15 planned / 20 total", encoding="utf-8")
    history = history_file(root)
    (root / "docs" / "setup-spend.json").write_bytes(history.read_bytes())
    monkeypatch.setattr(ledger_module, "_PROJECT_ROOT", root)
    return root


def test_default_ledger_and_history_ignore_launch_directory(tmp_path, monkeypatch):
    root = reviewed_workspace(tmp_path, monkeypatch)
    # First-time initialization is an explicit reviewed migration, not default
    # behavior available to every new clone.
    SpendLedger(root / ".state" / "spend.sqlite", history_path=root / "docs" / "setup-spend.json")
    first_cwd, second_cwd = tmp_path / "first", tmp_path / "second"
    first_cwd.mkdir()
    second_cwd.mkdir()
    # A copied, zero-cost historical record in cwd cannot grant a fresh allowance.
    (second_cwd / "docs").mkdir()
    (second_cwd / "docs" / "setup-spend.json").write_bytes(
        history_file(second_cwd, settled="0").read_bytes())
    monkeypatch.chdir(first_cwd)
    first = SpendLedger()
    ticket = first.reserve("cloud-running", "Google Cloud", "14")
    first.mark_dispatched(ticket)
    monkeypatch.chdir(second_cwd)
    reopened = SpendLedger()
    assert reopened.path == first.path == root / ".state" / "spend.sqlite"
    assert reopened.snapshot()["committed_estimated_usd"] == "14.000179"
    with pytest.raises(SpendBudgetExceeded):
        reopened.reserve("new-mission", "Gemini", "1")
    assert not (first_cwd / ".state").exists()
    assert not (second_cwd / ".state").exists()


@pytest.mark.parametrize("missing", ["AGENTS.md", "docs/budget-policy.md", "docs/setup-spend.json"])
def test_default_ledger_refuses_unreviewed_or_packaged_workspace(tmp_path, monkeypatch, missing):
    root = reviewed_workspace(tmp_path, monkeypatch)
    (root / missing).unlink()
    with pytest.raises(HistoryImportError, match="reviewed source workspace"):
        SpendLedger()
    assert not (root / ".state").exists()


def test_default_ledger_cannot_disable_historical_import(tmp_path, monkeypatch):
    root = reviewed_workspace(tmp_path, monkeypatch)
    with pytest.raises(HistoryImportError, match="cannot bypass"):
        SpendLedger(history_path=None)
    assert not (root / ".state").exists()


def test_default_missing_canonical_ledger_does_not_create_state_or_import(tmp_path, monkeypatch):
    root = reviewed_workspace(tmp_path, monkeypatch)
    with pytest.raises(HistoryImportError, match="fresh clones remain mock-only"):
        SpendLedger()
    assert not (root / ".state").exists()


@pytest.mark.parametrize("contents", [b"", b"not a sqlite database"])
def test_default_empty_or_invalid_file_is_unchanged_after_refusal(tmp_path, monkeypatch, contents):
    root = reviewed_workspace(tmp_path, monkeypatch)
    path = root / ".state" / "spend.sqlite"
    path.parent.mkdir()
    path.write_bytes(contents)
    before = {file.name: file.read_bytes() for file in path.parent.iterdir()}
    with pytest.raises(HistoryImportError, match="already be initialized"):
        SpendLedger()
    assert {file.name: file.read_bytes() for file in path.parent.iterdir()} == before


def test_default_unrelated_sqlite_database_is_not_initialized(tmp_path, monkeypatch):
    root = reviewed_workspace(tmp_path, monkeypatch)
    path = root / ".state" / "spend.sqlite"
    path.parent.mkdir()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
        db.execute("INSERT INTO unrelated VALUES ('preserve')")
    before = path.read_bytes()
    with pytest.raises(HistoryImportError, match="already be initialized"):
        SpendLedger()
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("unrelated",)]


def test_default_initialized_but_unimported_ledger_cannot_bootstrap_history(tmp_path, monkeypatch):
    root = reviewed_workspace(tmp_path, monkeypatch)
    explicit = SpendLedger(root / ".state" / "spend.sqlite", history_path=None)
    ticket = explicit.reserve("already-running", "Cloud", "3")
    explicit.mark_dispatched(ticket)
    before = explicit.path.read_bytes()
    with pytest.raises(HistoryImportError, match="already be initialized"):
        SpendLedger()
    assert explicit.path.read_bytes() == before
    assert not explicit.snapshot()["history_imported"]
    assert explicit.snapshot()["reserved_usd"] == "3.000000"


@pytest.mark.parametrize("mutation", [
    "UPDATE ledger_meta SET value='2' WHERE key='schema_version'",
    "UPDATE ledger_meta SET value='{}' WHERE key='history_import'",
    "DELETE FROM spend_operations WHERE imported=1",
    "ALTER TABLE spend_operations RENAME COLUMN reserved_micros TO wrong_column",
])
def test_default_rejects_inconsistent_schema_or_marker_without_repair(tmp_path, monkeypatch, mutation):
    root = reviewed_workspace(tmp_path, monkeypatch)
    explicit = SpendLedger(root / ".state" / "spend.sqlite", history_path=root / "docs" / "setup-spend.json")
    with sqlite3.connect(explicit.path) as db:
        db.execute(mutation)
    before = explicit.path.read_bytes()
    with pytest.raises(HistoryImportError, match="already be initialized"):
        SpendLedger()
    assert explicit.path.read_bytes() == before


def test_default_reopen_is_read_only_and_preserves_newer_costs(tmp_path, monkeypatch):
    root = reviewed_workspace(tmp_path, monkeypatch)
    explicit = SpendLedger(root / ".state" / "spend.sqlite", history_path=root / "docs" / "setup-spend.json")
    cloud = explicit.reserve("running-cloud", "Cloud", "3")
    explicit.mark_dispatched(cloud)
    model = explicit.reserve("later-model", "Gemini", "0.01")
    explicit.mark_dispatched(model)
    explicit.settle(model.operation_id, "0.000257")
    snapshot = explicit.snapshot()
    before = explicit.path.read_bytes()
    # The stale history need not be readable; default reopening may not import,
    # initialize, repair or otherwise perform a write.
    (root / "docs" / "setup-spend.json").write_text("invalid stale history", encoding="utf-8")
    def forbidden(*args, **kwargs):
        raise AssertionError("Default reopening must not enter write/bootstrap methods")
    monkeypatch.setattr(SpendLedger, "_initialize", forbidden)
    monkeypatch.setattr(SpendLedger, "import_history_once", forbidden)
    reopened = SpendLedger()
    assert reopened.path.read_bytes() == before
    assert reopened.snapshot() == snapshot
    assert reopened.snapshot()["committed_estimated_usd"] == "3.000436"
