import base64
import json
from pathlib import Path

import pytest

from relay_gateway.integrations import audio_receipt as integration


REPORT = {"report_id": "station-a-001", "simulated": True,
          "finding": "suspected_water", "reviewed": True, "wetness_milli": 850}


@pytest.fixture
def live_flags(monkeypatch):
    monkeypatch.setenv("RELAY_ALLOW_ELEVENLABS", "1")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "unit-test-key-not-a-secret")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "testVoice")
    monkeypatch.setenv("RELAY_ALLOW_SOLANA_DEVNET", "1")


def forbidden_transport(*args, **kwargs):
    raise AssertionError("Network must not run in this test")


def test_mock_defaults_never_dispatch_or_create_wallet(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(integration, "_post", forbidden_transport)
    speech = integration.synthesize_briefing("Station A needs review.", reviewed=True)
    first = integration.create_report_receipt(REPORT, finalized=True)
    second = integration.create_report_receipt(REPORT, finalized=True)
    assert first == second
    assert speech["mode"] == "mock" and speech["audio_path"] is None
    assert speech["actual_billed_usd"] == "0.00"
    assert speech["provider_character_cost"] is None
    assert speech["provider_character_cost_status"] == "not_requested"
    assert first["signature"] is None and first["chain_verified"] is False
    assert integration.prepare_devnet_wallet()["public_key"] is None
    assert not (tmp_path / ".state").exists()


def test_report_integrity_original_true_modified_false_and_order_stable():
    receipt = integration.create_report_receipt(REPORT, finalized=True)
    same = dict(reversed(list(REPORT.items())))
    assert integration.report_sha256(same) == integration.report_sha256(REPORT)
    check = integration.verify_report_receipt(same, receipt)
    assert check["valid"] is True and check["chain_verified"] is False
    assert check["status"] == "mock_hash_verified"
    changed = integration.verify_report_receipt({**REPORT, "wetness_milli": 0}, receipt)
    assert changed["valid"] is False and changed["status"] == "report_changed"


@pytest.mark.parametrize("report", [[], {"x": 1}, {"simulated": "yes"},
    {"simulated": True, "n": float("nan")}, {"simulated": True, 1: "nonstring"},
    {"simulated": True, "huge": "x" * integration.MAX_REPORT_BYTES}])
def test_unsafe_report_input_rejected(report):
    with pytest.raises(ValueError):
        integration.create_report_receipt(report, finalized=True)


@pytest.mark.parametrize("text", ["", " ", "x" * 601, "unsafe\x00input", None])
def test_speech_bounds_before_dispatch(text):
    with pytest.raises(ValueError):
        integration.synthesize_briefing(text, reviewed=True, _transport=forbidden_transport)


def test_explicit_review_and_live_switches_required(monkeypatch, tmp_path):
    monkeypatch.delenv("RELAY_ALLOW_ELEVENLABS", raising=False)
    monkeypatch.delenv("RELAY_ALLOW_SOLANA_DEVNET", raising=False)
    with pytest.raises(ValueError):
        integration.synthesize_briefing("Station A", reviewed=False)
    with pytest.raises(ValueError):
        integration.create_report_receipt(REPORT, finalized=False)
    with pytest.raises(ValueError):
        integration.synthesize_briefing("Station A", reviewed=True, live="false")
    with pytest.raises(integration.IntegrationError, match="RELAY_ALLOW_ELEVENLABS"):
        integration.synthesize_briefing("Station A", reviewed=True, live=True, voice_id="testVoice", _transport=forbidden_transport)
    with pytest.raises(integration.IntegrationError, match="RELAY_ALLOW_SOLANA_DEVNET"):
        integration.create_report_receipt(REPORT, finalized=True, live=True, _transport=forbidden_transport)
    for network in ("mainnet-beta", "testnet", "https://untrusted.invalid"):
        with pytest.raises(ValueError):
            integration.create_report_receipt(REPORT, finalized=True, network=network)
    with pytest.raises(ValueError):
        integration.synthesize_briefing("Station A", reviewed=True, voice_id="../other?key=unsafe")


def test_speech_success_cache_and_changed_voice_are_distinct(tmp_path, live_flags):
    calls = []
    audio = b"ID3" + b"test-mp3-body"
    def send(url, headers, body, timeout):
        calls.append((url, json.loads(body)))
        assert url.startswith("https://api.elevenlabs.io/v1/text-to-speech/")
        assert "xi-api-key" in headers and timeout == 20
        return integration.HttpResponse(200, audio, {"Content-Type": "audio/mpeg", "request-id": "request123",
            "Character-Cost": "10.5", "X-Trace-Id": "trace-123_abc", "unrelated-secret": "never-record-this"})
    options = {"reviewed": True, "live": True, "state_dir": tmp_path / ".state", "_transport": send}
    first = integration.synthesize_briefing("Station A needs review.", **options)
    cached = integration.synthesize_briefing("Station A needs review.", **options)
    other = integration.synthesize_briefing("Station A needs review.", voice_id="anotherVoice", **options)
    assert len(calls) == 2
    assert first["request_sent"] is True and cached["request_sent"] is False
    assert cached["cache_hit"] is True and first["cache_key"] != other["cache_key"]
    for result in (first, cached):
        assert result["provider_character_cost"] == "10.5"
        assert result["provider_character_cost_status"] == "reported"
        assert result["provider_character_cost_unit"] == "provider_defined"
        assert result["provider_trace_id"] == "trace-123_abc"
        assert result["provider_request_id"] == "request123"
        assert result["actual_billed_usd"] is None
        assert "estimated_usd" not in result
    assert Path(first["audio_path"]).read_bytes() == audio
    metadata = Path(first["audio_path"]).with_suffix(".json").read_text()
    assert "unit-test-key-not-a-secret" not in metadata
    assert "Station A needs review" not in metadata
    assert "never-record-this" not in metadata


@pytest.mark.parametrize("header,expected_status", [(None, "missing"), ("", "malformed"),
    ("-1", "malformed"), ("NaN", "malformed"), ("Infinity", "malformed"),
    ("1e2", "malformed"), ("1,000", "malformed"), ("0.0000001", "malformed"),
    ("9" * 129, "malformed"), ("1\r\nsecret", "malformed"), (123, "malformed")])
def test_unknown_speech_usage_stays_unknown_and_cache_does_not_regenerate(tmp_path, live_flags, header, expected_status):
    calls = []
    def send(*args):
        calls.append(1)
        headers = {"content-type": "audio/mpeg", "x-trace-id": "invalid\r\ntrace"}
        if header is not None:
            headers["character-cost"] = header
        return integration.HttpResponse(200, b"ID3test", headers)
    options = {"reviewed": True, "live": True, "state_dir": tmp_path / ".state", "_transport": send}
    first = integration.synthesize_briefing("Review Station A.", **options)
    cached = integration.synthesize_briefing("Review Station A.", **options)
    for result in (first, cached):
        assert result["status"] == "completed"
        assert result["provider_character_cost"] is None
        assert result["provider_character_cost_status"] == expected_status
        assert result["provider_trace_id"] is None
        assert result["actual_billed_usd"] is None
    assert len(calls) == 1 and cached["request_sent"] is False
    metadata = Path(first["audio_path"]).with_suffix(".json").read_text()
    assert "invalid" not in metadata and "secret" not in metadata


@pytest.mark.parametrize("header", ["0", "165", "82.5", "0.000001"])
def test_reported_character_cost_is_not_automatically_currency(tmp_path, live_flags, header):
    def send(*args):
        return integration.HttpResponse(200, b"ID3test", {"content-type": "audio/mpeg", "character-cost": header})
    result = integration.synthesize_briefing("Review Station A.", reviewed=True, live=True,
        state_dir=tmp_path / ".state", _transport=send)
    assert result["provider_character_cost"] == header
    assert result["provider_character_cost_status"] == "reported"
    assert result["actual_billed_usd"] is None
    assert "estimated_usd" not in result


def test_speech_timeout_not_automatically_retried_or_secret_exposed(tmp_path, live_flags):
    calls = []
    def fail(*args):
        calls.append(1)
        raise TimeoutError("unit-test-key-not-a-secret")
    options = {"reviewed": True, "live": True, "state_dir": tmp_path / ".state", "_transport": fail}
    with pytest.raises(integration.IntegrationError) as first:
        integration.synthesize_briefing("Station A needs review.", **options)
    assert "unit-test-key-not-a-secret" not in str(first.value)
    with pytest.raises(integration.IntegrationError, match="earlier speech dispatch"):
        integration.synthesize_briefing("Station A needs review.", **options)
    assert len(calls) == 1


def test_cache_corruption_does_not_regenerate(tmp_path, live_flags):
    def send(*args):
        return integration.HttpResponse(200, b"ID3test", {"content-type": "audio/mpeg"})
    options = {"reviewed": True, "live": True, "state_dir": tmp_path / ".state"}
    result = integration.synthesize_briefing("Review Station A.", _transport=send, **options)
    Path(result["audio_path"]).write_bytes(b"tampered")
    with pytest.raises(integration.IntegrationError, match="integrity"):
        integration.synthesize_briefing("Review Station A.", _transport=forbidden_transport, **options)


@pytest.mark.parametrize("response", [integration.HttpResponse(200, b"<html>failure</html>", {"content-type": "text/html"}),
    integration.HttpResponse(429, b"limited", {"content-type": "application/json"}),
    integration.HttpResponse(200, b"ID3" + b"x" * integration.MAX_AUDIO_BYTES, {"content-type": "audio/mpeg"})])
def test_invalid_audio_response_leaves_unresolved_attempt(tmp_path, live_flags, response):
    calls = []
    def send(*args):
        calls.append(1)
        return response
    options = {"reviewed": True, "live": True, "state_dir": tmp_path / ".state", "_transport": send}
    with pytest.raises(integration.IntegrationError):
        integration.synthesize_briefing("Review Station A.", **options)
    with pytest.raises(integration.IntegrationError):
        integration.synthesize_briefing("Review Station A.", **options)
    assert len(calls) == 1


class FakeDevnet:
    def __init__(self, *, balance=100_000, confirmed=True, send_failure=False):
        self.calls = []
        self.balance = balance
        self.confirmed = confirmed
        self.send_failure = send_failure
        self.raw = None

    def __call__(self, url, headers, body, timeout):
        from solders.hash import Hash
        from solders.transaction import VersionedTransaction
        assert url == integration.DEVNET_RPC
        request = json.loads(body)
        method = request["method"]
        self.calls.append(method)
        if method == "getLatestBlockhash":
            result = {"value": {"blockhash": str(Hash.default()), "lastValidBlockHeight": 100}}
        elif method == "getFeeForMessage":
            result = {"value": 5000}
        elif method == "getBalance":
            result = {"value": self.balance}
        elif method == "sendTransaction":
            assert request["params"][1]["skipPreflight"] is False
            assert request["params"][1]["maxRetries"] == 0
            self.raw = request["params"][0]
            transaction = VersionedTransaction.from_bytes(base64.b64decode(self.raw))
            assert all(transaction.verify_with_results())
            if self.send_failure:
                raise TimeoutError("RPC unknown")
            result = str(transaction.signatures[0])
        elif method == "getTransaction":
            result = {"meta": {"err": None}, "transaction": [self.raw, "base64"], "slot": 42} if self.confirmed and self.raw else None
        else:
            raise AssertionError("Unexpected RPC method " + method)
        return integration.HttpResponse(200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode())


@pytest.fixture
def sdk_wallet(monkeypatch):
    pytest.importorskip("solders")
    # SDK signing is real; OS ACL setup has its own live platform path.
    monkeypatch.setattr(integration, "_private_file", lambda path: None)


def test_real_sdk_signature_memo_verification_and_receipt_reuse(tmp_path, live_flags, sdk_wallet):
    rpc = FakeDevnet()
    options = {"finalized": True, "live": True, "state_dir": tmp_path / ".state", "_transport": rpc}
    receipt = integration.create_report_receipt(REPORT, **options)
    assert receipt["chain_verified"] is True and receipt["status"] == "confirmed"
    assert receipt["explorer_url"].endswith("?cluster=devnet")
    key_file = tmp_path / ".state" / "solana" / "devnet-keypair.json"
    secret = key_file.read_text()
    assert len(json.loads(secret)) == 64 and secret not in json.dumps(receipt)
    verification = integration.verify_report_receipt(REPORT, receipt, live=True, _transport=rpc)
    assert verification["valid"] is True and verification["chain_verified"] is True
    changed = integration.verify_report_receipt({**REPORT, "wetness_milli": 0}, receipt, live=True, _transport=forbidden_transport)
    assert changed["valid"] is False
    repeated = integration.create_report_receipt(REPORT, **options)
    assert repeated["reused_receipt"] is True
    assert rpc.calls.count("sendTransaction") == 1
    assert "requestAirdrop" not in rpc.calls
    local_only = integration.verify_report_receipt(REPORT, receipt)
    assert local_only["valid"] is None and local_only["chain_verified"] is False


def test_unknown_devnet_send_cannot_duplicate_transaction(tmp_path, live_flags, sdk_wallet):
    rpc = FakeDevnet(send_failure=True, confirmed=False)
    options = {"finalized": True, "live": True, "state_dir": tmp_path / ".state", "_transport": rpc}
    with pytest.raises(integration.IntegrationError, match="unresolved"):
        integration.create_report_receipt(REPORT, **options)
    repeated = integration.create_report_receipt(REPORT, **options)
    assert repeated["status"] == "not_yet_confirmed"
    assert repeated["chain_verified"] is False
    assert rpc.calls.count("sendTransaction") == 1


def test_live_verification_rejects_valid_transaction_for_different_report(tmp_path, live_flags, sdk_wallet):
    rpc = FakeDevnet()
    other_report = {**REPORT, "wetness_milli": 0}
    other_receipt = integration.create_report_receipt(other_report, finalized=True, live=True,
        state_dir=tmp_path / ".state", _transport=rpc)
    # The fetched transaction has a valid signature, but its actual memo is for
    # another report. Locally changing the claimed hash must not pass proof.
    claimed = integration.create_report_receipt(REPORT, finalized=True)
    forged = {**other_receipt, "report_sha256": claimed["report_sha256"], "memo": claimed["memo"]}
    result = integration.verify_report_receipt(REPORT, forged, live=True, _transport=rpc)
    assert result["hash_matches"] is True
    assert result["valid"] is False and result["chain_verified"] is False
    assert result["status"] == "memo_mismatch"


def test_unfunded_devnet_wallet_never_sends_or_airdrops(tmp_path, live_flags, sdk_wallet):
    rpc = FakeDevnet(balance=0)
    with pytest.raises(integration.IntegrationError, match="devnet test tokens"):
        integration.create_report_receipt(REPORT, finalized=True, live=True, state_dir=tmp_path / ".state", _transport=rpc)
    assert "sendTransaction" not in rpc.calls and "requestAirdrop" not in rpc.calls


def test_corrupt_key_is_not_replaced(tmp_path, live_flags, sdk_wallet):
    directory = tmp_path / ".state" / "solana"
    directory.mkdir(parents=True)
    key = directory / "devnet-keypair.json"
    key.write_text("not a wallet")
    with pytest.raises(integration.IntegrationError, match="not replaced"):
        integration.prepare_devnet_wallet(live=True, state_dir=tmp_path / ".state")
    assert key.read_text() == "not a wallet"
