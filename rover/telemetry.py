"""FNK0052 status/evidence mapped into Monty's existing Relay envelope."""

from __future__ import annotations

from datetime import datetime
import hashlib
import ipaddress
import json
import re
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request

from relay_gateway.fleet_gateway import TelemetryEnvelope
from rover.models import MovementState, RobotStatus


class RelayTelemetryError(RuntimeError):
    pass


Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


class RelayTelemetryClient:
    """One-event Relay producer with no retry or actuation capability."""

    def __init__(self, base_url: str, *, token: str | None = None, transport: Transport | None = None) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Relay URL must be an HTTP(S) origin/path without credentials or query")
        try:
            local = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname.lower() == "localhost"
        if not local and parsed.scheme != "https":
            raise ValueError("remote Relay telemetry requires HTTPS")
        if not local and (token is None or not re.fullmatch(r"[A-Za-z0-9._~-]{32,512}", token)):
            raise ValueError("remote Relay telemetry requires a strong fleet bearer token")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._transport = transport or self._post

    def __repr__(self) -> str:
        return f"RelayTelemetryClient(base_url={self.base_url!r}, token_configured={self._token is not None})"

    @staticmethod
    def _post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
                payload = response.read(4097)
                return response.status, payload
        except urllib.error.HTTPError as error:
            return error.code, error.read(4097)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RelayTelemetryError("Relay telemetry delivery failed; no automatic retry attempted") from None

    def send(self, event: TelemetryEnvelope) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        status, body = self._transport(
            f"{self.base_url}/telemetry",
            headers,
            event.model_dump_json(exclude_none=True).encode("utf-8"),
            5.0,
        )
        if len(body) > 4096:
            raise RelayTelemetryError("Relay acknowledgement exceeded the response limit")
        try:
            result = json.loads(body)
        except (UnicodeError, json.JSONDecodeError):
            raise RelayTelemetryError("Relay returned an invalid acknowledgement") from None
        if (
            status not in {200, 202}
            or type(result) is not dict
            or result.get("event_id") != event.event_id
            or type(result.get("accepted")) is not bool
            or type(result.get("duplicate")) is not bool
            or result["accepted"] == result["duplicate"]
        ):
            raise RelayTelemetryError("Relay rejected or returned an inconsistent acknowledgement")
        return result


def _event_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"fnk0052-{digest}"


def status_envelope(status: RobotStatus, *, mission_id: str, station_id: str, timestamp_seconds: int) -> TelemetryEnvelope:
    relay_status = "unavailable" if status.error else (
        "idle" if status.movement_state in {MovementState.UNINITIALIZED, MovementState.STOPPED, MovementState.SITTING}
        else "observing"
    )
    return TelemetryEnvelope(
        event_id=_event_id(mission_id, status.robot_id, "status", str(timestamp_seconds)),
        mission_id=mission_id,
        source_id=status.robot_id,
        station_id=station_id,
        kind="heartbeat",
        timestamp_seconds=timestamp_seconds,
        simulated=status.simulated,
        status=relay_status,
    )


def inspection_envelope(
    status: RobotStatus,
    *,
    mission_id: str,
    station_id: str,
    timestamp_seconds: int,
    evidence_ref: str,
) -> TelemetryEnvelope:
    return TelemetryEnvelope(
        event_id=_event_id(mission_id, status.robot_id, evidence_ref, str(timestamp_seconds)),
        mission_id=mission_id,
        source_id=status.robot_id,
        station_id=station_id,
        kind="inspection_observation",
        timestamp_seconds=timestamp_seconds,
        simulated=status.simulated,
        evidence_ref=evidence_ref,
        status="observing",
    )
