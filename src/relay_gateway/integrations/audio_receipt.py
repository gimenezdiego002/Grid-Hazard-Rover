"""Explicit speech generation and devnet-only report receipts.

Defaults never use a network, create a wallet, or manufacture playable speech.
The caller owns cross-provider budget admission before enabling a live operation.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import csv
from dataclasses import dataclass, field
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Mapping
import urllib.error
import urllib.request


DEVNET_RPC = "https://api.devnet.solana.com"
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
MAX_BRIEFING_CHARS = 600
MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 256 * 1024
OUTPUT_FORMAT = "mp3_44100_128"
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_PROVIDER_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CHARACTER_COST = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?\Z")


class IntegrationError(RuntimeError):
    """Sanitized message safe for an operator; never contains provider bodies."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


HttpPost = Callable[[str, Mapping[str, str], bytes, float], HttpResponse]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _post(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            payload = response.read(MAX_AUDIO_BYTES + 1)
            if len(payload) > MAX_AUDIO_BYTES:
                raise IntegrationError("Provider response exceeded the local size limit.")
            return HttpResponse(response.status, payload, dict(response.headers.items()))
    except urllib.error.HTTPError as error:
        # Do not echo potentially sensitive request data or response bodies.
        raise IntegrationError(f"Provider HTTP request failed with status {error.code}; no retry attempted.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise IntegrationError("Provider request failed or timed out; billing/transaction status may be unknown. No retry attempted.") from None


def _json_bytes(value) -> bytes:
    def inspect(item, depth=0):
        if depth > 20:
            raise ValueError("JSON nesting exceeds the local limit.")
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("JSON object keys must be strings.")
                inspect(child, depth + 1)
        elif type(item) is list:
            for child in item:
                inspect(child, depth + 1)
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Non-finite JSON numbers are not allowed.")
        elif item is not None and type(item) not in (str, int, bool):
            raise ValueError("Only JSON values are accepted.")
    inspect(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Value cannot be encoded as bounded UTF-8 JSON.") from None
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("JSON exceeds the local size limit.")
    return encoded


def canonical_report_bytes(report: dict) -> bytes:
    """Relay canonical JSON v1: sorted keys, compact UTF-8, finite JSON values.

    This is our explicit Python-compatible encoding, not an RFC 8785 claim.
    """
    if type(report) is not dict or type(report.get("simulated")) is not bool:
        raise ValueError("A report must be a JSON object with an explicit simulated boolean.")
    return _json_bytes(report)


def report_sha256(report: dict) -> str:
    return hashlib.sha256(canonical_report_bytes(report)).hexdigest()


def _state_root(state_dir) -> Path:
    requested = Path(state_dir)
    if requested.name != ".state" or requested.is_symlink() or requested.is_junction():
        raise ValueError("Local integration state must be a dedicated, non-linked .state directory.")
    root = requested.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _child(root: Path, *parts: str) -> Path:
    target = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise ValueError("Linked integration state paths are not accepted.")
    if not target.resolve().is_relative_to(root):
        raise ValueError("Integration state must remain inside its .state directory.")
    return target


@contextmanager
def _exclusive_lock(path: Path):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise IntegrationError("This operation is already running or left an unresolved lock; inspect it before retrying.") from None
    os.close(descriptor)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _write_json(path: Path, content: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_json_bytes(content))
    os.replace(temporary, path)


def _read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise IntegrationError("Local integration record exceeds the size limit.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise IntegrationError("Local integration record is unreadable; no network retry attempted.") from None
    if type(value) is not dict:
        raise IntegrationError("Local integration record has an invalid format.")
    return value


def _live_switch(name: str) -> None:
    if os.environ.get(name) != "1":
        raise IntegrationError(f"Live operation requires {name}=1 and explicit live=True.")


def _check_live(live: bool) -> None:
    if type(live) is not bool:
        raise ValueError("live must be an explicit boolean.")


def _safe_provider_id(value) -> str | None:
    return value if isinstance(value, str) and _PROVIDER_ID.fullmatch(value) else None


def _speech_usage_evidence(character_cost, trace_id) -> dict:
    """Allowlist generation metadata without interpreting it as money.

    ElevenLabs documents this header as character cost, not USD. Its unit-to-
    currency mapping must be verified against the applicable account pricing.
    Keep malformed values unknown instead of guessing from input text length.
    """
    valid = isinstance(character_cost, str) and _CHARACTER_COST.fullmatch(character_cost)
    return {
        "provider_character_cost": character_cost if valid else None,
        "provider_character_cost_status": "reported" if valid else (
            "missing" if character_cost is None else "malformed"),
        "provider_character_cost_unit": "provider_defined",
        "provider_trace_id": _safe_provider_id(trace_id),
    }


def synthesize_briefing(text: str, *, reviewed: bool, live: bool = False,
                       voice_id: str | None = None, model_id: str | None = None,
                       state_dir: str | Path = ".state", _transport: HttpPost | None = None) -> dict:
    """Speak reviewed text once, or return a clearly labeled mock descriptor.

    One dispatch maximum, zero automatic retries. An unresolved attempt blocks
    subsequent identical requests until its billing status is manually resolved.
    """
    _check_live(live)
    if reviewed is not True:
        raise ValueError("Speech requires an explicitly reviewed briefing.")
    if type(text) is not str or not text.strip() or len(text) > MAX_BRIEFING_CHARS:
        raise ValueError(f"Briefing must contain 1–{MAX_BRIEFING_CHARS} characters.")
    if any(ord(char) < 32 and char not in "\n\t" for char in text) or "\x7f" in text:
        raise ValueError("Briefing contains unsupported control characters.")
    text = text.strip()
    voice = voice_id or os.environ.get("ELEVENLABS_VOICE_ID") or (None if live else "mock-voice")
    model = model_id or os.environ.get("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2"
    if not isinstance(voice, str) or not _IDENTIFIER.fullmatch(voice):
        raise ValueError("An explicit valid ElevenLabs voice ID is required.")
    if not isinstance(model, str) or not _IDENTIFIER.fullmatch(model):
        raise ValueError("Invalid ElevenLabs model ID.")
    cache_key = hashlib.sha256(_json_bytes({"v": 1, "text": text, "voice_id": voice,
                                          "model_id": model, "output_format": OUTPUT_FORMAT})).hexdigest()
    result = {"provider": "elevenlabs", "mode": "live" if live else "mock",
              "simulated": not live, "cache_key": cache_key, "cache_hit": False,
              "characters": len(text), "voice_id": voice, "model_id": model,
              "output_format": OUTPUT_FORMAT, "audio_path": None, "audio_sha256": None,
              "request_sent": False, "actual_billed_usd": None if live else "0.00",
              **_speech_usage_evidence(None, None), "provider_character_cost_status": "not_requested"}
    if not live:
        return {**result, "status": "mock", "note": "No speech generated; no provider request made."}
    _live_switch("RELAY_ALLOW_ELEVENLABS")
    root = _state_root(state_dir)
    directory = _child(root, "audio")
    directory.mkdir(exist_ok=True)
    audio_path = _child(root, "audio", cache_key + ".mp3")
    record_path = _child(root, "audio", cache_key + ".json")
    attempt_path = _child(root, "audio", cache_key + ".attempt.json")
    lock_path = _child(root, "audio", cache_key + ".lock")
    with _exclusive_lock(lock_path):
        if record_path.exists() or audio_path.exists():
            if not (record_path.exists() and audio_path.exists()) or audio_path.stat().st_size > MAX_AUDIO_BYTES:
                raise IntegrationError("Speech cache is incomplete; no automatic regeneration attempted.")
            record = _read_json(record_path)
            actual_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
            if record.get("cache_key") != cache_key or record.get("audio_sha256") != actual_hash:
                raise IntegrationError("Speech cache integrity failed; no automatic regeneration attempted.")
            evidence = _speech_usage_evidence(record.get("provider_character_cost"), record.get("provider_trace_id"))
            if evidence["provider_character_cost_status"] == "missing" and record.get("provider_character_cost_status") == "malformed":
                evidence["provider_character_cost_status"] = "malformed"
            request_id = _safe_provider_id(record.get("provider_request_id"))
            if request_id:
                evidence["provider_request_id"] = request_id
            return {**result, "status": "completed", "cache_hit": True,
                    "audio_path": str(audio_path), "audio_sha256": actual_hash, **evidence}
        if attempt_path.exists():
            raise IntegrationError("An earlier speech dispatch is unresolved; check billing before authorizing another attempt.")
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise IntegrationError("ELEVENLABS_API_KEY is not configured.")
        _write_json(attempt_path, {"cache_key": cache_key, "status": "dispatching",
                                   "characters": len(text), "voice_id": voice, "model_id": model})
        try:
            response = (_transport or _post)(
                "https://api.elevenlabs.io/v1/text-to-speech/" + voice + "?output_format=" + OUTPUT_FORMAT,
                {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
                _json_bytes({"text": text, "model_id": model}), 20.0)
            headers = {key.lower(): value for key, value in response.headers.items()}
            mp3_signature = response.body.startswith(b"ID3") or (len(response.body) >= 2 and response.body[0] == 255 and response.body[1] & 224 == 224)
            if response.status != 200 or not response.body or len(response.body) > MAX_AUDIO_BYTES:
                raise IntegrationError("Speech generation did not return a bounded successful audio response.")
            if headers.get("content-type", "").split(";")[0] not in ("audio/mpeg", "audio/mp3") or not mp3_signature:
                raise IntegrationError("Speech response is not recognized as MP3 audio.")
            audio_path.write_bytes(response.body)
            result.update(status="completed", request_sent=True, audio_path=str(audio_path),
                          audio_sha256=hashlib.sha256(response.body).hexdigest())
            result.update(_speech_usage_evidence(headers.get("character-cost"), headers.get("x-trace-id")))
            request_id = _safe_provider_id(headers.get("request-id") or headers.get("x-request-id"))
            if request_id:
                result["provider_request_id"] = request_id
            _write_json(record_path, result)
            _write_json(attempt_path, {"cache_key": cache_key, "status": "completed"})
            return result
        except Exception as error:
            if isinstance(error, IntegrationError):
                raise
            raise IntegrationError("Speech dispatch or local recording failed; no retry attempted. Review provider billing before recovery.") from None


def _check_network(network: str) -> None:
    if network != "devnet":
        raise ValueError("Only Solana devnet is supported; mainnet and custom RPC endpoints are disabled.")


def _rpc(method: str, params: list, transport: HttpPost | None):
    response = (transport or _post)(DEVNET_RPC, {"Content-Type": "application/json"},
                                    _json_bytes({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}), 20.0)
    if response.status != 200 or len(response.body) > MAX_AUDIO_BYTES:
        raise IntegrationError("Solana devnet RPC did not return a bounded successful response.")
    try:
        body = json.loads(response.body)
        if not isinstance(body, dict) or "error" in body or "result" not in body:
            raise ValueError
        return body["result"]
    except (ValueError, UnicodeError):
        raise IntegrationError("Solana devnet RPC rejected the request or returned invalid data.") from None


def _solders():
    try:
        from solders.hash import Hash
        from solders.instruction import AccountMeta, Instruction
        from solders.keypair import Keypair
        from solders.message import MessageV0
        from solders.pubkey import Pubkey
        from solders.signature import Signature
        from solders.transaction import VersionedTransaction
        return Hash, AccountMeta, Instruction, Keypair, MessageV0, Pubkey, Signature, VersionedTransaction
    except ImportError:
        raise IntegrationError("Live Solana receipts require the optional solders==0.29.0 dependency.") from None


def _private_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
        return
    # Restrict the empty file before writing secret bytes. Never echo command output.
    flags = subprocess.CREATE_NO_WINDOW
    try:
        identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                                  check=True, capture_output=True, text=True, timeout=10, creationflags=flags)
        sid = next(csv.reader(io.StringIO(identity.stdout)))[-1]
        if not re.fullmatch(r"S-1-(?:\d+-)*\d+", sid):
            raise ValueError
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(F)"],
                       check=True, capture_output=True, timeout=10, creationflags=flags)
    except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
        raise IntegrationError("Could not restrict the dedicated devnet key file; no secret was written.") from None


def _wallet(root: Path):
    _, _, _, Keypair, _, _, _, _ = _solders()
    directory = _child(root, "solana")
    directory.mkdir(exist_ok=True)
    key_path = _child(root, "solana", "devnet-keypair.json")
    with _exclusive_lock(_child(root, "solana", "wallet.lock")):
        if key_path.exists():
            if key_path.stat().st_size > 1024:
                raise IntegrationError("Dedicated devnet key file is invalid.")
            try:
                raw = json.loads(key_path.read_text(encoding="utf-8"))
                if type(raw) is not list or len(raw) != 64 or any(type(value) is not int or not 0 <= value <= 255 for value in raw):
                    raise ValueError
                return Keypair.from_bytes(bytes(raw))
            except (ValueError, UnicodeError):
                raise IntegrationError("Dedicated devnet key file is invalid; it was not replaced.") from None
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        _private_file(key_path)
        wallet = Keypair()
        key_path.write_text(json.dumps(list(bytes(wallet))), encoding="utf-8")
        return wallet


def prepare_devnet_wallet(*, live: bool = False, network: str = "devnet", state_dir: str | Path = ".state") -> dict:
    """Create/reuse only this project's dedicated devnet wallet; never fund it."""
    _check_live(live)
    _check_network(network)
    if not live:
        return {"mode": "mock", "network": "devnet", "public_key": None, "wallet_created": False}
    _live_switch("RELAY_ALLOW_SOLANA_DEVNET")
    wallet = _wallet(_state_root(state_dir))
    return {"mode": "live", "network": "devnet", "public_key": str(wallet.pubkey()),
            "note": "Dedicated local devnet wallet only; no airdrop or transaction requested."}


def _memo(digest: str) -> str:
    return "relay:v1:sha256:" + digest


def verify_report_receipt(report: dict, receipt: dict, *, live: bool = False,
                          network: str = "devnet", _transport: HttpPost | None = None) -> dict:
    """Verify local report bytes, and optionally the actual signed devnet memo.

    Mock verification proves only the local hash comparison. A live receipt is
    never called valid until a successful confirmed transaction is inspected.
    """
    _check_live(live)
    _check_network(network)
    digest = report_sha256(report)
    if type(receipt) is not dict or receipt.get("schema") != "relay.receipt.v1" or receipt.get("network") != "devnet":
        raise ValueError("Unsupported receipt format or network.")
    matches = receipt.get("report_sha256") == digest and receipt.get("memo") == _memo(digest)
    result = {"hash_matches": matches, "chain_verified": False, "valid": False,
              "mode": receipt.get("mode"), "network": "devnet", "report_sha256": digest}
    if not matches:
        return {**result, "status": "report_changed"}
    if receipt.get("mode") == "mock":
        return {**result, "valid": True, "simulated": True, "status": "mock_hash_verified",
                "note": "Local hash comparison only; no blockchain transaction exists."}
    if receipt.get("mode") != "live":
        raise ValueError("Unknown receipt mode.")
    if not live:
        return {**result, "valid": None, "status": "chain_not_checked"}
    _live_switch("RELAY_ALLOW_SOLANA_DEVNET")
    _, _, _, _, _, Pubkey, Signature, VersionedTransaction = _solders()
    try:
        signature = str(Signature.from_string(receipt["signature"]))
        signer = str(Pubkey.from_string(receipt["signer"]))
    except (ValueError, KeyError, TypeError):
        raise ValueError("Receipt signature or signer is invalid.") from None
    fetched = _rpc("getTransaction", [signature, {"commitment": "confirmed", "encoding": "base64", "maxSupportedTransactionVersion": 0}], _transport)
    if fetched is None:
        return {**result, "valid": None, "status": "not_yet_confirmed"}
    try:
        if fetched["meta"]["err"] is not None:
            return {**result, "status": "transaction_failed"}
        raw, encoding = fetched["transaction"]
        if encoding != "base64":
            raise ValueError
        transaction = VersionedTransaction.from_bytes(base64.b64decode(raw, validate=True))
        if str(transaction.signatures[0]) != signature or not all(transaction.verify_with_results()):
            raise ValueError
        message = transaction.message
        keys = message.account_keys
        if str(keys[0]) != signer:
            raise ValueError
        expected = _memo(digest).encode("utf-8")
        memo_valid = any(str(keys[instruction.program_id_index]) == MEMO_PROGRAM
                         and bytes(instruction.data) == expected and 0 in instruction.accounts
                         for instruction in message.instructions)
        if not memo_valid:
            return {**result, "status": "memo_mismatch"}
        return {**result, "valid": True, "chain_verified": True, "status": "confirmed",
                "signature": signature, "slot": fetched.get("slot"),
                "note": "Report integrity verified; this does not establish sensor accuracy."}
    except (ValueError, KeyError, TypeError, IndexError):
        return {**result, "status": "invalid_transaction_evidence"}


def create_report_receipt(report: dict, *, finalized: bool, live: bool = False,
                          network: str = "devnet", state_dir: str | Path = ".state",
                          _transport: HttpPost | None = None) -> dict:
    """Sign/send one memo on devnet; never airdrop, retry, or use mainnet.

    A durable record is saved before dispatch. Repeated calls with the same
    report only inspect the recorded signature, avoiding a second transaction.
    """
    _check_live(live)
    _check_network(network)
    if finalized is not True:
        raise ValueError("A receipt requires an explicitly finalized report.")
    digest = report_sha256(report)
    receipt = {"schema": "relay.receipt.v1", "provider": "solana", "mode": "live" if live else "mock",
               "network": "devnet", "simulated": not live or report["simulated"],
               "report_simulated": report["simulated"], "report_sha256": digest,
               "memo": _memo(digest), "signature": None, "signer": None, "explorer_url": None,
               "chain_verified": False, "request_sent": False}
    if not live:
        return {**receipt, "status": "mock", "note": "No wallet or blockchain transaction created."}
    _live_switch("RELAY_ALLOW_SOLANA_DEVNET")
    Hash, AccountMeta, Instruction, _, MessageV0, Pubkey, _, VersionedTransaction = _solders()
    root = _state_root(state_dir)
    directory = _child(root, "solana", "receipts")
    directory.mkdir(parents=True, exist_ok=True)
    path = _child(root, "solana", "receipts", digest + ".json")
    with _exclusive_lock(_child(root, "solana", "receipts", digest + ".lock")):
        if path.exists():
            recorded = _read_json(path)
            verification = verify_report_receipt(report, recorded, live=True, _transport=_transport)
            return {**recorded, "reused_receipt": True, "request_sent": False, "verification": verification,
                    "chain_verified": verification["chain_verified"], "status": verification["status"]}
        wallet = _wallet(root)
        signer = wallet.pubkey()
        block = _rpc("getLatestBlockhash", [{"commitment": "confirmed"}], _transport)
        try:
            recent_hash = Hash.from_string(block["value"]["blockhash"])
        except (ValueError, KeyError, TypeError):
            raise IntegrationError("Devnet returned an invalid recent blockhash.") from None
        instruction = Instruction(Pubkey.from_string(MEMO_PROGRAM), receipt["memo"].encode("utf-8"),
                                  [AccountMeta(signer, True, False)])
        message = MessageV0.try_compile(signer, [instruction], [], recent_hash)
        transaction = VersionedTransaction(message, [wallet])
        from solders.message import to_bytes_versioned
        encoded_message = base64.b64encode(to_bytes_versioned(message)).decode("ascii")
        fee = _rpc("getFeeForMessage", [encoded_message, {"commitment": "confirmed"}], _transport)
        balance = _rpc("getBalance", [str(signer), {"commitment": "confirmed"}], _transport)
        if not isinstance(fee, dict) or type(fee.get("value")) is not int or fee["value"] < 0:
            raise IntegrationError("Devnet fee estimate is unavailable; no transaction sent.")
        if not isinstance(balance, dict) or type(balance.get("value")) is not int or balance["value"] < fee["value"]:
            raise IntegrationError("Dedicated wallet needs devnet test tokens for the estimated fee; no airdrop or transaction requested.")
        signature = str(transaction.signatures[0])
        receipt.update(status="prepared", signer=str(signer), signature=signature,
                       explorer_url="https://explorer.solana.com/tx/" + signature + "?cluster=devnet",
                       fee_lamports_estimate=fee["value"], receipt_path=str(path))
        _write_json(path, receipt)
        try:
            sent = _rpc("sendTransaction", [base64.b64encode(bytes(transaction)).decode("ascii"),
                        {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed", "maxRetries": 0}], _transport)
            if sent != signature:
                raise IntegrationError("Devnet returned a different transaction signature; inspect the saved receipt.")
            receipt.update(status="submitted", request_sent=True)
            _write_json(path, receipt)
            verification = verify_report_receipt(report, receipt, live=True, _transport=_transport)
            receipt.update(verification=verification, chain_verified=verification["chain_verified"], status=verification["status"])
            _write_json(path, receipt)
            return receipt
        except Exception:
            receipt.update(status="unknown", request_sent=True)
            _write_json(path, receipt)
            raise IntegrationError("Devnet submission or confirmation is unresolved. The saved signature must be checked; no automatic resend attempted.") from None
