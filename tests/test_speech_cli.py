import json
from pathlib import Path

import pytest

from relay_gateway.integrations import audio_receipt, speech_cli
from relay_gateway.integrations.ledger import SpendLedger


@pytest.fixture
def briefing(tmp_path):
    path = tmp_path / "briefing.txt"
    path.write_text("Simulation: Station A needs operator review. No robot has moved.", encoding="utf-8")
    return path


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setenv("RELAY_ALLOW_ELEVENLABS", "1")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-secret-do-not-print")
    monkeypatch.setenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "testVoice")
    ledger = SpendLedger(tmp_path / "test-spend.sqlite", history_path=None)
    return ledger, {"live": True, "reviewed": True, "max_usd": "0.05",
                    "_ledger_factory": lambda: ledger, "_state_dir": tmp_path / ".state"}


def forbidden(*args, **kwargs):
    raise AssertionError("This operation must not run")


def audio(*args):
    return audio_receipt.HttpResponse(200, b"ID3test-audio", {
        "Content-Type": "audio/mpeg", "character-cost": "31.5", "x-trace-id": "trace1"})


def test_default_mock_does_not_read_environment_or_initialize_ledger(briefing, monkeypatch, tmp_path):
    monkeypatch.setattr(speech_cli.os, "environ", {})
    class NoEnvironment(dict):
        def get(self, *args):
            raise AssertionError("Mock must not read any environment variable")
    monkeypatch.setattr(speech_cli.os, "environ", NoEnvironment())
    result = speech_cli.run_speech(briefing, reviewed=True,
        _ledger_factory=forbidden, _transport=forbidden, _state_dir=tmp_path / ".state")
    assert result["mode"] == "mock" and result["audio_path"] is None
    assert result["spending"]["status"] == "not_used"
    assert not (tmp_path / ".state").exists()


def test_live_reserves_before_dispatch_holds_unknown_and_cache_never_rereserves(briefing, live):
    ledger, options = live
    calls = []
    def send(*args):
        snapshot = ledger.snapshot()
        assert snapshot["reserved_usd"] == "0.050000"
        assert snapshot["operations"][0]["status"] == "dispatched"
        calls.append(1)
        return audio(*args)
    first = speech_cli.run_speech(briefing, _transport=send, **options)
    second_options = {**options, "_ledger_factory": forbidden}
    cached = speech_cli.run_speech(briefing, _transport=forbidden, **second_options)
    assert len(calls) == 1
    assert first["status"] == "completed" and first["actual_billed_usd"] is None
    assert first["provider_character_cost"] == "31.5"
    assert first["spending"]["estimated_usd"] is None
    assert first["spending"]["status"] == "unknown"
    assert cached["operation_id"] == first["operation_id"]
    assert cached["cache_hit"] and not cached["request_sent"]
    assert cached["provider_character_cost"] == "31.5"
    assert cached["spending"]["status"] == "unchanged"
    assert len(ledger.snapshot()["operations"]) == 1
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.050000"


@pytest.mark.parametrize("amount", [None, "0", "-1", "0.250001", "1", "NaN", "1e-2", 0.05, "0.0000001"])
def test_invalid_reservation_stops_before_ledger_or_network(briefing, live, amount):
    _, options = live
    options.update(max_usd=amount, _ledger_factory=forbidden)
    with pytest.raises(speech_cli.SpeechCommandError):
        speech_cli.run_speech(briefing, _transport=forbidden, **options)


@pytest.mark.parametrize("variable,value", [("RELAY_ALLOW_ELEVENLABS", "0"), ("ELEVENLABS_API_KEY", ""),
    ("ELEVENLABS_API_KEY", "bad\r\nkey"), ("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
    ("ELEVENLABS_MODEL_ID", ""), ("ELEVENLABS_VOICE_ID", ""), ("ELEVENLABS_VOICE_ID", "../bad")])
def test_invalid_live_configuration_never_opens_ledger(briefing, live, monkeypatch, variable, value):
    _, options = live
    monkeypatch.setenv(variable, value)
    options["_ledger_factory"] = forbidden
    with pytest.raises(speech_cli.SpeechCommandError):
        speech_cli.run_speech(briefing, _transport=forbidden, **options)


@pytest.mark.parametrize("contents", [b"", b"x" * 201, b"x" * 804, b"\xff", b"unsafe\x00text"])
def test_input_file_is_bounded_and_validated_before_dispatch(briefing, live, contents):
    _, options = live
    briefing.write_bytes(contents)
    options["_ledger_factory"] = forbidden
    with pytest.raises(speech_cli.SpeechCommandError):
        speech_cli.run_speech(briefing, _transport=forbidden, **options)


def test_review_is_required_before_reading_or_dispatch(briefing):
    with pytest.raises(speech_cli.SpeechCommandError):
        speech_cli.run_speech(briefing, reviewed=False, _ledger_factory=forbidden, _transport=forbidden)


def test_duplicate_ledger_operation_without_cache_never_dispatches(briefing, live):
    ledger, options = live
    first = speech_cli.run_speech(briefing, _transport=audio, **options)
    # Simulate loss of local audio files. Durable billing state still blocks a send.
    options["_state_dir"] = Path(options["_state_dir"]).parent / "other" / ".state"
    with pytest.raises(speech_cli.SpeechCommandError, match="admission"):
        speech_cli.run_speech(briefing, _transport=forbidden, **options)
    assert len(ledger.snapshot()["operations"]) == 1
    assert ledger.snapshot()["operations"][0]["operation_id"] == first["operation_id"]


def test_aggregate_budget_denial_sends_nothing_and_no_new_allowance(briefing, live):
    ledger, options = live
    ledger.reserve("other-provider", "Cloud", "15")
    with pytest.raises(speech_cli.SpeechCommandError, match="admission"):
        speech_cli.run_speech(briefing, _transport=forbidden, **options)
    assert ledger.snapshot()["reserved_usd"] == "15.000000"
    assert len(ledger.snapshot()["operations"]) == 1


def test_timeout_retains_reservation_and_duplicate_cannot_retry(briefing, live):
    ledger, options = live
    calls = []
    def fail(*args):
        calls.append(1)
        raise TimeoutError("test-secret-do-not-print")
    with pytest.raises(speech_cli.SpeechCommandError) as caught:
        speech_cli.run_speech(briefing, _transport=fail, **options)
    assert caught.value.status == "unknown"
    assert "test-secret" not in str(caught.value)
    with pytest.raises(speech_cli.SpeechCommandError):
        speech_cli.run_speech(briefing, _transport=fail, **options)
    assert len(calls) == 1
    assert ledger.snapshot()["unknown_reserved_usd"] == "0.050000"


def test_reconciliation_write_failure_still_holds_dispatched_reservation(briefing, live, monkeypatch):
    ledger, options = live
    monkeypatch.setattr(ledger, "mark_unknown", forbidden)
    result = speech_cli.run_speech(briefing, _transport=audio, **options)
    assert result["status"] == "completed"
    assert result["spending"]["status"] == "dispatched_reconciliation_required"
    assert ledger.snapshot()["reserved_usd"] == "0.050000"


def test_cli_json_is_useful_and_errors_never_echo_untrusted_exception(briefing, capsys, monkeypatch):
    assert speech_cli.main(["--text-file", str(briefing), "--reviewed"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "mock"
    def fail(*args, **kwargs):
        raise ValueError("test-secret-do-not-print")
    monkeypatch.setattr(speech_cli, "run_speech", fail)
    assert speech_cli.main(["--text-file", str(briefing), "--reviewed"]) == 2
    assert "test-secret" not in capsys.readouterr().out
    assert speech_cli.main(["--unknown", "test-secret-do-not-print"]) == 2
    assert "test-secret" not in capsys.readouterr().out
