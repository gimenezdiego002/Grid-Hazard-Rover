"""The saved judge fallback must reflect real outcomes and stay wholly offline."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket

import pytest

from relay_gateway.integrations import ledger
from relay_gateway.providers import GeminiProvider


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rehearse-demo.py"
spec = importlib.util.spec_from_file_location("relay_rehearsal_script", SCRIPT)
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Rehearsal attempted network, live model, or live spending-ledger access")
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(GeminiProvider, "__init__", denied)
    monkeypatch.setattr(ledger.SpendLedger, "__init__", denied)


@pytest.fixture
def packet():
    return rehearsal.build_packet()


def test_packet_runs_real_fixture_and_preserves_refusal_boundary(packet):
    assert packet["status"] == "passed"
    assert len(packet["checks"]) >= 25 and all(check["passed"] for check in packet["checks"])
    assert packet["fixture"]["readings"] == 12
    for mode in ("preset", "directed"):
        assert packet["missions"][mode]["final"]["status"] == "completed"
    refused = packet["missions"]["zero_request_refusal"]
    assert refused["analysis"]["accounting"]["new_requests"] == 0
    assert refused["after_review"]["status"] == "needs_review"
    assert refused["blocked_announcement"] == {"rejected": True, "state_preserved": True}
    assert packet["comparison"]["baseline"]["accounting"]["tokens"] == 3743
    assert packet["comparison"]["economy"]["accounting"]["tokens"] == 312
    assert packet["integration"]["telemetry_persistence"]["replay_inserted"] == 0


def test_hostile_environment_cannot_enable_live_work_or_change_existing_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sentinel = "CREDENTIAL_SENTINEL_NOT_FOR_ARTIFACTS"
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "MONGODB_URI", "POLLARD_MONGODB_URI",
                 "TIGER_DATABASE_URL", "SNOWFLAKE_TOKEN", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID",
                 "ELEVENLABS_MODEL_ID", "SOLANA_RPC_URL"):
        monkeypatch.setenv(name, sentinel)
    for name in ("RELAY_ALLOW_LIVE_GEMINI", "RELAY_ALLOW_ELEVENLABS", "RELAY_ALLOW_SOLANA_DEVNET"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("RELAY_PROVIDER", "gemini")
    monkeypatch.setenv("RELAY_STORE_PATH", "mongodb")
    state = tmp_path / ".state"
    state.mkdir()
    (state / "spend.sqlite").write_bytes(b"unchanged-ledger")
    (state / "cloud-config.json").write_text(sentinel)
    before = {path.name: path.read_bytes() for path in state.iterdir()}
    packet = rehearsal.build_packet()
    assert packet["status"] == "passed"
    assert sentinel not in json.dumps(packet)
    assert {path.name: path.read_bytes() for path in state.iterdir()} == before
    assert set(tmp_path.iterdir()) == {state}


@pytest.mark.parametrize("fault", ["completed_refusal", "hidden_live_call", "broken_tamper_check", "duplicate_telemetry", "lost_incident"])
def test_verifier_detects_broken_evidence(packet, fault):
    damaged = deepcopy(packet)
    if fault == "completed_refusal":
        damaged["missions"]["zero_request_refusal"]["final"]["status"] = "completed"
    elif fault == "hidden_live_call":
        damaged["missions"]["preset"]["analysis"]["provider_mode"] = "gemini"
    elif fault == "broken_tamper_check":
        damaged["integration"]["tamper_verification"]["valid"] = True
    elif fault == "duplicate_telemetry":
        damaged["integration"]["telemetry_persistence"]["replay_inserted"] = 12
    elif fault == "lost_incident":
        damaged["comparison"]["economy"]["evaluation"]["detected_hazard_episodes"] = 0
    assert any(not check["passed"] for check in rehearsal.verify_packet(damaged))


def test_cli_exits_nonzero_for_actual_adapter_failure(tmp_path, monkeypatch, capsys):
    original = rehearsal.run_integration_demo

    def failed_adapter(*args, **kwargs):
        result = original(*args, **kwargs)
        result["steps"][2]["status"] = "failed"
        return result

    monkeypatch.setattr(rehearsal, "run_integration_demo", failed_adapter)
    assert rehearsal.main(["--output-dir", str(tmp_path)]) == 1
    saved = next(tmp_path.glob("run-*/packet.json"))
    packet = json.loads(saved.read_text(encoding="utf-8"))
    assert packet["status"] == "failed"
    assert not next(check for check in packet["checks"] if check["name"] == "integration: six completed mock adapters")["passed"]
    assert "failed" in capsys.readouterr().out


def test_html_escapes_evidence_and_runs_preserve_unrelated_files(packet, tmp_path):
    sentinel = tmp_path / "index.html"
    sentinel.write_text("unrelated")
    malicious = '</pre><script src="https://example.test/steal"></script><img src=x onerror=alert(1)>'
    packet["limitations"].append(malicious)
    packet["missions"]["preset"]["final"]["environment_safety"] = malicious
    first = rehearsal.save_packet(packet, tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in first.iterdir()}
    second = rehearsal.save_packet(packet, tmp_path)
    assert first != second
    assert sentinel.read_text() == "unrelated"
    assert first_bytes == {path.name: path.read_bytes() for path in first.iterdir()}
    html = (first / "index.html").read_text(encoding="utf-8")
    assert "<script" not in html and "<img" not in html
    assert "&lt;/pre&gt;&lt;script" in html
    assert "Content-Security-Policy" in html
    assert "SIMULATION" in html and "NO HARDWARE OR LIVE PROVIDER PROOF" in html
    assert malicious not in rehearsal.LIMITS


def test_nonsynthetic_fixture_is_rejected_before_any_replay(tmp_path, monkeypatch):
    fixture = json.loads(rehearsal.FIXTURE.read_text(encoding="utf-8"))
    fixture["observations"][0]["simulated"] = False
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(rehearsal, "FIXTURE", path)

    def denied(*args, **kwargs):
        pytest.fail("Invalid fixture was used for a replay")

    monkeypatch.setattr(rehearsal, "run_scenario", denied)
    monkeypatch.setattr(rehearsal, "compare_scenario", denied)
    monkeypatch.setattr(rehearsal, "run_integration_demo", denied)
    with pytest.raises(ValueError, match="canonical twelve-reading synthetic"):
        rehearsal.build_packet()


def test_fixture_is_bounded_and_errors_do_not_leak_exception_text(tmp_path, monkeypatch, capsys):
    oversized = tmp_path / "fixture.json"
    oversized.write_bytes(b" " * 32_769)
    monkeypatch.setattr(rehearsal, "FIXTURE", oversized)
    with pytest.raises(ValueError, match="32 KiB"):
        rehearsal.load_fixture()

    def fail():
        raise RuntimeError("SECRET_SENTINEL_IN_ERROR")

    monkeypatch.setattr(rehearsal, "build_packet", fail)
    assert rehearsal.main(["--output-dir", str(tmp_path / "output")]) == 1
    assert "SECRET_SENTINEL" not in capsys.readouterr().err
    assert not (tmp_path / "output").exists()
