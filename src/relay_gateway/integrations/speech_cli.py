"""One reviewed briefing, with mock defaults and durable live admission."""

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import re

from . import audio_receipt
from .ledger import SpendLedger


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_TEXT_CHARACTERS = 200
MAX_TEXT_BYTES = MAX_TEXT_CHARACTERS * 4 + 3  # UTF-8 plus optional BOM.
LIVE_MODEL = "eleven_flash_v2_5"
_VOICE = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_AMOUNT = re.compile(r"0(?:\.[0-9]{1,6})?\Z")


class SpeechCommandError(RuntimeError):
    """Only fixed, non-sensitive messages leave this command."""

    def __init__(self, message: str, *, status: str = "blocked"):
        super().__init__(message)
        self.status = status


def _read_briefing(path) -> str:
    try:
        file = Path(path)
        if not file.is_file():
            raise ValueError
        with file.open("rb") as stream:
            raw = stream.read(MAX_TEXT_BYTES + 1)
        if len(raw) > MAX_TEXT_BYTES:
            raise ValueError
        text = raw.decode("utf-8-sig").strip()
    except (OSError, TypeError, ValueError):
        raise SpeechCommandError("Briefing must be a bounded UTF-8 text file.") from None
    if not 1 <= len(text) <= MAX_TEXT_CHARACTERS or any(
        ord(char) < 32 and char not in "\n\t" or ord(char) == 127 for char in text
    ):
        raise SpeechCommandError("Briefing must contain 1–200 characters without unsupported control characters.")
    return text


def _reservation(value) -> str:
    if not isinstance(value, str) or not _AMOUNT.fullmatch(value):
        raise SpeechCommandError("Live speech requires --max-usd as a positive decimal no greater than 0.25.")
    amount = Decimal(value)
    if not Decimal("0") < amount <= Decimal("0.25"):
        raise SpeechCommandError("Live speech requires --max-usd as a positive decimal no greater than 0.25.")
    return f"{amount:.6f}"


def _live_configuration() -> tuple[str, str]:
    if os.environ.get("RELAY_ALLOW_ELEVENLABS") != "1":
        raise SpeechCommandError("Live speech requires RELAY_ALLOW_ELEVENLABS=1.")
    voice = os.environ.get("ELEVENLABS_VOICE_ID")
    model = os.environ.get("ELEVENLABS_MODEL_ID")
    if not isinstance(voice, str) or not _VOICE.fullmatch(voice):
        raise SpeechCommandError("An explicit valid ELEVENLABS_VOICE_ID is required.")
    if model != LIVE_MODEL:
        raise SpeechCommandError("ELEVENLABS_MODEL_ID must explicitly select eleven_flash_v2_5.")
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key or len(key) > 4096 or not key.isascii() or any(ord(char) <= 32 or ord(char) >= 127 for char in key):
        raise SpeechCommandError("A valid ELEVENLABS_API_KEY must be configured locally.")
    return voice, model


def run_speech(text_file, *, reviewed: bool, live: bool = False, max_usd: str | None = None,
               _ledger_factory=None, _transport=None, _state_dir=None) -> dict:
    """Private injection points isolate tests; CLI cannot redirect the ledger.

    A transport gate reserves immediately before outbound work, after the
    adapter's local validation/cache lookup. Cached audio never opens a ledger.
    """
    if reviewed is not True or type(live) is not bool:
        raise SpeechCommandError("The operator must explicitly supply --reviewed; live mode must be boolean.")
    text = _read_briefing(text_file)
    maximum = _reservation(max_usd) if live else None
    voice, model = _live_configuration() if live else ("mock-voice", LIVE_MODEL)
    # Nonempty explicit settings make the mock independent of all environment keys.
    preview = audio_receipt.synthesize_briefing(text, reviewed=True, voice_id=voice, model_id=model)
    operation_id = "speech:" + preview["cache_key"]
    if not live:
        return {**preview, "operation_id": operation_id,
                "spending": {"status": "not_used", "new_reservation": False,
                             "reserved_usd": "0.000000", "estimated_usd": "0.000000"}}

    ledger = None
    ticket = None
    dispatched = False
    gate_error = None

    def metered_transport(url, headers, body, timeout):
        nonlocal ledger, ticket, dispatched, gate_error
        try:
            if ticket is not None:
                raise SpeechCommandError("The one-request speech limit was reached.")
            ledger = (_ledger_factory or SpendLedger)()
            ticket = ledger.reserve(operation_id, "ElevenLabs", maximum)
            if not ticket.created:
                raise SpeechCommandError("This speech operation already exists; it cannot dispatch again.")
            ledger.mark_dispatched(ticket)
            dispatched = True
        except Exception:
            gate_error = SpeechCommandError("Shared spending admission or duplicate protection blocked speech; no provider request was sent.")
            raise gate_error from None
        return (_transport or audio_receipt._post)(url, headers, body, timeout)

    def retain_reservation(reason: str) -> str:
        try:
            ledger.mark_unknown(operation_id, reason=reason)
            return "unknown"
        except Exception:
            # The dispatched row still consumes allowance; never release it.
            return "dispatched_reconciliation_required"

    try:
        result = audio_receipt.synthesize_briefing(
            text, reviewed=True, live=True, voice_id=voice, model_id=model,
            state_dir=_state_dir if _state_dir is not None else PROJECT_ROOT / ".state",
            _transport=metered_transport)
    except Exception:
        if gate_error is not None:
            raise gate_error from None
        if dispatched:
            retain_reservation("unclassified")
            raise SpeechCommandError(
                "Speech delivery or recording is unresolved. Its reservation remains held; no retry was attempted.",
                status="unknown") from None
        raise SpeechCommandError("Local speech validation or cache state blocked generation; no provider request was sent.") from None

    if not dispatched:
        return {**result, "operation_id": operation_id,
                "spending": {"status": "unchanged", "new_reservation": False,
                             "reserved_usd": None, "estimated_usd": None,
                             "note": "Cached original generation may still require billing reconciliation."}}
    return {**result, "operation_id": operation_id,
            "spending": {"status": retain_reservation("missing_usage"), "new_reservation": True,
                         "reserved_usd": ticket.reserved_usd, "estimated_usd": None,
                         "note": "Usage headers do not establish USD billing. Reconcile the original operation manually."}}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SpeechCommandError("Invalid speech command options; use --help.")


def main(argv=None) -> int:
    parser = _Parser(description="Generate one reviewed, bounded briefing; default is offline mock.")
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--reviewed", action="store_true", help="Confirm operator review of the exact input text")
    parser.add_argument("--live", action="store_true", help="Explicitly enable one metered provider request")
    parser.add_argument("--max-usd", help="Live reservation, greater than zero and at most 0.25; no default")
    try:
        args = parser.parse_args(argv)
        result = run_speech(args.text_file, reviewed=args.reviewed, live=args.live, max_usd=args.max_usd)
    except SpeechCommandError as error:
        print(json.dumps({"status": error.status, "message": str(error), "actual_billed_usd": None}))
        return 2
    except Exception:
        print(json.dumps({"status": "unknown", "message": "Speech command failed; inspect local state before retrying.",
                          "actual_billed_usd": None}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
