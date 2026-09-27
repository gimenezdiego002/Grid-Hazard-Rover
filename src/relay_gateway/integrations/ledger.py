"""Durable admission across providers, without claiming to enforce their invoices.

Every operation opens its own SQLite connection. BEGIN IMMEDIATE serializes
reservations across local threads/processes. Reservations never expire: uncertain
external work continues consuming allowance until explicitly reconciled.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from uuid import uuid4


_MICROS = Decimal(1_000_000)
_PLANNED = 15_000_000
_AUTHORIZED = 20_000_000
_MAX_INTEGER = 9_223_372_036_854_775_807
_LIVE_STATES = ("reserved", "dispatched", "unknown")
# An editable installation resolves to this checkout regardless of launch cwd.
# A normal wheel has no reviewed workspace/history and must fail closed by default.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_HISTORY = Path("docs/setup-spend.json")


class SpendBudgetExceeded(RuntimeError):
    """A new reservation cannot fit the remaining planned allowance."""


class OperationConflict(RuntimeError):
    """An operation ID was reused for a different provider or maximum."""


class DispatchDenied(RuntimeError):
    """Only the first reservation owner may dispatch, exactly once."""


class SettlementConflict(RuntimeError):
    """Settlement conflicts with an operation's durable state or prior amount."""


class HistoryImportError(RuntimeError):
    """Historical totals are missing, inconsistent, or would be duplicated."""


class LedgerBusy(RuntimeError):
    """The bounded SQLite lock deadline expired; do not dispatch."""


def _units(value: str | Decimal | int) -> int:
    """Round sub-micro-dollar estimates upward, never via binary floats."""
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise ValueError("USD amounts must be Decimal, string or integer; floats are forbidden")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid USD amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("USD amount must be finite and nonnegative")
    units = int((amount * _MICROS).to_integral_value(rounding=ROUND_CEILING))
    if units > _MAX_INTEGER:
        raise ValueError("USD amount is outside ledger integer range")
    return units


def _usd(units: int) -> str:
    return f"{Decimal(units) / _MICROS:.6f}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{name} must be a nonempty string of at most 200 characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} cannot contain control characters")
    return value


@dataclass(frozen=True)
class Reservation:
    operation_id: str
    provider: str
    reserved_usd: str
    status: str
    created: bool
    claim_token: str | None = field(default=None, repr=False)


class SpendLedger:
    """Local aggregate USD ledger: $15 planned out of $20 authorized.

    Use one canonical durable path across all live callers. A different path is
    a different ledger, not a fresh spending authorization. Deleting/replacing
    the database loses enforcement history; it is not a provider billing cap.
    """

    def __init__(self, path: str | Path | None = None, *,
                 history_path: str | Path | None = _DEFAULT_HISTORY,
                 lock_timeout_ms: int = 5000):
        if type(lock_timeout_ms) is not int or not 1 <= lock_timeout_ms <= 30_000:
            raise ValueError("lock_timeout_ms must be between 1 and 30000")
        if path is None:
            required = ("AGENTS.md", "docs/budget-policy.md", "docs/setup-spend.json")
            if not all((_PROJECT_ROOT / name).is_file() for name in required):
                raise HistoryImportError(
                    "Default spending ledger requires the reviewed source workspace and historical record; "
                    "packaged/cloud live callers need an explicitly reviewed shared durable ledger")
            if history_path is not _DEFAULT_HISTORY:
                raise HistoryImportError("Default spending ledger cannot bypass its canonical historical record")
            self.path = (_PROJECT_ROOT / ".state" / "spend.sqlite").resolve()
            self.lock_timeout_ms = lock_timeout_ms
            self._validate_existing_default()
            # Reopening the canonical ledger is read-only. In particular, never
            # bootstrap a fresh clone from the stale, one-time setup snapshot.
            return
        if history_path is _DEFAULT_HISTORY:
            history_path = _PROJECT_ROOT / _DEFAULT_HISTORY
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_timeout_ms = lock_timeout_ms
        self._initialize()
        if history_path is not None:
            self.import_history_once(history_path)

    def _validate_existing_default(self):
        """Require an initialized ledger without creating files or importing.

        Explicit-path construction remains available for reviewed migration and
        isolated tests. Its existence is not permission for another allowance.
        """
        expected_columns = {
            "ledger_meta": [("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0)],
            "spend_operations": [
                ("operation_id", "TEXT", 0, 1), ("provider", "TEXT", 1, 0),
                ("reserved_micros", "INTEGER", 1, 0), ("settled_micros", "INTEGER", 0, 0),
                ("status", "TEXT", 1, 0), ("claim_hash", "TEXT", 0, 0),
                ("created_at", "TEXT", 1, 0), ("updated_at", "TEXT", 1, 0),
                ("unknown_reason", "TEXT", 0, 0), ("imported", "INTEGER", 1, 0)],
        }
        connection = None
        try:
            if not self.path.is_file() or self.path.stat().st_size == 0:
                raise ValueError("Missing initialized ledger")
            connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True,
                                         timeout=self.lock_timeout_ms / 1000, isolation_level=None)
            connection.execute("BEGIN")
            for table, expected in expected_columns.items():
                kind = connection.execute("SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
                if kind != ("table",):
                    raise ValueError("Missing ledger table")
                columns = [(row[1], row[2].upper(), row[3], row[5])
                           for row in connection.execute(f"PRAGMA table_info({table})")]
                if columns != expected:
                    raise ValueError("Ledger schema mismatch")
            metadata = dict(connection.execute("SELECT key,value FROM ledger_meta"))
            expected = {"schema_version": "1", "currency": "USD", "planned_micros": str(_PLANNED),
                        "authorized_micros": str(_AUTHORIZED)}
            if any(metadata.get(key) != value for key, value in expected.items()):
                raise ValueError("Ledger configuration mismatch")
            marker = json.loads(metadata.get("history_import", "null"))
            if (not isinstance(marker, dict)
                    or not isinstance(marker.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", marker["sha256"])
                    or not isinstance(marker.get("imported_at"), str) or not marker["imported_at"]
                    or not isinstance(marker.get("source_name"), str) or not marker["source_name"]
                    or type(marker.get("operation_count")) is not int or marker["operation_count"] < 0):
                raise ValueError("Missing complete history marker")
            imported_count = connection.execute("SELECT COUNT(*) FROM spend_operations WHERE imported=1").fetchone()[0]
            if imported_count != marker["operation_count"]:
                raise ValueError("Imported history no longer matches its marker")
        except (OSError, ValueError, TypeError, sqlite3.Error):
            raise HistoryImportError(
                "Default spending ledger must already be initialized at the canonical workspace path; "
                "fresh clones remain mock-only until the authorized cumulative ledger is restored or shared. "
                "The historical setup snapshot cannot initialize a new allowance.") from None
        finally:
            if connection is not None:
                connection.close()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=self.lock_timeout_ms / 1000,
                                     isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.lock_timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _transaction(self, *, write=True):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.OperationalError as error:
            connection.rollback()
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                raise LedgerBusy("Spending ledger is busy; no external call is authorized") from None
            raise
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS ledger_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS spend_operations (
                operation_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                reserved_micros INTEGER NOT NULL CHECK(reserved_micros >= 0),
                settled_micros INTEGER CHECK(settled_micros IS NULL OR settled_micros >= 0),
                status TEXT NOT NULL CHECK(status IN ('reserved','dispatched','unknown','settled','cancelled')),
                claim_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                unknown_reason TEXT,
                imported INTEGER NOT NULL DEFAULT 0 CHECK(imported IN (0,1))
            )""")
            expected = {"schema_version": "1", "currency": "USD", "planned_micros": str(_PLANNED),
                        "authorized_micros": str(_AUTHORIZED)}
            for key, value in expected.items():
                db.execute("INSERT OR IGNORE INTO ledger_meta(key,value) VALUES (?,?)", (key, value))
                stored = db.execute("SELECT value FROM ledger_meta WHERE key=?", (key,)).fetchone()[0]
                if stored != value:
                    raise ValueError("Ledger schema/currency/authorization differs from reviewed configuration")

    @staticmethod
    def _totals(db):
        rows = db.execute("SELECT reserved_micros,settled_micros,status FROM spend_operations").fetchall()
        # Python integer accumulation avoids SQLite SUM overflow for extreme reports.
        settled = sum(row["settled_micros"] or 0 for row in rows if row["status"] == "settled")
        reserved = sum(row["reserved_micros"] for row in rows if row["status"] in _LIVE_STATES)
        unknown = sum(row["reserved_micros"] for row in rows if row["status"] == "unknown")
        return settled, reserved, unknown

    @staticmethod
    def _ticket(row, *, created=False, claim_token=None):
        return Reservation(operation_id=row["operation_id"], provider=row["provider"],
                           reserved_usd=_usd(row["reserved_micros"]), status=row["status"],
                           created=created, claim_token=claim_token)

    def reserve(self, operation_id: str, provider: str, maximum_usd: str | Decimal | int) -> Reservation:
        operation_id = _identifier(operation_id, "operation_id")
        provider = _identifier(provider, "provider")
        requested = _units(maximum_usd)
        with self._transaction() as db:
            old = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if old is not None:
                if old["provider"] != provider or old["reserved_micros"] != requested:
                    raise OperationConflict("Operation ID is already bound to a different provider or maximum")
                return self._ticket(old)
            settled, reserved, _ = self._totals(db)
            if settled + reserved + requested > _PLANNED:
                raise SpendBudgetExceeded(
                    f"USD reservation {_usd(requested)} exceeds remaining planned allowance "
                    f"{_usd(max(0, _PLANNED - settled - reserved))}")
            claim = uuid4().hex
            now = _now()
            db.execute("""INSERT INTO spend_operations
                          (operation_id,provider,reserved_micros,status,claim_hash,created_at,updated_at)
                          VALUES (?,?,?,'reserved',?,?,?)""",
                       (operation_id, provider, requested, hashlib.sha256(claim.encode()).hexdigest(), now, now))
            row = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (operation_id,)).fetchone()
            return self._ticket(row, created=True, claim_token=claim)

    @staticmethod
    def _owned_undispatched(db, ticket: Reservation):
        if not isinstance(ticket, Reservation) or not ticket.created or not ticket.claim_token:
            raise DispatchDenied("Reservation is a duplicate or has no dispatch claim")
        row = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (ticket.operation_id,)).fetchone()
        expected = hashlib.sha256(ticket.claim_token.encode()).hexdigest()
        if row is None or row["status"] != "reserved" or row["claim_hash"] != expected:
            raise DispatchDenied("Dispatch claim was consumed, cancelled, or is not owned by this caller")
        return row

    def mark_dispatched(self, ticket: Reservation) -> Reservation:
        """Must succeed immediately before the single outbound attempt."""
        with self._transaction() as db:
            self._owned_undispatched(db, ticket)
            db.execute("UPDATE spend_operations SET status='dispatched',claim_hash=NULL,updated_at=? WHERE operation_id=?",
                       (_now(), ticket.operation_id))
            row = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (ticket.operation_id,)).fetchone()
            return self._ticket(row)

    def cancel_before_dispatch(self, ticket: Reservation) -> Reservation:
        """Release only an owned reservation whose outbound attempt never started."""
        with self._transaction() as db:
            self._owned_undispatched(db, ticket)
            db.execute("UPDATE spend_operations SET status='cancelled',claim_hash=NULL,updated_at=? WHERE operation_id=?",
                       (_now(), ticket.operation_id))
            row = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (ticket.operation_id,)).fetchone()
            return self._ticket(row)

    def mark_unknown(self, operation_id: str, *, reason: str = "unclassified") -> Reservation:
        allowed = {"unclassified", "timeout", "connection_lost", "missing_usage", "provider_pending", "process_restart"}
        if reason not in allowed:
            raise ValueError("Unknown reason must be a fixed non-sensitive category")
        with self._transaction() as db:
            row = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None or row["status"] not in {"dispatched", "unknown"}:
                raise SettlementConflict("Only dispatched or already unknown work can remain unresolved")
            db.execute("UPDATE spend_operations SET status='unknown',unknown_reason=?,updated_at=? WHERE operation_id=?",
                       (reason, _now(), operation_id))
            row = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (operation_id,)).fetchone()
            return self._ticket(row)

    def settle(self, operation_id: str, actual_estimated_usd: str | Decimal | int) -> dict[str, Any]:
        """Reconcile observed usage; record even an overrun that already occurred.

        The amount remains an estimate, not an invoice. Repeating exactly the
        same settled amount is idempotent; changing it needs explicit reconciliation.
        """
        actual = _units(actual_estimated_usd)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise SettlementConflict("Unknown operation")
            if row["status"] == "settled":
                if row["settled_micros"] != actual:
                    raise SettlementConflict("Operation already settled at a different amount")
            elif row["status"] in {"dispatched", "unknown"}:
                db.execute("UPDATE spend_operations SET status='settled',settled_micros=?,claim_hash=NULL,updated_at=? WHERE operation_id=?",
                           (actual, _now(), operation_id))
            else:
                raise SettlementConflict("Only dispatched or unknown work can settle")
            row = db.execute("SELECT * FROM spend_operations WHERE operation_id=?", (operation_id,)).fetchone()
            return self._public_row(row)

    @staticmethod
    def _public_row(row):
        actual = row["settled_micros"]
        return {"operation_id": row["operation_id"], "provider": row["provider"],
                "status": row["status"], "reserved_usd": _usd(row["reserved_micros"]),
                "settled_estimated_usd": _usd(actual) if actual is not None else None,
                "actual_billed_usd": None, "created_at": row["created_at"],
                "updated_at": row["updated_at"], "unknown_reason": row["unknown_reason"],
                "reservation_overrun_usd": _usd(max(0, (actual or 0) - row["reserved_micros"])),
                "historical_import": bool(row["imported"])}

    def snapshot(self) -> dict[str, Any]:
        with self._transaction(write=False) as db:
            settled, reserved, unknown = self._totals(db)
            rows = db.execute("SELECT * FROM spend_operations ORDER BY created_at,operation_id").fetchall()
            imported = db.execute("SELECT value FROM ledger_meta WHERE key='history_import'").fetchone()
            committed = settled + reserved
            return {"currency": "USD", "planned_ceiling_usd": _usd(_PLANNED),
                    "authorization_total_usd": _usd(_AUTHORIZED), "held_contingency_usd": "5.000000",
                    "settled_estimated_usd": _usd(settled), "reserved_usd": _usd(reserved),
                    "unknown_reserved_usd": _usd(unknown), "committed_estimated_usd": _usd(committed),
                    "remaining_planned_usd": _usd(max(0, _PLANNED - committed)),
                    "planned_overrun_usd": _usd(max(0, committed - _PLANNED)),
                    "authorization_overrun_usd": _usd(max(0, committed - _AUTHORIZED)),
                    "actual_billed_usd": None, "history_imported": imported is not None,
                    "operations": [self._public_row(row) for row in rows],
                    "limitation": "Local application admission only; provider invoices and unwrapped resources can differ."}

    def import_history_once(self, history_path: str | Path) -> bool:
        """Import the reviewed setup ledger atomically once, never resetting history.

        Later edits of setup-spend.json are not reimported. After this migration,
        all new reservations/settlements belong in this durable SQLite ledger.
        """
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM ledger_meta WHERE key='history_import'").fetchone():
                return False
            try:
                raw = Path(history_path).read_bytes()
                history = json.loads(raw)
                rows = self._history_rows(history)
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise HistoryImportError("Historical setup spending is missing or invalid; live admission is blocked") from error
            now = _now()
            for item in rows:
                if db.execute("SELECT 1 FROM spend_operations WHERE operation_id=?", (item["id"],)).fetchone():
                    raise HistoryImportError("Historical operation ID already exists without a completed import marker")
                db.execute("""INSERT INTO spend_operations
                            (operation_id,provider,reserved_micros,settled_micros,status,created_at,updated_at,imported,unknown_reason)
                            VALUES (?,?,?,?,?,?,?,1,?)""",
                           (item["id"], item["provider"], item["reserved"], item["settled"], item["status"], now, now,
                            "unclassified" if item["status"] == "unknown" else None))
            metadata = {"sha256": hashlib.sha256(raw).hexdigest(), "imported_at": now,
                        "source_name": Path(history_path).name, "operation_count": len(rows)}
            db.execute("INSERT INTO ledger_meta(key,value) VALUES ('history_import',?)", (json.dumps(metadata),))
            return True

    @staticmethod
    def _history_rows(history):
        if not isinstance(history, dict) or history.get("currency") != "USD":
            raise ValueError("Historical currency must be USD")
        if _units(history["authorization_total"]) != _AUTHORIZED or _units(history["planned_ceiling"]) != _PLANNED:
            raise ValueError("Historical allowance differs from authorized amounts")
        settled_total = _units(history.get("estimated_new_usage_usd", history.get("recorded_new_paid_usage", "0")))
        unresolved_total = _units(history.get("unresolved_reservations", "0"))
        entries = history.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("Historical entries must be a list")
        result = []
        seen = set()
        for entry in entries:
            identifier = _identifier(entry["id"], "historical operation ID")
            if identifier in seen:
                raise ValueError("Duplicate historical operation ID")
            seen.add(identifier)
            provider = _identifier(entry["provider"], "historical provider")
            settled_value = entry.get("settled_estimated_usd")
            status = entry.get("status", "unknown")
            if settled_value is not None:
                settled = _units(settled_value)
                reserved = _units(entry.get("reserved_usd", settled_value))
                result.append({"id": identifier, "provider": provider, "reserved": reserved,
                               "settled": settled, "status": "settled"})
            elif status in {"cancelled", "cancelled_undispatched"}:
                result.append({"id": identifier, "provider": provider,
                               "reserved": _units(entry.get("reserved_usd", "0")),
                               "settled": None, "status": "cancelled"})
            else:
                result.append({"id": identifier, "provider": provider,
                               "reserved": _units(entry["reserved_usd"]),
                               "settled": None, "status": "unknown"})
        if not entries:
            if settled_total:
                result.append({"id": "historical:aggregate:settled", "provider": "historical aggregate",
                               "reserved": settled_total, "settled": settled_total, "status": "settled"})
            if unresolved_total:
                result.append({"id": "historical:aggregate:unknown", "provider": "historical aggregate",
                               "reserved": unresolved_total, "settled": None, "status": "unknown"})
        if sum(item["settled"] or 0 for item in result) != settled_total:
            raise ValueError("Historical settled entries disagree with their summary")
        if sum(item["reserved"] for item in result if item["status"] == "unknown") != unresolved_total:
            raise ValueError("Historical unresolved entries disagree with their summary")
        return result
