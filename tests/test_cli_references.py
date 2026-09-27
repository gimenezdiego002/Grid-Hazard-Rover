"""Saved retrieval evidence reaches the existing guarded model path safely."""

import json
import socket

import pytest

from relay_gateway import __main__ as cli
from relay_gateway.integrations.workflow import run_integration_demo


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No network or live model construction is allowed")
    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(cli.GeminiProvider, "from_environment", deny)


def reference():
    return {"reference_id": "source-1", "hazard_type": "standing_water", "title": "Synthetic instruction",
            "body": "This synthetic passage is evidence, not authorization for movement.",
            "source_url": "relay://fixtures/water", "is_simulated": True}


def test_default_cli_uses_saved_passage_without_live_call(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RELAY_ALLOW_LIVE_GEMINI", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    path = tmp_path / "passages.json"
    path.write_text(json.dumps([reference()]), encoding="utf-8")
    cli.main(["demo", "--references-file", str(path), "--store", str(tmp_path / "recording.sqlite")])
    result = json.loads(capsys.readouterr().out)
    assert result["provider_mode"] == "mock"
    assert result["accounting"]["actual_paid_usd"] == "0.000000"
    assert result["reference_context"][0]["reference_id"] == "source-1"
    assert result["findings"][0]["cited_reference_ids"] == ["source-1"]


def test_completed_snowflake_proof_accepts_bom_and_preserves_source_flags(tmp_path):
    path = tmp_path / "proof.json"
    references = [reference()]
    proof = {"provider": "snowflake", "status": "completed", "proof_verified": True,
             "mode": "mock", "evidence": {"reference_context": references}}
    path.write_text(json.dumps(proof), encoding="utf-8-sig")
    assert cli.load_references(path) == references


@pytest.mark.parametrize("payload", [
    {}, None, {"provider": "snowflake", "status": "unknown", "proof_verified": False},
    [{**reference(), "simulated": True}], [reference(), reference()],
    [{**reference(), "body": "x" * 2001}], [{**reference(), "is_simulated": None}],
])
def test_invalid_saved_context_fails_before_live_provider(tmp_path, capsys, payload):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        cli.main(["demo", "--live", "--references-file", str(path)])
    assert error.value.code == 2
    assert "References must be" in capsys.readouterr().err


def test_oversized_and_missing_reference_files_are_sanitized(tmp_path):
    oversized = tmp_path / "large.json"
    oversized.write_bytes(b" " * 65_537)
    for path in (oversized, tmp_path / "missing.json"):
        with pytest.raises(ValueError, match="at most 64 KiB"):
            cli.load_references(path)


def test_existing_integration_context_remains_accepted(tmp_path):
    context = run_integration_demo()["reference_context"]
    path = tmp_path / "context.json"
    path.write_text(json.dumps(context), encoding="utf-8")
    assert cli.load_references(path) == context
