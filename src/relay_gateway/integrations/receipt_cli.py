"""One explicit devnet receipt operation; default behavior is fully offline."""

import argparse
import json
import os
from pathlib import Path
import re

from . import audio_receipt


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_INPUT_BYTES = 256 * 1024
COMMAND_SCHEMA = "relay.receipt-command.v1"
_BASE58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,128}\Z")
_STATUSES = {"mock", "confirmed", "not_yet_confirmed", "transaction_failed", "memo_mismatch",
             "invalid_transaction_evidence", "report_changed", "mock_hash_verified", "chain_not_checked"}
_UNFUNDED = "Dedicated wallet needs devnet test tokens for the estimated fee; no airdrop or transaction requested."


class ReceiptCommandError(RuntimeError):
    def __init__(self, message, *, status="blocked"):
        super().__init__(message)
        self.status = status


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Non-finite JSON constant")


def _read_json(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant)
        if type(value) is not dict:
            raise ValueError
        audio_receipt._json_bytes(value)  # Finite values and nesting <= 20.
        return value
    except (OSError, TypeError, ValueError, UnicodeError, RecursionError):
        raise ReceiptCommandError("Input must be a bounded UTF-8 JSON object of at most 256 KiB, without duplicate keys or non-finite values.") from None


def _report(path):
    value = _read_json(path)
    if value.get("schema_version") == "1" and "report" in value:
        if value.get("mode") != "mock" or value.get("status") != "completed" or value.get("simulated") is not True:
            raise ReceiptCommandError("A replay envelope must be a completed, explicitly simulated mock integration replay.")
        value = value["report"]
    try:
        audio_receipt.canonical_report_bytes(value)
    except (TypeError, ValueError, RecursionError):
        raise ReceiptCommandError("Report must have an explicit simulated boolean and bounded finite JSON content.") from None
    return value


def _receipt(path):
    value = _read_json(path)
    if value.get("schema") == COMMAND_SCHEMA:
        if value.get("operation") != "create" or type(value.get("receipt")) is not dict:
            raise ReceiptCommandError("Receipt command output must contain a creation receipt.")
        value = value["receipt"]
    if (value.get("schema") != "relay.receipt.v1" or value.get("network") != "devnet"
            or value.get("mode") not in {"mock", "live"}):
        raise ReceiptCommandError("Receipt must be a Relay mock or live devnet receipt.")
    return value


def _live(live):
    if type(live) is not bool:
        raise ReceiptCommandError("Live mode must be an explicit boolean.")
    if live and os.environ.get("RELAY_ALLOW_SOLANA_DEVNET") != "1":
        raise ReceiptCommandError("Live receipt operations require RELAY_ALLOW_SOLANA_DEVNET=1 and --live.")


def _verification(result):
    if (not isinstance(result, dict) or result.get("status") not in _STATUSES
            or type(result.get("hash_matches")) is not bool
            or type(result.get("chain_verified")) is not bool
            or result.get("valid") is not None and type(result.get("valid")) is not bool):
        raise ValueError("Invalid verification result")
    output = {name: result.get(name) for name in ("status", "hash_matches", "chain_verified", "valid")}
    slot = result.get("slot")
    if type(slot) is int and slot >= 0:
        output["slot"] = slot
    return output


def _base(operation, report, live):
    return {"schema": COMMAND_SCHEMA, "operation": operation, "mode": "live" if live else "mock",
            "network": "devnet", "report_sha256": audio_receipt.report_sha256(report),
            "report_simulated": report["simulated"], "funding_requested": False,
            "fee_unit": "devnet_lamports", "fee_is_test_tokens": True,
            "actual_billed_usd": None if live else "0.000000",
            "spend_ledger_modified": False,
            "limitations": ["Devnet lamports are test-token units, not USD; this command performs no currency conversion.",
                            "A report hash proves integrity, not sensor accuracy, human review or a physical inspection."]}


def run_create(report_file, *, finalized=False, live=False):
    if finalized is not True:
        raise ReceiptCommandError("Creation requires --finalized for the exact report being anchored.")
    report = _report(report_file)
    _live(live)
    base = _base("create", report, live)
    try:
        options = {"finalized": True, "live": live}
        if live:
            options["state_dir"] = PROJECT_ROOT / ".state"
        result = audio_receipt.create_report_receipt(report, **options)
        digest = base["report_sha256"]
        mode = "live" if live else "mock"
        if (result.get("schema") != "relay.receipt.v1" or result.get("network") != "devnet"
                or result.get("mode") != mode or result.get("report_sha256") != digest
                or result.get("memo") != "relay:v1:sha256:" + digest or result.get("status") not in _STATUSES):
            raise ValueError("Unexpected receipt result")
        signature, signer = result.get("signature"), result.get("signer")
        if live and (not isinstance(signature, str) or not _BASE58.fullmatch(signature)
                     or not isinstance(signer, str) or not _BASE58.fullmatch(signer)):
            raise ValueError("Invalid live signature or signer")
        receipt = {"schema": "relay.receipt.v1", "provider": "solana", "mode": mode, "network": "devnet",
                   "simulated": not live or report["simulated"], "report_simulated": report["simulated"],
                   "report_sha256": digest, "memo": "relay:v1:sha256:" + digest,
                   "signature": signature if live else None, "signer": signer if live else None,
                   "status": result["status"], "chain_verified": result.get("chain_verified") is True,
                   "request_sent": result.get("request_sent") is True,
                   "reused_receipt": result.get("reused_receipt") is True,
                   "explorer_url": "https://explorer.solana.com/tx/" + signature + "?cluster=devnet" if live else None}
        fee = result.get("fee_lamports_estimate")
        if type(fee) is int and fee >= 0:
            receipt["fee_lamports_estimate"] = fee
        verification = _verification(result["verification"]) if "verification" in result else None
        if live:
            if (receipt["status"] == "confirmed") != receipt["chain_verified"]:
                raise ValueError("Inconsistent chain result")
            if receipt["chain_verified"] and (verification is None or verification["status"] != "confirmed"
                                               or verification["valid"] is not True or verification["hash_matches"] is not True
                                               or verification["chain_verified"] is not True):
                raise ValueError("Unverified confirmation")
        elif receipt["status"] != "mock" or receipt["chain_verified"]:
            raise ValueError("Mock cannot claim a transaction")
        return {**base, "status": receipt["status"], "receipt": receipt,
                "verification": verification, "chain_verified": receipt["chain_verified"]}
    except Exception as error:
        if isinstance(error, audio_receipt.IntegrationError) and str(error) == _UNFUNDED:
            raise ReceiptCommandError("Dedicated devnet wallet needs test tokens; no transaction or funding request was sent.") from None
        raise ReceiptCommandError("Receipt creation is unresolved. Inspect the saved receipt before retrying; no automatic retry was attempted.",
                                  status="unknown") from None


def run_verify(report_file, receipt_file, *, live=False):
    report, receipt = _report(report_file), _receipt(receipt_file)
    _live(live)
    base = _base("verify", report, live)
    try:
        verification = _verification(audio_receipt.verify_report_receipt(report, receipt, live=live))
    except Exception:
        raise ReceiptCommandError("Receipt verification is unresolved; no transaction was submitted and no automatic retry was attempted.",
                                  status="unknown") from None
    return {**base, "status": verification["status"], "receipt_mode": receipt["mode"],
            "verification": verification, "chain_verified": verification["chain_verified"],
            "transaction_submitted": False}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ReceiptCommandError("Invalid receipt command options; use --help.")


def main(argv=None):
    parser = _Parser(description="Create or verify one report receipt; defaults are offline mocks.")
    commands = parser.add_subparsers(dest="operation", required=True)
    create = commands.add_parser("create")
    create.add_argument("--report-file", type=Path, required=True)
    create.add_argument("--finalized", action="store_true")
    create.add_argument("--live", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("--report-file", type=Path, required=True)
    verify.add_argument("--receipt-file", type=Path, required=True)
    verify.add_argument("--live", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.operation == "create":
            result = run_create(args.report_file, finalized=args.finalized, live=args.live)
        else:
            result = run_verify(args.report_file, args.receipt_file, live=args.live)
    except ReceiptCommandError as error:
        print(json.dumps({"schema": COMMAND_SCHEMA, "status": error.status, "message": str(error), "actual_billed_usd": None}))
        return 2
    except Exception:
        print(json.dumps({"schema": COMMAND_SCHEMA, "status": "unknown", "message": "Receipt command is unresolved; inspect local evidence before retrying.", "actual_billed_usd": None}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"mock", "mock_hash_verified", "confirmed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
