"""Receipt command tests prohibit sockets and use temporary input files."""

import json
import socket

import pytest

from relay_gateway.integrations import audio_receipt, ledger, receipt_cli


REPORT = {"schema": "relay.report.v1", "mission_id": "receipt-proof", "simulated": True,
          "review": {"human_review_performed": False}, "wetness_milli": 850}


def forbidden(*args, **kwargs):
    raise AssertionError("Forbidden operation")


@pytest.fixture(autouse=True)
def no_network_or_ledger(monkeypatch):
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(ledger, "SpendLedger", forbidden)


@pytest.fixture
def report_file(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(REPORT), encoding="utf-8")
    return path


def save_receipt(tmp_path, receipt):
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def live_receipt(report, status="confirmed", **extra):
    result = audio_receipt.create_report_receipt(report, finalized=True)
    confirmed = status == "confirmed"
    return {**result, "mode": "live", "status": status, "signature": "A" * 88, "signer": "B" * 44,
            "chain_verified": confirmed, "request_sent": True, "fee_lamports_estimate": 5000,
            "verification": {"status": status, "hash_matches": True, "chain_verified": confirmed,
                             "valid": True if confirmed else None}, **extra}


def test_mock_create_and_verify_never_read_env_wallet_or_state(report_file, tmp_path, monkeypatch):
    class NoEnvironment(dict):
        def get(self, *args):
            raise AssertionError("Mock must not read environment")
    monkeypatch.setattr(receipt_cli.os, "environ", NoEnvironment())
    monkeypatch.setattr(audio_receipt, "_state_root", forbidden)
    monkeypatch.setattr(audio_receipt, "_wallet", forbidden)
    monkeypatch.setattr(audio_receipt, "_rpc", forbidden)
    result = receipt_cli.run_create(report_file, finalized=True)
    receipt_file = save_receipt(tmp_path, result)
    verified = receipt_cli.run_verify(report_file, receipt_file)
    assert result["status"] == "mock" and result["receipt"]["signature"] is None
    assert not result["chain_verified"] and result["report_simulated"]
    assert verified["verification"]["valid"] is True
    assert verified["status"] == "mock_hash_verified" and not verified["chain_verified"]
    assert not (tmp_path / ".state").exists()


def test_mock_receipt_rejects_modified_report_without_network(report_file, tmp_path):
    receipt_file = save_receipt(tmp_path, receipt_cli.run_create(report_file, finalized=True))
    report_file.write_text(json.dumps({**REPORT, "wetness_milli": 0}), encoding="utf-8")
    result = receipt_cli.run_verify(report_file, receipt_file)
    assert result["status"] == "report_changed"
    assert result["verification"]["valid"] is False


def test_completed_mock_replay_extracts_exact_report(report_file):
    expected = receipt_cli.run_create(report_file, finalized=True)["report_sha256"]
    report_file.write_text(json.dumps({"schema_version": "1", "mode": "mock", "simulated": True,
                                      "status": "completed", "report": REPORT}), encoding="utf-8")
    assert receipt_cli.run_create(report_file, finalized=True)["report_sha256"] == expected


def test_creation_requires_explicit_finalization_before_adapter(report_file, monkeypatch):
    monkeypatch.setattr(audio_receipt, "create_report_receipt", forbidden)
    with pytest.raises(receipt_cli.ReceiptCommandError, match="finalized"):
        receipt_cli.run_create(report_file)


@pytest.mark.parametrize("contents", [b"", b"[]", b"{}", b"\xff", b"x" * (256 * 1024 + 1),
    b'{"simulated":true,"value":NaN}', b'{"simulated":true,"value":1e999}',
    b'{"simulated":true,"simulated":false}', b'{"simulated":true,"child":{"x":1,"x":2}}',
    b'{"simulated":"true"}'], ids=["empty", "list", "missing-flag", "invalid-utf8", "oversized",
                                      "nan", "infinite-exponent", "duplicate-root", "duplicate-nested", "wrong-flag"])
def test_invalid_report_is_blocked_before_adapter(report_file, monkeypatch, contents):
    report_file.write_bytes(contents)
    monkeypatch.setattr(audio_receipt, "create_report_receipt", forbidden)
    with pytest.raises(receipt_cli.ReceiptCommandError):
        receipt_cli.run_create(report_file, finalized=True, live=True)


def test_deeply_nested_json_is_blocked(report_file):
    nested = REPORT
    for _ in range(22):
        nested = {"child": nested}
    report_file.write_text(json.dumps({"simulated": True, "value": nested}), encoding="utf-8")
    with pytest.raises(receipt_cli.ReceiptCommandError):
        receipt_cli.run_create(report_file, finalized=True)


@pytest.mark.parametrize("operation", ["create", "verify"])
def test_live_requires_both_flag_and_environment_switch(report_file, tmp_path, monkeypatch, operation):
    receipt_file = save_receipt(tmp_path, audio_receipt.create_report_receipt(REPORT, finalized=True))
    monkeypatch.delenv("RELAY_ALLOW_SOLANA_DEVNET", raising=False)
    monkeypatch.setattr(audio_receipt, "create_report_receipt", forbidden)
    monkeypatch.setattr(audio_receipt, "verify_report_receipt", forbidden)
    with pytest.raises(receipt_cli.ReceiptCommandError, match="RELAY_ALLOW_SOLANA_DEVNET"):
        if operation == "create":
            receipt_cli.run_create(report_file, finalized=True, live=True)
        else:
            receipt_cli.run_verify(report_file, receipt_file, live=True)


@pytest.mark.parametrize("status", ["confirmed", "not_yet_confirmed", "transaction_failed"])
def test_live_creation_one_adapter_call_and_status_preserved(report_file, monkeypatch, status):
    monkeypatch.setenv("RELAY_ALLOW_SOLANA_DEVNET", "1")
    expected = live_receipt(REPORT, status=status)
    calls = []
    def create(report, **options):
        calls.append(options)
        assert report == REPORT
        return expected
    monkeypatch.setattr(audio_receipt, "create_report_receipt", create)
    result = receipt_cli.run_create(report_file, finalized=True, live=True)
    assert len(calls) == 1 and calls[0]["live"] is True and calls[0]["finalized"] is True
    assert result["status"] == status and result["chain_verified"] == (status == "confirmed")
    assert result["receipt"]["fee_lamports_estimate"] == 5000
    assert result["fee_unit"] == "devnet_lamports" and result["fee_is_test_tokens"]
    assert result["actual_billed_usd"] is None and not result["spend_ledger_modified"]


def test_live_creation_uses_canonical_state_independent_of_launch_directory(report_file, tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_ALLOW_SOLANA_DEVNET", "1")
    root = tmp_path / "workspace"
    monkeypatch.setattr(receipt_cli, "PROJECT_ROOT", root)
    expected = live_receipt(REPORT)
    paths = []
    def create(report, **options):
        paths.append(options["state_dir"])
        return expected
    monkeypatch.setattr(audio_receipt, "create_report_receipt", create)
    for name in ("first", "second"):
        cwd = tmp_path / name
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        receipt_cli.run_create(report_file, finalized=True, live=True)
        assert not (cwd / ".state").exists()
    assert paths == [root / ".state", root / ".state"]


def test_reused_receipt_is_preserved_and_adapter_is_not_retried(report_file, monkeypatch):
    monkeypatch.setenv("RELAY_ALLOW_SOLANA_DEVNET", "1")
    expected = live_receipt(REPORT, reused_receipt=True, request_sent=False)
    calls = []
    def create(*args, **kwargs):
        calls.append(1)
        return expected
    monkeypatch.setattr(audio_receipt, "create_report_receipt", create)
    result = receipt_cli.run_create(report_file, finalized=True, live=True)
    assert result["receipt"]["reused_receipt"] and not result["receipt"]["request_sent"]
    assert len(calls) == 1


def test_unfunded_error_is_clear_but_never_funds_or_retries(report_file, monkeypatch):
    monkeypatch.setenv("RELAY_ALLOW_SOLANA_DEVNET", "1")
    calls = []
    def create(*args, **kwargs):
        calls.append(1)
        raise audio_receipt.IntegrationError(receipt_cli._UNFUNDED)
    monkeypatch.setattr(audio_receipt, "create_report_receipt", create)
    with pytest.raises(receipt_cli.ReceiptCommandError, match="needs test tokens") as caught:
        receipt_cli.run_create(report_file, finalized=True, live=True)
    assert caught.value.status == "blocked" and len(calls) == 1


def test_live_verify_is_one_read_only_adapter_call(report_file, tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_ALLOW_SOLANA_DEVNET", "1")
    receipt_file = save_receipt(tmp_path, live_receipt(REPORT))
    before = receipt_file.read_bytes()
    calls = []
    def verify(report, receipt, **options):
        calls.append(options)
        return {"status": "not_yet_confirmed", "hash_matches": True, "chain_verified": False, "valid": None}
    monkeypatch.setattr(audio_receipt, "verify_report_receipt", verify)
    monkeypatch.setattr(audio_receipt, "_state_root", forbidden)
    monkeypatch.setattr(audio_receipt, "_wallet", forbidden)
    monkeypatch.setattr(audio_receipt, "create_report_receipt", forbidden)
    result = receipt_cli.run_verify(report_file, receipt_file, live=True)
    assert calls == [{"live": True}] and result["status"] == "not_yet_confirmed"
    assert not result["transaction_submitted"] and not result["funding_requested"]
    assert receipt_file.read_bytes() == before


def test_local_verification_of_live_receipt_never_claims_chain_proof(report_file, tmp_path):
    receipt_file = save_receipt(tmp_path, live_receipt(REPORT))
    result = receipt_cli.run_verify(report_file, receipt_file)
    assert result["status"] == "chain_not_checked" and not result["chain_verified"]
    assert result["verification"]["valid"] is None


@pytest.mark.parametrize("value", [[], {}, {"schema": "relay.receipt.v1", "network": "mainnet", "mode": "live"},
    {"schema": receipt_cli.COMMAND_SCHEMA, "operation": "verify", "receipt": {}}])
def test_invalid_receipt_never_calls_verifier(report_file, tmp_path, monkeypatch, value):
    receipt_file = save_receipt(tmp_path, value)
    monkeypatch.setattr(audio_receipt, "verify_report_receipt", forbidden)
    with pytest.raises(receipt_cli.ReceiptCommandError):
        receipt_cli.run_verify(report_file, receipt_file)


def test_success_output_allowlists_fields_and_builds_own_explorer_url(report_file, monkeypatch):
    monkeypatch.setenv("RELAY_ALLOW_SOLANA_DEVNET", "1")
    expected = live_receipt(REPORT, note="secret-value", credential="secret-value", receipt_path="secret-value",
                            explorer_url="https://unsafe.example/secret-value")
    monkeypatch.setattr(audio_receipt, "create_report_receipt", lambda *args, **kwargs: expected)
    result = receipt_cli.run_create(report_file, finalized=True, live=True)
    assert "secret-value" not in json.dumps(result)
    assert result["receipt"]["explorer_url"].startswith("https://explorer.solana.com/tx/")


@pytest.mark.parametrize("operation", ["create", "verify"])
def test_errors_are_sanitized_and_not_retried(report_file, tmp_path, monkeypatch, capsys, operation):
    receipt_file = save_receipt(tmp_path, audio_receipt.create_report_receipt(REPORT, finalized=True))
    monkeypatch.setenv("RELAY_ALLOW_SOLANA_DEVNET", "1")
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("secret-value")
    monkeypatch.setattr(audio_receipt, "create_report_receipt" if operation == "create" else "verify_report_receipt", fail)
    args = [operation, "--report-file", str(report_file), "--live"]
    args += ["--finalized"] if operation == "create" else ["--receipt-file", str(receipt_file)]
    assert receipt_cli.main(args) == 2
    output = capsys.readouterr().out
    assert "secret-value" not in output and json.loads(output)["status"] == "unknown"
    assert len(calls) == 1


def test_cli_mock_roundtrip_and_unsupported_options_are_sanitized(report_file, tmp_path, capsys):
    assert receipt_cli.main(["create", "--report-file", str(report_file), "--finalized"]) == 0
    result = json.loads(capsys.readouterr().out)
    receipt_file = save_receipt(tmp_path, result)
    assert receipt_cli.main(["verify", "--report-file", str(report_file), "--receipt-file", str(receipt_file)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "mock_hash_verified"
    assert receipt_cli.main(["create", "--report-file", str(report_file), "--state-dir", "secret-value"]) == 2
    assert "secret-value" not in capsys.readouterr().out
    assert receipt_cli.main(["create", "--report-file", str(report_file), "--network", "mainnet"]) == 2
    assert "mainnet" not in capsys.readouterr().out
