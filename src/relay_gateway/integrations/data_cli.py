"""Finite synthetic data proofs with explicit shared-ledger live admission."""

import argparse
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
import re

from ..models import normalize_reference_context
from .data import MongoMissionStore, MockMongoClient, SnowflakeReferenceStore, TigerTelemetryStore
from .ledger import SpendLedger


PROVIDERS = {"mongodb": "MongoDB Atlas", "tiger": "Tiger Data", "snowflake": "Snowflake"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_AMOUNT = re.compile(r"(?:0(?:\.[0-9]{1,6})?|1(?:\.0{1,6})?)\Z")
START = "2026-09-26T18:00:00Z"
END = "2026-09-26T18:01:00Z"


class DataCommandError(RuntimeError):
    """Only fixed messages, never configuration or provider errors, are public."""


class _ProofStopped(Exception):
    def __init__(self, status):
        self.status = status


def _reservation(value):
    if not isinstance(value, str) or not _AMOUNT.fullmatch(value) or Decimal(value) <= 0:
        raise DataCommandError("Live proof requires --max-usd greater than zero and at most 1, with at most six decimal places.")
    return f"{Decimal(value):.6f}"


def _adapters(provider, live):
    """Construct and locally validate only; adapter methods open connections."""
    if provider == "mongodb":
        if live:
            if importlib.util.find_spec("pymongo") is None:
                raise ValueError("Missing optional dependency")
            return (MongoMissionStore.from_environment(live=True), MongoMissionStore.from_environment(live=True))
        # A shared in-memory transport demonstrates the contract, not persistence.
        transport = MockMongoClient()
        return (MongoMissionStore(client=transport), MongoMissionStore(client=transport))
    if provider == "tiger":
        if live and importlib.util.find_spec("psycopg") is None:
            raise ValueError("Missing optional dependency")
        return (TigerTelemetryStore.from_environment(live=live),)
    return (SnowflakeReferenceStore.from_environment(live=live),)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _proof(provider, adapters, mission_id, steps):
    def call(action, operation):
        result = operation()
        status = result.get("status") if isinstance(result, dict) else None
        status = status if status in {"completed", "failed", "unknown"} else "unknown"
        step = {"action": action, "status": status}
        # Preserve a pending query's handle for manual read-only reconciliation.
        if provider == "snowflake" and isinstance(result, dict):
            handle = result.get("evidence", {}).get("statement_handle")
            if isinstance(handle, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", handle):
                step["statement_handle"] = handle
        steps.append(step)
        if status != "completed":
            raise _ProofStopped(status)
        return result

    def require(condition):
        if not condition:
            raise _ProofStopped("failed")

    if provider == "mongodb":
        writer, reader = adapters
        initial = {"mission_id": mission_id, "simulated": True, "review_status": "pending",
                   "human_review_performed": False, "actuation_enabled": False}
        reviewed = {**initial, "review_status": "simulated_review"}
        first = call("upsert_pending_snapshot", lambda: writer.upsert_mission(initial))
        second = call("upsert_simulated_review", lambda: writer.upsert_mission(reviewed))
        writer.close()
        restored = call("read_with_fresh_adapter", lambda: reader.get_mission(mission_id))
        expected_digest = _digest(reviewed)
        require(restored.get("mission") == reviewed
                and restored.get("evidence", {}).get("content_sha256") == expected_digest
                and second.get("evidence", {}).get("content_sha256") == expected_digest)
        return {"mission_id": mission_id, "content_sha256": expected_digest,
                "review_status": "simulated_review", "human_review_performed": False,
                "initial_inserted": first.get("inserted"), "review_inserted": second.get("inserted"),
                "fresh_adapter_readback_verified": True}
    if provider == "tiger":
        (store,) = adapters
        events = [{"mission_id": mission_id, "event_id": "water-proof-001", "robot_id": "station-a",
                   "observed_at": START, "kind": "water", "value_milli": 850, "simulated": True,
                   "latitude": None, "longitude": None}]
        inserted = call("insert_synthetic_event", lambda: store.insert_telemetry(events))
        replay = call("replay_identical_event", lambda: store.insert_telemetry(events))
        queried = call("query_fixed_window", lambda: store.query_range(mission_id, START, END, limit=2))
        require(inserted.get("inserted") in (0, 1) and replay.get("inserted") == 0
                and queried.get("rows") == events)
        return {"mission_id": mission_id, "event_ids": [events[0]["event_id"]],
                "inserted_events": inserted["inserted"], "replay_inserted_events": replay["inserted"],
                "readback_events": 1, "start_inclusive": START, "end_exclusive": END,
                "idempotency_verified": True, "payload_readback_verified": True}
    (store,) = adapters
    result = call("retrieve_bounded_references", lambda: store.retrieve("standing_water", limit=2))
    references = result.get("references")
    require(isinstance(references, list) and 1 <= len(references) <= 2)
    # Adapter validation already bounds/validates these fields; preserve the
    # passages so a separately metered Gemini run can use the exact saved data.
    context = normalize_reference_context([
        {key: value for key, value in reference.items() if key != "simulated"}
        | {"is_simulated": reference["simulated"]} for reference in references])
    return {"statement_handle": result.get("evidence", {}).get("statement_handle"),
            "reference_ids": [reference["reference_id"] for reference in references],
            "reference_context": context, "retrieval_verified": True, "model_use_verified": False,
            "source_simulation_note": "Each passage retains its own is_simulated flag; the proof's hazard query is synthetic."}


def run_data_proof(provider, *, live=False, operation_id=None, max_usd=None,
                   _ledger_factory=None, _adapter_factory=None):
    """Private test injection cannot be selected by command-line arguments."""
    if provider not in PROVIDERS or type(live) is not bool:
        raise DataCommandError("Choose mongodb, tiger or snowflake; live mode must be explicit.")
    if operation_id is not None and (not isinstance(operation_id, str) or not _IDENTIFIER.fullmatch(operation_id)):
        raise DataCommandError("Operation ID must be a non-secret identifier of 1–80 letters, digits, dots, underscores, colons or hyphens.")
    maximum = None
    if live:
        if operation_id is None:
            raise DataCommandError("Live proof requires an explicit --operation-id; reuse it to prevent accidental redispatch.")
        maximum = _reservation(max_usd)
        if os.environ.get("RELAY_ALLOW_LIVE_DATA") != "1":
            raise DataCommandError("Live proof requires RELAY_ALLOW_LIVE_DATA=1.")
    identifier = "data:" + provider + ":" + (operation_id or "offline-proof-v1")
    mission_id = "relay-data-proof-" + hashlib.sha256(identifier.encode()).hexdigest()[:24]
    try:
        adapters = (_adapter_factory or _adapters)(provider, live)
    except Exception:
        raise DataCommandError("Local provider configuration or optional dependency is invalid; no provider request was sent.") from None

    ticket = None
    ledger = None
    steps = []
    status = "completed"
    evidence = {}
    spending = {"status": "not_used", "reserved_usd": "0.000000", "estimated_usd": "0.000000"}
    try:
        if live:
            try:
                ledger = (_ledger_factory or SpendLedger)()
                ticket = ledger.reserve(identifier, PROVIDERS[provider], maximum)
                if not ticket.created:
                    raise ValueError("Duplicate")
                ledger.mark_dispatched(ticket)
            except Exception:
                raise DataCommandError("Shared spending admission or duplicate protection blocked the proof; no provider request was sent.") from None
        try:
            evidence = _proof(provider, adapters, mission_id, steps)
        except _ProofStopped as error:
            status = error.status
        except Exception:
            status = "unknown"
        if live:
            try:
                ledger.mark_unknown(identifier, reason="missing_usage" if status == "completed" else "unclassified")
                spending_status = "unknown"
            except Exception:
                spending_status = "dispatched_reconciliation_required"
            spending = {"status": spending_status, "reserved_usd": ticket.reserved_usd,
                        "estimated_usd": None,
                        "note": "The entire reservation remains held. Reconcile provider usage and resource lifetime manually."}
    finally:
        for adapter in adapters:
            close = getattr(adapter, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass
    return {"schema_version": "1", "provider": provider, "mode": "live" if live else "mock",
            "status": status, "operation_id": identifier, "simulated": True,
            "remote_verified": live and status == "completed", "proof_verified": status == "completed",
            "actual_billed_usd": None if live else "0.000000", "steps": steps,
            "evidence": evidence, "spending": spending,
            "limitations": ["All proof inputs are synthetic; review and physical inspection are not established.",
                            "No cloud service or SQL schema is provisioned. MongoDB upserts may create the configured database/collection. Provider billing and shutdown remain external.",
                            "Reference retrieval alone does not prove use by Gemini." if provider == "snowflake"
                            else "A completed proof verifies only the bounded operations shown."]}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DataCommandError("Invalid data proof command options; use --help.")


def main(argv=None):
    parser = _Parser(description="Run one finite synthetic data proof; default is offline mock.")
    parser.add_argument("provider", choices=PROVIDERS)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--operation-id", help="Non-secret explicit attempt identifier; duplicates never dispatch again")
    parser.add_argument("--max-usd", help="Live reservation, greater than zero and at most 1; verify pricing first")
    try:
        args = parser.parse_args(argv)
        result = run_data_proof(args.provider, live=args.live, operation_id=args.operation_id, max_usd=args.max_usd)
    except DataCommandError as error:
        print(json.dumps({"status": "blocked", "message": str(error), "actual_billed_usd": None}))
        return 2
    except Exception:
        print(json.dumps({"status": "unknown", "message": "Data proof is unresolved; inspect local spending state before retrying.",
                          "actual_billed_usd": None}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
