"""Small, separate fleet telemetry service intended for DigitalOcean.

No model calls, hardware control, background simulator, or cloud provisioning.
Mock mode accepts only explicitly synthetic envelopes over loopback.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Callable, Literal
import urllib.error
import urllib.parse
import urllib.request
import uuid

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Scenario


MAX_ENVELOPE_BYTES = 4096
_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$"


class TelemetryEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"] = "1"
    event_id: str = Field(pattern=_ID, max_length=96)
    mission_id: str = Field(pattern=_ID, max_length=96)
    source_id: str = Field(pattern=_ID, max_length=96)
    station_id: str = Field(pattern=_ID, max_length=96)
    kind: Literal["water_reading", "inspection_observation", "heartbeat"]
    timestamp_seconds: int = Field(ge=0, le=1_000_000_000_000)
    simulated: bool
    value_milli: int | None = Field(default=None, ge=0, le=1000)
    evidence_ref: str | None = Field(default=None, pattern=_ID, max_length=96)
    status: Literal["idle", "observing", "unavailable"] | None = None

    @model_validator(mode="after")
    def kind_fields(self):
        if self.kind == "water_reading" and (self.value_milli is None or self.evidence_ref is not None or self.status is not None):
            raise ValueError("Water readings require only a normalized wetness value.")
        if self.kind == "inspection_observation" and (self.evidence_ref is None or self.value_milli is not None):
            raise ValueError("Inspection observations require an opaque evidence reference, not a sensor value.")
        if self.kind == "heartbeat" and (self.status is None or self.value_milli is not None or self.evidence_ref is not None):
            raise ValueError("Heartbeats require only a status.")
        return self


@dataclass(frozen=True)
class FleetConfig:
    mode: Literal["mock", "live"] = "mock"
    api_token: str | None = field(default=None, repr=False)
    ttl_seconds: int = 3600
    max_events: int = 5000

    def __post_init__(self):
        if self.mode not in {"mock", "live"}:
            raise ValueError("RELAY_FLEET_MODE must be mock or live.")
        if self.mode == "live" and (not isinstance(self.api_token, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{32,512}", self.api_token)):
            raise ValueError("Live fleet mode requires a strong RELAY_FLEET_API_TOKEN (32–512 URL-safe characters).")
        if type(self.ttl_seconds) is not int or not 60 <= self.ttl_seconds <= 86400:
            raise ValueError("Telemetry TTL must be 60–86400 seconds.")
        if type(self.max_events) is not int or not 1 <= self.max_events <= 10000:
            raise ValueError("Telemetry cache capacity must be 1–10000 events.")

    @classmethod
    def from_env(cls):
        return cls(mode=os.environ.get("RELAY_FLEET_MODE", "mock"),
                   api_token=os.environ.get("RELAY_FLEET_API_TOKEN"),
                   ttl_seconds=int(os.environ.get("RELAY_FLEET_TTL_SECONDS", "3600")),
                   max_events=int(os.environ.get("RELAY_FLEET_MAX_EVENTS", "5000")))


class DuplicateConflict(Exception):
    pass


class CacheFull(Exception):
    pass


class TelemetryCache:
    """Thread-safe bounded memory, with finite retention and explicit restart ID."""
    def __init__(self, config: FleetConfig, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self.clock = clock
        self.stream_id = uuid.uuid4().hex
        self._events = {}
        self._sequence = 0
        self._lock = threading.Lock()

    def _prune(self, now):
        expired = [key for key, item in self._events.items() if now - item["received"] >= self.config.ttl_seconds]
        for key in expired:
            del self._events[key]

    def accept(self, event: TelemetryEnvelope):
        payload = event.model_dump(mode="json", exclude_none=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        identity = (event.mission_id, event.source_id, event.event_id)
        with self._lock:
            now = self.clock()
            self._prune(now)
            existing = self._events.get(identity)
            if existing:
                if existing["digest"] != digest:
                    raise DuplicateConflict
                return {"accepted": False, "duplicate": True, "sequence": existing["sequence"],
                        "stream_id": self.stream_id, "event_id": event.event_id, "sha256": digest}
            if len(self._events) >= self.config.max_events:
                raise CacheFull
            self._sequence += 1
            self._events[identity] = {"sequence": self._sequence, "digest": digest,
                                      "received": now, "event": payload}
            return {"accepted": True, "duplicate": False, "sequence": self._sequence,
                    "stream_id": self.stream_id, "event_id": event.event_id, "sha256": digest}

    def read(self, after_sequence=0, limit=100):
        with self._lock:
            self._prune(self.clock())
            retained = sorted(self._events.values(), key=lambda item: item["sequence"])
            first = retained[0]["sequence"] if retained else self._sequence + 1
            selected = [item for item in retained if item["sequence"] > after_sequence][:limit]
            return {"stream_id": self.stream_id, "durability": "process_memory",
                    "ttl_seconds": self.config.ttl_seconds, "latest_sequence": self._sequence,
                    "retained_from_sequence": first, "gap_detected": after_sequence < first - 1,
                    "next_after_sequence": selected[-1]["sequence"] if selected else after_sequence,
                    "events": [{"sequence": item["sequence"], "sha256": item["digest"],
                                "event": dict(item["event"])} for item in selected]}


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        chunks, total, count = [], 0, 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            count += 1
            if total > MAX_ENVELOPE_BYTES or count > 64:
                return await JSONResponse({"detail": "Telemetry request exceeds the 4 KiB input limit."}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False
        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()
        return await self.app(scope, replay_body, send)


def _loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def create_app(config: FleetConfig | None = None, *, cache: TelemetryCache | None = None) -> FastAPI:
    config = config or FleetConfig.from_env()
    cache = cache or TelemetryCache(config)
    service = FastAPI(title="Relay Fleet Telemetry Gateway", version="0.1.0",
                      description="Bounded telemetry intake. No model calls or physical robot commands.")
    service.add_middleware(BodyLimitMiddleware)
    service.state.telemetry_cache = cache

    def authorize(request: Request):
        if config.mode == "mock":
            if request.client is None or not _loopback(request.client.host):
                raise HTTPException(403, "Mock telemetry is available only over loopback.")
            return
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        if len(supplied) > 512 or not secrets.compare_digest(supplied.encode(), config.api_token.encode()):
            raise HTTPException(401, "A valid fleet bearer token is required.", headers={"WWW-Authenticate": "Bearer"})

    @service.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"detail": "Invalid telemetry envelope or cursor. Check the documented field types and bounds."}, status_code=422)

    @service.get("/health")
    def health():
        return {"status": "ok", "role": "fleet_telemetry_gateway", "mode": config.mode,
                "stream_id": cache.stream_id, "auth_required": config.mode == "live",
                "actuation_enabled": False, "model_calls_enabled": False,
                "durability": "process_memory", "max_events": config.max_events,
                "ttl_seconds": config.ttl_seconds, "cloud_deployment_verified": False}

    @service.post("/telemetry")
    def telemetry(event: TelemetryEnvelope, request: Request):
        authorize(request)
        if config.mode == "mock" and event.simulated is not True:
            raise HTTPException(403, "Mock gateway accepts only explicitly simulated telemetry.")
        try:
            accepted = cache.accept(event)
        except DuplicateConflict:
            raise HTTPException(409, "This mission/source/event identity already has different content.") from None
        except CacheFull:
            raise HTTPException(503, "Telemetry cache is full. Drain or wait for retention expiry; no event was evicted.") from None
        return JSONResponse({**accepted, "simulated": event.simulated, "actuation_enabled": False},
                            status_code=202 if accepted["accepted"] else 200)

    @service.get("/events")
    def events(request: Request, after_sequence: int = Query(default=0, ge=0),
               limit: int = Query(default=100, ge=1, le=100)):
        authorize(request)
        return cache.read(after_sequence, limit)

    return service


def fixture_events(scenario: Scenario | dict) -> list[TelemetryEnvelope]:
    scenario = Scenario.model_validate(scenario)
    if scenario.simulated is not True or any(observation.simulated is not True for observation in scenario.observations):
        raise ValueError("The fixture sender accepts synthetic scenarios only.")
    events = []
    active = False
    for observation in scenario.observations:
        if observation.kind != "water" or observation.value_milli is None:
            raise ValueError("This fixture requires bounded normalized water readings.")
        common = {"mission_id": scenario.mission_id, "station_id": scenario.station_id, "simulated": True}
        events.append(TelemetryEnvelope(**common, event_id=observation.event_id,
            source_id=scenario.station_id, kind="water_reading", timestamp_seconds=observation.timestamp_seconds,
            value_milli=observation.value_milli))
        if observation.value_milli <= 200:
            active = False
        if observation.value_milli >= 700 and not active:
            events.append(TelemetryEnvelope(**common, event_id="rover-" + observation.event_id,
                source_id="intellio-rover", kind="inspection_observation", timestamp_seconds=observation.timestamp_seconds + 1,
                evidence_ref="synthetic-" + observation.event_id, status="observing"))
            active = True
    return sorted(events, key=lambda event: event.timestamp_seconds)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def send_fixture(scenario: Scenario | dict, base_url: str = "http://127.0.0.1:8787", *, allow_remote: bool = False) -> dict:
    """Send one finite labeled fixture. No retry, animation loop, or actuation."""
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}:
        raise ValueError("Use a plain HTTP(S) gateway origin without credentials, paths, query, or fragment.")
    if not _loopback(parts.hostname) and (allow_remote is not True or parts.scheme != "https"):
        raise ValueError("Remote fixture sending requires HTTPS and explicit allow_remote=True.")
    token = os.environ.get("RELAY_FLEET_API_TOKEN")
    if not _loopback(parts.hostname) and not token:
        raise ValueError("Remote fixture sending requires RELAY_FLEET_API_TOKEN.")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(_NoRedirect())
    results = []
    for event in fixture_events(scenario):
        request = urllib.request.Request(base_url.rstrip("/") + "/telemetry",
            data=event.model_dump_json(exclude_none=True).encode(), headers=headers, method="POST")
        try:
            with opener.open(request, timeout=5) as response:
                raw = response.read(MAX_ENVELOPE_BYTES + 1)
                if len(raw) > MAX_ENVELOPE_BYTES:
                    raise ValueError("Gateway response exceeded the local limit.")
                result = json.loads(raw)
                if (response.status not in {200, 202} or type(result) is not dict
                        or result.get("event_id") != event.event_id
                        or type(result.get("accepted")) is not bool
                        or type(result.get("duplicate")) is not bool
                        or result["accepted"] == result["duplicate"]
                        or type(result.get("sequence")) is not int or result["sequence"] < 1):
                    raise ValueError("Gateway did not return a valid intake acknowledgement.")
                results.append({"event_id": event.event_id, "accepted": result.get("accepted"),
                                "duplicate": result.get("duplicate"), "sequence": result.get("sequence")})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError(f"Fixture dispatch stopped after {len(results)} successful responses; no automatic retry attempted.") from None
    return {"simulated": True, "events_sent": len(results), "results": results,
            "note": "Synthetic station and rover envelopes only; no physical device was commanded."}


app = create_app()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the separate telemetry gateway")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    for name in ("fixture", "send-fixture"):
        command = commands.add_parser(name)
        command.add_argument("--scenario", default="scenarios/leak.json")
        if name == "send-fixture":
            command.add_argument("--base-url", default="http://127.0.0.1:8787")
            command.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "serve":
        if not 1024 <= args.port <= 65535:
            parser.error("Port must be between 1024 and 65535.")
        if FleetConfig.from_env().mode == "mock" and not _loopback(args.host):
            parser.error("Mock gateway must bind to loopback.")
        import uvicorn
        uvicorn.run("relay_gateway.fleet_gateway:app", host=args.host, port=args.port)
        return
    source = Path(args.scenario)
    if source.stat().st_size > 256 * 1024:
        parser.error("Scenario exceeds the local size limit.")
    scenario = Scenario.model_validate_json(source.read_text(encoding="utf-8"))
    if args.command == "fixture":
        result = {"simulated": True, "events": [event.model_dump(mode="json", exclude_none=True) for event in fixture_events(scenario)]}
    else:
        result = send_fixture(scenario, args.base_url, allow_remote=args.allow_remote)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
