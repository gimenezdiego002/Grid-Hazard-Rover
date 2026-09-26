"""Task-specific $0.50 admission layered over the one canonical spending ledger."""

from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
import hashlib
import os
from pathlib import Path
import threading
import time

from .integrations.ledger import LedgerBusy, SpendBudgetExceeded, SpendLedger


TASK_PREFIX = "jev-integration-v1:"
TASK_CAP_USD = Decimal("0.50")
_THREAD_LOCK = threading.Lock()


class JevTaskLedger:
    """Persistent combined Gemini/Jev task cap; never a new spending allowance.

    A separate advisory lock serializes this facade's snapshot+reserve across
    processes. The existing ledger still atomically admits *all* providers into
    the shared $15 envelope. No independent copy or fresh live DB is created.
    Keep the lock file; unlinking it while callers run defeats serialization.
    """

    def __init__(self):
        self._ledger = SpendLedger()
        self.is_canonical = True
        self._lock_path = self._ledger.path.parent / "jev-task.lock"

    @classmethod
    def for_test(cls, ledger: SpendLedger):
        instance = cls.__new__(cls)
        instance._ledger = ledger
        instance.is_canonical = False
        instance._lock_path = ledger.path.with_suffix(".jev-test.lock")
        return instance

    @staticmethod
    def _operation(operation_id):
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 200:
            raise ValueError("A bounded operation ID is required")
        if operation_id.startswith(TASK_PREFIX):
            return operation_id
        return TASK_PREFIX + hashlib.sha256(operation_id.encode()).hexdigest()

    @contextmanager
    def _lock(self):
        if not _THREAD_LOCK.acquire(timeout=5):
            raise LedgerBusy("Jev task admission is busy")
        descriptor = None
        locked = False
        try:
            descriptor = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            until = time.monotonic() + 5
            while True:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() >= until:
                        raise LedgerBusy("Jev task admission is busy") from None
                    time.sleep(0.01)
            yield
        finally:
            if descriptor is not None:
                if locked:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            _THREAD_LOCK.release()

    def reserve(self, operation_id, provider, maximum_usd):
        if isinstance(maximum_usd, bool) or not isinstance(maximum_usd, (str, Decimal, int)):
            raise ValueError("Use decimal money")
        amount = Decimal(maximum_usd)
        if not amount.is_finite() or amount < 0:
            raise ValueError("Use nonnegative finite money")
        amount = amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
        operation = self._operation(operation_id)
        with self._lock():
            rows = self._ledger.snapshot()["operations"]
            # Identical existing reservations still flow through canonical
            # idempotency/claim validation, never gain another dispatch claim.
            if not any(row["operation_id"] == operation for row in rows):
                committed = sum((Decimal(row["settled_estimated_usd"] or row["reserved_usd"])
                                 for row in rows if row["operation_id"].startswith(TASK_PREFIX)
                                 and row["status"] != "cancelled"), Decimal(0))
                if committed + amount > TASK_CAP_USD:
                    raise SpendBudgetExceeded("Combined Jev integration task cap exhausted")
            return self._ledger.reserve(operation, provider, amount)

    def mark_dispatched(self, ticket):
        with self._lock():
            return self._ledger.mark_dispatched(ticket)

    def cancel_before_dispatch(self, ticket):
        with self._lock():
            return self._ledger.cancel_before_dispatch(ticket)

    def settle(self, operation_id, amount):
        with self._lock():
            return self._ledger.settle(self._operation(operation_id), amount)

    def mark_unknown(self, operation_id, *, reason="unclassified"):
        with self._lock():
            return self._ledger.mark_unknown(self._operation(operation_id), reason=reason)

    def snapshot(self):
        return self._ledger.snapshot()

    def task_snapshot(self):
        rows = [row for row in self.snapshot()["operations"] if row["operation_id"].startswith(TASK_PREFIX)]
        committed = sum((Decimal(row["settled_estimated_usd"] or row["reserved_usd"])
                         for row in rows if row["status"] != "cancelled"), Decimal(0))
        return {"task_cap_usd": str(TASK_CAP_USD), "committed_estimated_usd": str(committed),
                "remaining_usd": str(max(Decimal(0), TASK_CAP_USD - committed)), "operations": rows}
