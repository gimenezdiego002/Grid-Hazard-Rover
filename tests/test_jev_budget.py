"""Task cap uses temporary shared databases; no test touches live spending."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
import multiprocessing
from pathlib import Path
import threading

import pytest

from relay_gateway.integrations.ledger import (
    DispatchDenied, OperationConflict, SpendBudgetExceeded, SpendLedger,
)
from relay_gateway.jev_budget import JevTaskLedger, TASK_PREFIX


def facade(path):
    return JevTaskLedger.for_test(SpendLedger(path, history_path=None))


def _process_reservation(path, operation, provider, ready, gate, output):
    """Spawn-compatible worker with its own interpreter and DB connection."""
    ledger = facade(Path(path))
    ready.put(operation)
    if not gate.wait(10):
        output.put("start_timeout")
        return
    try:
        ticket = ledger.reserve(operation, provider, "0.30")
        output.put("created" if ticket.created else "duplicate")
    except SpendBudgetExceeded:
        output.put("refused")


def test_gemini_and_jev_share_task_cap_across_facade_restart(tmp_path):
    path = tmp_path / "spend.sqlite"
    first = facade(path)
    ticket = first.reserve("jev:first", "TypeSafe", "0.30")
    first.mark_dispatched(ticket)
    first.settle(ticket.operation_id, "0.03")
    restarted = facade(path)
    restarted.reserve("gemini:second", "Gemini", "0.46")
    with pytest.raises(SpendBudgetExceeded):
        restarted.reserve("jev:third", "TypeSafe", "0.010001")
    assert Decimal(restarted.task_snapshot()["committed_estimated_usd"]) == Decimal("0.49")
    assert len(restarted.snapshot()["operations"]) == 2


def test_reserved_dispatched_and_unknown_costs_all_survive_restart(tmp_path):
    path = tmp_path / "spend.sqlite"
    task = facade(path)
    task.reserve("reserved", "TypeSafe", "0.1")
    dispatched = task.reserve("dispatched", "Gemini", "0.1")
    task.mark_dispatched(dispatched)
    unknown = task.reserve("unknown", "TypeSafe", "0.1")
    task.mark_dispatched(unknown)
    task.mark_unknown(unknown.operation_id, reason="timeout")
    restarted = facade(path)
    restarted.reserve("remaining", "Gemini", "0.2")
    with pytest.raises(SpendBudgetExceeded):
        restarted.reserve("too-much", "TypeSafe", "0.000001")
    snapshot = restarted.snapshot()
    assert snapshot["unknown_reserved_usd"] == "0.100000"
    assert snapshot["reserved_usd"] == "0.500000"
    assert {row["status"] for row in snapshot["operations"]} == {"reserved", "dispatched", "unknown"}


def test_canonical_global_cap_remains_stricter_than_task_allowance(tmp_path):
    base = SpendLedger(tmp_path / "spend.sqlite", history_path=None)
    base.reserve("other-task:hosting", "Cloud", "14.80")
    task = JevTaskLedger.for_test(base)
    with pytest.raises(SpendBudgetExceeded):
        task.reserve("jev:first", "TypeSafe", "0.30")
    task.reserve("jev:first", "TypeSafe", "0.20")
    with pytest.raises(SpendBudgetExceeded):
        task.reserve("gemini:second", "Gemini", "0.000001")
    assert task.snapshot()["committed_estimated_usd"] == "15.000000"
    assert Decimal(task.task_snapshot()["committed_estimated_usd"]) == Decimal("0.20")


def test_simultaneous_provider_threads_cannot_oversubscribe_task_cap(tmp_path):
    path = tmp_path / "spend.sqlite"
    facade(path)
    barrier = threading.Barrier(2)

    def reserve(index):
        task = facade(path)
        barrier.wait(timeout=5)
        try:
            return task.reserve(f"operation-{index}", ("Gemini", "TypeSafe")[index], "0.30").created
        except SpendBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(reserve, range(2)))
    assert sorted(outcomes) == [False, True]
    assert Decimal(facade(path).task_snapshot()["committed_estimated_usd"]) == Decimal("0.30")


def test_simultaneous_processes_share_one_persistent_task_cap(tmp_path):
    path = tmp_path / "spend.sqlite"
    facade(path)
    context = multiprocessing.get_context("spawn")
    ready, output, gate = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(target=_process_reservation,
                 args=(str(path), f"process-{index}", provider, ready, gate, output))
                 for index, provider in enumerate(("Gemini", "TypeSafe"))]
    try:
        for process in processes:
            process.start()
        assert len({ready.get(timeout=15), ready.get(timeout=15)}) == 2
        gate.set()
        outcomes = sorted([output.get(timeout=15), output.get(timeout=15)])
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert outcomes == ["created", "refused"]
        assert Decimal(facade(path).task_snapshot()["committed_estimated_usd"]) == Decimal("0.30")
    finally:
        gate.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        ready.close()
        output.close()


def test_duplicate_reservation_never_creates_or_reuses_dispatch_claim(tmp_path):
    path = tmp_path / "spend.sqlite"
    task = facade(path)
    original = task.reserve("operation", "TypeSafe", "0.1")
    duplicate = facade(path).reserve("operation", "TypeSafe", "0.1")
    assert original.created and not duplicate.created
    assert original.operation_id == duplicate.operation_id
    assert original.operation_id.startswith(TASK_PREFIX)
    with pytest.raises(DispatchDenied):
        task.mark_dispatched(duplicate)
    task.mark_dispatched(original)
    with pytest.raises(DispatchDenied):
        task.mark_dispatched(original)
    assert task.snapshot()["reserved_usd"] == "0.100000"


def test_identical_operation_race_returns_exactly_one_owned_claim(tmp_path):
    path = tmp_path / "spend.sqlite"
    facade(path)
    barrier = threading.Barrier(2)

    def reserve(_):
        task = facade(path)
        barrier.wait(timeout=5)
        return task.reserve("same-operation", "Gemini", "0.40")

    with ThreadPoolExecutor(max_workers=2) as workers:
        tickets = list(workers.map(reserve, range(2)))
    assert sum(ticket.created for ticket in tickets) == 1
    assert facade(path).snapshot()["reserved_usd"] == "0.400000"


@pytest.mark.parametrize("provider,amount", [("Gemini", "0.1"), ("TypeSafe", "0.2")])
def test_duplicate_identity_cannot_change_provider_or_reservation(tmp_path, provider, amount):
    task = facade(tmp_path / "spend.sqlite")
    task.reserve("operation", "TypeSafe", "0.1")
    with pytest.raises(OperationConflict):
        task.reserve("operation", provider, amount)


def test_cancellation_releases_only_owned_undispatched_cost(tmp_path):
    task = facade(tmp_path / "spend.sqlite")
    cancelled = task.reserve("cancelled", "TypeSafe", "0.4")
    task.cancel_before_dispatch(cancelled)
    remaining = task.reserve("next", "Gemini", "0.5")
    task.mark_dispatched(remaining)
    with pytest.raises(DispatchDenied):
        task.cancel_before_dispatch(remaining)
    assert Decimal(task.task_snapshot()["committed_estimated_usd"]) == Decimal("0.50")


def test_verified_zero_settlement_frees_reservation_without_forgetting_operation(tmp_path):
    task = facade(tmp_path / "spend.sqlite")
    ticket = task.reserve("zero", "TypeSafe", "0.5")
    task.mark_dispatched(ticket)
    task.settle(ticket.operation_id, "0")
    task.reserve("next", "Gemini", "0.5")
    assert Decimal(task.task_snapshot()["committed_estimated_usd"]) == Decimal("0.50")
    assert len(task.snapshot()["operations"]) == 2


def test_incurred_overrun_is_recorded_and_blocks_future_requests(tmp_path):
    task = facade(tmp_path / "spend.sqlite")
    ticket = task.reserve("overrun", "TypeSafe", "0.1")
    task.mark_dispatched(ticket)
    task.settle(ticket.operation_id, "0.6")
    with pytest.raises(SpendBudgetExceeded):
        task.reserve("after-overrun", "Gemini", "0.000001")
    assert Decimal(task.task_snapshot()["committed_estimated_usd"]) == Decimal("0.60")
    assert Decimal(task.task_snapshot()["remaining_usd"]) == 0


@pytest.mark.parametrize("amount", [True, False, 0.1, "NaN", "Infinity", "-0.1", "not-money"])
def test_invalid_money_never_writes_a_reservation(tmp_path, amount):
    task = facade(tmp_path / "spend.sqlite")
    with pytest.raises((ValueError, InvalidOperation)):
        task.reserve("bad", "TypeSafe", amount)
    assert task.snapshot()["operations"] == []


def test_submicro_reservation_rounds_up_before_task_cap_check(tmp_path):
    task = facade(tmp_path / "spend.sqlite")
    task.reserve("all-but-micro", "Gemini", "0.499999")
    ticket = task.reserve("submicro", "TypeSafe", "0.000000001")
    assert ticket.reserved_usd == "0.000001"
    with pytest.raises(SpendBudgetExceeded):
        task.reserve("extra", "TypeSafe", "0.000000001")


def test_validation_failure_releases_the_task_lock(tmp_path):
    task = facade(tmp_path / "spend.sqlite")
    with pytest.raises(ValueError):
        task.reserve("bad", "", "0.1")
    assert task.reserve("good", "TypeSafe", "0.1").created
