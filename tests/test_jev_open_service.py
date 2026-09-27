"""Loopback service tests use fixtures only: no weights, CUDA or downloads."""

from concurrent.futures import ThreadPoolExecutor
import builtins
import json
import sys
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from relay_gateway import jev_open_service as service
from relay_gateway.jev_provider import FixtureJevProvider


def packet(**overrides):
    result = {
        "state": json.dumps({"health": "fresh", "local_alarm": False,
                             "water_threshold_exceeded": False, "changed": True,
                             "simulated": True, "actuation_enabled": False}),
        "choices": ["hold", "continue_monitoring"],
        "operation_id": "local:fixture:1",
        "timeout_seconds": 5.0,
    }
    result.update(overrides)
    return result


@pytest.fixture
def fixture_provider():
    return FixtureJevProvider()


@pytest.fixture
def client(fixture_provider):
    with TestClient(service.create_app(fixture_provider), base_url="http://127.0.0.1:8770") as connection:
        yield connection


def test_health_labels_fixture_honestly_and_exposes_no_actuation(client, fixture_provider):
    result = client.get("/health")
    assert result.status_code == 200
    health = result.json()
    assert health["ready"] is True and health["inference_simulated"] is True
    assert health["model"] == fixture_provider.model
    assert health["hosted_api_requests"] == 0 and health["actuation_enabled"] is False
    assert health["requests"] == 0 and health["busy"] is False
    assert fixture_provider.calls == 0


def test_valid_decision_uses_fixture_and_tracks_one_admission(client, fixture_provider):
    result = client.post("/decide", json=packet())
    assert result.status_code == 200
    body = result.json()
    assert body["simulated"] is True and body["status"] == "completed"
    assert body["choice"] == "continue_monitoring"
    assert body["metrics"]["actual_paid_usd"] == "0"
    assert fixture_provider.calls == 1 and client.get("/health").json()["requests"] == 1


@pytest.mark.parametrize("host", ["attacker.example", "127.0.0.1.attacker.example", "localhost.attacker.example", "0.0.0.0"])
def test_foreign_host_is_rejected_before_provider(client, fixture_provider, host):
    assert client.post("/decide", json=packet(), headers={"host": host}).status_code == 400
    assert client.get("/health", headers={"host": host}).status_code == 400
    assert fixture_provider.calls == 0


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8770", "localhost", "localhost:8770"])
def test_only_explicit_loopback_hosts_are_allowed(client, host):
    assert client.get("/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("origin", ["https://attacker.example", "http://localhost:8770", "null"])
def test_browser_origins_cannot_start_inference(client, fixture_provider, origin):
    result = client.post("/decide", json=packet(), headers={"origin": origin})
    assert result.status_code == 403
    assert fixture_provider.calls == 0 and client.get("/health").json()["requests"] == 0


def test_preflight_does_not_grant_browser_access(client, fixture_provider):
    result = client.options("/decide", headers={"origin": "https://attacker.example",
                                                "access-control-request-method": "POST"})
    assert result.status_code == 405
    assert "access-control-allow-origin" not in result.headers
    assert fixture_provider.calls == 0


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "", "application/octet-stream"])
def test_non_json_body_never_reaches_provider(client, fixture_provider, content_type):
    response = client.post("/decide", content=json.dumps(packet()), headers={"content-type": content_type})
    assert response.status_code == 415
    assert fixture_provider.calls == 0


def test_content_type_json_charset_is_accepted(client):
    response = client.post("/decide", content=json.dumps(packet()), headers={"content-type": "application/json; charset=utf-8"})
    assert response.status_code == 200


def test_streamed_body_is_bounded_even_without_content_length(client, fixture_provider):
    def chunks():
        yield b'{"state":"'
        yield b"x" * 10000
        yield b"x" * 10000
        yield b'"}'

    response = client.post("/decide", content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert fixture_provider.calls == 0 and client.get("/health").json()["requests"] == 0


@pytest.mark.parametrize("change", [
    {"state": "x" * 8193}, {"state": "x"}, {"state": {}},
    {"choices": []}, {"choices": ["hold"] * 5}, {"choices": [1]},
    {"operation_id": "bad/id"}, {"operation_id": "x" * 161},
    {"timeout_seconds": 0}, {"timeout_seconds": 10.1}, {"timeout_seconds": "5"},
    {"unexpected": "private-input"},
], ids=["state-long", "state-short", "state-type", "choices-empty", "choices-long", "choice-type",
        "id-invalid", "id-long", "timeout-zero", "timeout-long", "timeout-type", "extra-field"])
def test_request_schema_rejects_bad_packets_without_quota_use(client, fixture_provider, change):
    response = client.post("/decide", json=packet(**change))
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid bounded local decision request"}
    assert "private-input" not in response.text
    assert fixture_provider.calls == 0 and client.get("/health").json()["requests"] == 0


@pytest.mark.parametrize("change", [
    {"choices": ["drive_forward"]}, {"choices": ["hold", "hold"]},
    {"state": "🌊" * 2100},
], ids=["unreviewed-action", "duplicate-actions", "utf8-limit"])
def test_choice_and_utf8_bounds_are_checked_before_provider(client, fixture_provider, change):
    response = client.post("/decide", json=packet(**change))
    assert response.status_code == 422
    assert fixture_provider.calls == 0 and client.get("/health").json()["requests"] == 0


def test_malformed_json_is_sanitized_and_not_admitted(client, fixture_provider):
    response = client.post("/decide", content=b'{"private-secret":', headers={"content-type": "application/json"})
    assert response.status_code == 422 and "private-secret" not in response.text
    assert fixture_provider.calls == 0


def test_fixed_worker_allowance_never_dispatches_excess_request(fixture_provider):
    with TestClient(service.create_app(fixture_provider, max_requests=1), base_url="http://localhost") as client:
        assert client.post("/decide", json=packet()).status_code == 200
        response = client.post("/decide", json=packet(operation_id="second"))
        assert response.status_code == 429
        assert "exhausted" in response.json()["detail"]
        assert fixture_provider.calls == 1
        assert client.get("/health").json()["requests"] == 1


def test_busy_request_is_rejected_without_overlap_or_extra_allowance_use():
    entered, release = Event(), Event()
    fixture = FixtureJevProvider()

    class BlockingFixture:
        simulated = True
        model = "blocking-fixture"

        def decide(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return fixture.decide(*args, **kwargs)

    with TestClient(service.create_app(BlockingFixture(), max_requests=2), base_url="http://localhost") as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, "/decide", json=packet())
            assert entered.wait(5)
            try:
                assert client.get("/health").json()["busy"] is True
                second = client.post("/decide", json=packet(operation_id="second"))
                assert second.status_code == 429 and "busy" in second.json()["detail"]
                assert client.get("/health").json()["requests"] == 1
            finally:
                release.set()
            assert first.result(timeout=5).status_code == 200
        assert client.get("/health").json()["busy"] is False
        assert fixture.calls == 1
        assert client.post("/decide", json=packet(operation_id="third")).status_code == 200
        assert fixture.calls == 2


def test_provider_errors_are_sanitized_counted_and_release_lock():
    class FailingFixture:
        simulated = True

        def decide(self, *args, **kwargs):
            raise RuntimeError("private-response-or-credential")

    with TestClient(service.create_app(FailingFixture(), max_requests=1), base_url="http://localhost") as client:
        response = client.post("/decide", json=packet())
        assert response.status_code == 503
        assert response.json() == {"detail": "Local inference unavailable; retain safe hold"}
        assert "private-response" not in response.text
        health = client.get("/health").json()
        assert health["requests"] == 1 and health["busy"] is False
        assert client.post("/decide", json=packet(operation_id="second")).status_code == 429


@pytest.mark.parametrize("limit", [0, 101, 1001, True, "10"])
def test_invalid_app_allowance_is_refused_without_model_work(fixture_provider, limit):
    with pytest.raises(ValueError):
        service.create_app(fixture_provider, max_requests=limit)
    assert fixture_provider.calls == 0


def test_cli_requires_load_local_flag_before_optional_imports():
    with pytest.raises(SystemExit) as caught:
        service.main([])
    assert caught.value.code == 2


@pytest.mark.parametrize("port", [0, 1023, 65536])
def test_cli_bad_port_is_refused_before_loading(port):
    with pytest.raises(SystemExit) as caught:
        service.main(["--load-local", "--port", str(port)])
    assert caught.value.code == 2


@pytest.mark.parametrize("option,value", [("--max-requests", "0"), ("--max-requests", "101"), ("--max-requests", "1001"),
                                         ("--max-length", "127"), ("--max-length", "4097")])
def test_cli_invalid_bounds_rejected_before_optional_imports(monkeypatch, option, value):
    native_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {"torch", "uvicorn", "jev_open_provider"}:
            pytest.fail("Invalid CLI limits reached optional model imports")
        return native_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(SystemExit) as caught:
        service.main(["--load-local", option, value])
    assert caught.value.code == 2


def test_cli_binds_loopback_and_offline_environment_before_fixture_load(monkeypatch, tmp_path, capsys):
    from relay_gateway import jev_open_provider

    events = []
    constructed = {}

    class Socket:
        def setsockopt(self, *args):
            pass

        def bind(self, address):
            assert address == ("127.0.0.1", 8771)
            events.append("bound")

        def close(self):
            events.append("closed")

    class Server:
        def __init__(self, config):
            self.config = config

        def run(self, sockets):
            assert len(sockets) == 1 and isinstance(sockets[0], Socket)
            assert self.config["host"] == "127.0.0.1"
            assert self.config["workers"] == 1 and self.config["access_log"] is False
            events.append("served")

    def fixture_load(**kwargs):
        assert events == ["bound"]
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN"):
            assert service.os.environ[key] == "1"
        assert kwargs["allow_local"] is True and kwargs["device"] == "cuda"
        assert kwargs["cache_dir"] == tmp_path and kwargs["max_length"] == 512
        constructed.update(kwargs)
        events.append("loaded")
        return FixtureJevProvider()

    # All heavyweight/runtime modules are test doubles, even if installed while
    # these tests run. No real CUDA work or listening socket can be created.
    torch = SimpleNamespace(
        __version__="fixture-torch", version=SimpleNamespace(cuda="fixture-cuda"), set_num_threads=lambda count: None,
        cuda=SimpleNamespace(is_available=lambda: True, is_bf16_supported=lambda: True,
                             synchronize=lambda: None, get_device_name=lambda index: "fixture-gpu",
                             memory_allocated=lambda: 0))
    uvicorn = SimpleNamespace(Config=lambda app, **kwargs: kwargs, Server=Server)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
    monkeypatch.setattr(service.socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(jev_open_provider.LocalOpenJevProvider, "from_local_cache", fixture_load)
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN",
                "TOKENIZERS_PARALLELISM", "HF_HUB_DISABLE_PROGRESS_BARS"):
        monkeypatch.setenv(key, "fixture-before-main")
    service.main(["--load-local", "--port", "8771", "--cache-dir", str(tmp_path),
                  "--max-requests", "3", "--max-length", "512"])
    assert events == ["bound", "loaded", "served", "closed"]
    assert constructed["max_calls"] == 3
    startup = json.loads(capsys.readouterr().out)
    assert startup["status"] == "loaded" and startup["cloud_api_usd"] == "0"
    assert startup["energy_measured"] is False


def test_docs_and_schema_routes_are_disabled(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
