"""Finite fleet reads with a durable local cursor; no inference or actuation."""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Observation, Scenario
from .path_safety import is_link_or_junction


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
MAX_PAGE_BYTES = 512_000
MAX_SEQUENCE = 2 ** 63 - 2
_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$"


class _Envelope(BaseModel):
    # Validate the wire contract here without importing fleet_gateway: importing
    # that ASGI module creates its app from the gateway's environment settings.
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
    def fields_for_kind(self):
        if self.kind == "water_reading" and (self.value_milli is None or self.evidence_ref is not None or self.status is not None):
            raise ValueError("Invalid water-reading fields")
        if self.kind == "inspection_observation" and (self.evidence_ref is None or self.value_milli is not None):
            raise ValueError("Invalid inspection-observation fields")
        if self.kind == "heartbeat" and (self.status is None or self.value_milli is not None or self.evidence_ref is not None):
            raise ValueError("Invalid heartbeat fields")
        return self


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(event):
    return hashlib.sha256(_canonical(event).encode()).hexdigest()


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_SEQUENCE:
        raise ValueError("Invalid gateway sequence")
    return value


def _page(value):
    try:
        if type(value) is not dict or len(_canonical(value).encode()) > MAX_PAGE_BYTES:
            raise ValueError
        stream = value["stream_id"]
        if not isinstance(stream, str) or not re.fullmatch(_ID, stream):
            raise ValueError
        latest = _integer(value["latest_sequence"])
        retained = _integer(value["retained_from_sequence"], 1)
        after = _integer(value["next_after_sequence"])
        if retained > latest + 1 or type(value["gap_detected"]) is not bool:
            raise ValueError
        if value.get("durability") != "process_memory":
            raise ValueError
        events = value["events"]
        if not isinstance(events, list) or len(events) > 100:
            raise ValueError
        checked, previous = [], 0
        for item in events:
            if type(item) is not dict or set(item) != {"sequence", "sha256", "event"}:
                raise ValueError
            sequence = _integer(item["sequence"], 1)
            if sequence <= previous or sequence > latest or sequence < retained:
                raise ValueError
            event = _Envelope.model_validate(item["event"]).model_dump(mode="json", exclude_none=True)
            if len(_canonical(event).encode()) > 4096 or item["sha256"] != _digest(event):
                raise ValueError
            checked.append({"sequence": sequence, "sha256": item["sha256"], "event": event})
            previous = sequence
        if checked and after != checked[-1]["sequence"]:
            raise ValueError
        return {"stream_id": stream, "latest_sequence": latest, "retained_from_sequence": retained,
                "next_after_sequence": after, "gap_detected": value["gap_detected"], "events": checked}
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValueError("Invalid, oversized, or inconsistent gateway page") from None


def _result(status, reason=None, **details):
    return {"status": status, "reason": reason, "simulated": True, "model_calls": 0,
            "provider_writes": 0, "actuation_enabled": False, **details}


def _origin(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError
        host = parsed.hostname.lower()
        local = host == "localhost"
        try:
            local = local or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        authority = f"[{host}]" if ":" in host else host
        if port is not None and port != (443 if parsed.scheme == "https" else 80):
            authority += f":{port}"
        origin = f"{parsed.scheme}://{authority}"
        return origin, local
    except (ValueError, TypeError):
        raise ValueError("Use a gateway HTTP(S) origin without credentials, path, query, or fragment") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class FleetConsumer:
    """Durable source-bound cursor and event identities in workspace/.state."""

    def __init__(self, source_id="offline-fixture", *, workspace_root=None):
        if not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", source_id):
            raise ValueError("Invalid consumer source ID")
        self.source_id = source_id
        self.root = Path(workspace_root or WORKSPACE_ROOT).resolve()
        self.state = self.root / ".state"
        self.path = self.state / "fleet-consumer.sqlite"
        for path in (self.state, self.path, Path(str(self.path) + "-journal"),
                     Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")):
            if is_link_or_junction(path):
                raise ValueError("Linked fleet-consumer state paths are prohibited")
        self.state.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS consumer_state (
                  source_id TEXT PRIMARY KEY, stream_id TEXT, after_sequence INTEGER NOT NULL DEFAULT 0,
                  review_required INTEGER NOT NULL DEFAULT 0, reason TEXT,
                  pending_stream TEXT, pending_after INTEGER);
                CREATE TABLE IF NOT EXISTS envelopes (
                  source_id TEXT NOT NULL, mission_id TEXT NOT NULL, device_id TEXT NOT NULL,
                  event_id TEXT NOT NULL, sha256 TEXT NOT NULL, envelope_json TEXT NOT NULL,
                  PRIMARY KEY (source_id, mission_id, device_id, event_id));
                CREATE TABLE IF NOT EXISTS sequence_records (
                  source_id TEXT NOT NULL, stream_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                  sha256 TEXT NOT NULL, PRIMARY KEY (source_id, stream_id, sequence));
                CREATE INDEX IF NOT EXISTS envelope_digest ON envelopes(source_id, sha256);
                CREATE TABLE IF NOT EXISTS loss_acknowledgements (
                  source_id TEXT NOT NULL, old_stream TEXT, old_after INTEGER NOT NULL,
                  new_stream TEXT NOT NULL, new_after INTEGER NOT NULL, reason TEXT NOT NULL,
                  acknowledged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)
            connection.execute("INSERT OR IGNORE INTO consumer_state(source_id) VALUES (?)", (self.source_id,))

    @contextmanager
    def _connect(self, *, read_only=False):
        connection = (sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
                      if read_only else sqlite3.connect(self.path, timeout=5))
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @classmethod
    def from_url(cls, url, *, workspace_root=None):
        origin, _ = _origin(url)
        return cls("gateway:" + hashlib.sha256(origin.encode()).hexdigest(), workspace_root=workspace_root)

    def _state(self, connection):
        row = connection.execute("SELECT * FROM consumer_state WHERE source_id=?", (self.source_id,)).fetchone()
        return {"stream_id": row["stream_id"], "after_sequence": row["after_sequence"],
                "review_required": bool(row["review_required"]), "reason": row["reason"],
                "pending_stream_id": row["pending_stream"], "pending_after_sequence": row["pending_after"]}

    def cursor(self):
        with self._connect() as connection:
            return self._state(connection)

    def _block(self, connection, reason, page):
        current = self._state(connection)
        new_events = [item for item in page["events"] if item["sequence"] > current["after_sequence"]]
        target = page["retained_from_sequence"] - 1
        if reason == "sequence_gap" and new_events:
            expected = current["after_sequence"] + 1
            for item in new_events:
                if item["sequence"] != expected:
                    target = item["sequence"] - 1
                    break
                expected += 1
        connection.execute("""UPDATE consumer_state SET review_required=1, reason=?,
            pending_stream=?, pending_after=? WHERE source_id=?""",
                           (reason, page["stream_id"], target, self.source_id))
        return _result("needs_review", reason, cursor=self._state(connection),
                       events_accepted=0, observations=[], scenarios=[], opaque_evidence=[])

    def acknowledge_loss(self, stream_id, after_sequence, reason):
        """Explicitly accept a recorded reset/gap boundary; never delete evidence."""
        _integer(after_sequence)
        if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 300 or any(ord(c) < 32 for c in reason):
            raise ValueError("A brief explicit acknowledgement reason is required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection)
            if (not state["review_required"] or state["reason"] not in {"stream_reset", "retention_gap", "sequence_gap"}
                    or stream_id != state["pending_stream_id"] or after_sequence != state["pending_after_sequence"]):
                raise ValueError("Acknowledgement must match the recorded reset/gap boundary")
            connection.execute("""INSERT INTO loss_acknowledgements
                (source_id, old_stream, old_after, new_stream, new_after, reason) VALUES (?,?,?,?,?,?)""",
                (self.source_id, state["stream_id"], state["after_sequence"], stream_id, after_sequence, reason.strip()))
            connection.execute("""UPDATE consumer_state SET stream_id=?, after_sequence=?,
                review_required=0, reason=NULL, pending_stream=NULL, pending_after=NULL WHERE source_id=?""",
                (stream_id, after_sequence, self.source_id))
            return _result("acknowledged_loss", cursor=self._state(connection),
                           note="A gap/reset was acknowledged, not recovered. Prior envelope evidence is retained.")

    def consume_page(self, page):
        """Persist a validated page, or its contiguous prefix before a sequence gap."""
        try:
            page = _page(page)
        except ValueError:
            return _result("needs_review", "invalid_page", cursor=self.cursor(),
                           events_accepted=0, observations=[], scenarios=[], opaque_evidence=[])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection)
            if state["review_required"]:
                return _result("needs_review", state["reason"], cursor=state, events_accepted=0,
                               observations=[], scenarios=[], opaque_evidence=[])
            if state["stream_id"] is not None and state["stream_id"] != page["stream_id"]:
                return self._block(connection, "stream_reset", page)
            if page["gap_detected"] or state["after_sequence"] < page["retained_from_sequence"] - 1:
                return self._block(connection, "retention_gap", page)
            if page["latest_sequence"] < state["after_sequence"]:
                return self._block(connection, "sequence_regression", page)
            if not page["events"] and (page["next_after_sequence"] != state["after_sequence"]
                                       or page["latest_sequence"] > state["after_sequence"]):
                return self._block(connection, "sequence_gap", page)
            after, accepted, duplicates, pending = state["after_sequence"], [], 0, []
            seen = {}
            # Conflicts reject the page; a sequence gap preserves its validated prefix.
            for item in page["events"]:
                event, sequence = item["event"], item["sequence"]
                if event["simulated"] is not True:
                    return self._block(connection, "real_measurements_not_supported", page)
                identity = (event["mission_id"], event["source_id"], event["event_id"])
                if sequence <= state["after_sequence"]:
                    prior = connection.execute("SELECT sha256 FROM sequence_records WHERE source_id=? AND stream_id=? AND sequence=?",
                                               (self.source_id, page["stream_id"], sequence)).fetchone()
                    if prior is None or prior["sha256"] != item["sha256"]:
                        return self._block(connection, "sequence_conflict", page)
                    duplicates += 1
                    continue
                if sequence != after + 1:
                    mapped = self._map(accepted)
                    self._persist(connection, pending, page["stream_id"], after)
                    blocked = self._block(connection, "sequence_gap", page)
                    return {**blocked, "events_accepted": len(accepted), "duplicate_events": duplicates,
                            "prefix_sequences_committed": len(pending), "envelopes": accepted, **mapped,
                            "note": "Validated contiguous prefix saved. No event beyond the gap was accepted; explicit review is required."}
                prior = connection.execute("""SELECT sha256 FROM envelopes
                    WHERE source_id=? AND mission_id=? AND device_id=? AND event_id=?""", (self.source_id, *identity)).fetchone()
                existing_hash = seen.get(identity) or (prior["sha256"] if prior else None)
                if existing_hash is not None and existing_hash != item["sha256"]:
                    return self._block(connection, "event_identity_conflict", page)
                if existing_hash is None:
                    accepted.append(item)
                else:
                    duplicates += 1
                seen[identity] = item["sha256"]
                pending.append(item)
                after = sequence
            # Scenario construction also occurs before committing a cursor.
            mapped = self._map(accepted)
            self._persist(connection, pending, page["stream_id"], after)
            return _result("completed", cursor=self._state(connection), events_accepted=len(accepted),
                           duplicate_events=duplicates, envelopes=accepted, **mapped,
                           note="Synthetic page consumed locally. No model call, media decoding, or remote data-store write.")

    def _persist(self, connection, pending, stream_id, after):
        for item in pending:
            event = item["event"]
            connection.execute("INSERT OR IGNORE INTO envelopes VALUES (?,?,?,?,?,?)",
                               (self.source_id, event["mission_id"], event["source_id"], event["event_id"],
                                item["sha256"], _canonical(event)))
            connection.execute("INSERT INTO sequence_records VALUES (?,?,?,?)",
                               (self.source_id, stream_id, item["sequence"], item["sha256"]))
        connection.execute("UPDATE consumer_state SET stream_id=?, after_sequence=? WHERE source_id=?",
                           (stream_id, after, self.source_id))

    def export_stored(self, stream_id, after_sequence=0, limit=100):
        """Read bounded saved evidence for explicit recovery; never advance or dispatch."""
        if not isinstance(stream_id, str) or not re.fullmatch(_ID, stream_id):
            raise ValueError("Invalid stored stream ID")
        _integer(after_sequence)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Export limit must be 1 to 100")
        with self._connect(read_only=True) as connection:
            connection.execute("BEGIN")
            cursor = self._state(connection)
            rows = connection.execute("""SELECT s.sequence, s.sha256, e.envelope_json
                FROM sequence_records s LEFT JOIN envelopes e
                  ON e.source_id=s.source_id AND e.sha256=s.sha256
                WHERE s.source_id=? AND s.stream_id=? AND s.sequence>?
                ORDER BY s.sequence LIMIT ?""", (self.source_id, stream_id, after_sequence, limit)).fetchall()
            items, unique, seen = [], [], set()
            try:
                for row in rows:
                    if not isinstance(row["envelope_json"], str) or len(row["envelope_json"].encode()) > 4096:
                        raise ValueError
                    event = _Envelope.model_validate_json(row["envelope_json"]).model_dump(mode="json", exclude_none=True)
                    if not event["simulated"] or _digest(event) != row["sha256"]:
                        raise ValueError
                    item = {"sequence": _integer(row["sequence"], 1), "sha256": row["sha256"], "event": event}
                    items.append(item)
                    identity = (event["mission_id"], event["source_id"], event["event_id"])
                    if identity not in seen:
                        unique.append(item)
                        seen.add(identity)
                mapped = self._map(unique)
            except (ValueError, TypeError, OverflowError):
                return _result("needs_review", "stored_evidence_invalid", cursor=cursor,
                               replay=True, export_only=True, network_requests=0)
            return _result("completed", cursor=cursor, replay=True, export_only=True, network_requests=0,
                           stream_id=stream_id, after_sequence=after_sequence,
                           next_after_sequence=items[-1]["sequence"] if items else after_sequence,
                           exported_events=len(items), exported_unique_events=len(unique), envelopes=items, **mapped,
                           note="Read-only replay of saved evidence. No cursor advancement or downstream dispatch; downstream consumers must deduplicate stable event IDs.")

    @staticmethod
    def _map(items):
        groups, observations, opaque, mappings = defaultdict(list), [], [], []
        for item in items:
            event = item["event"]
            if event["kind"] != "water_reading":
                opaque.append(event)
                continue
            identity = [event["mission_id"], event["source_id"], event["event_id"]]
            identifier = "fleet-" + hashlib.sha256(_canonical(identity).encode()).hexdigest()[:32]
            observation = Observation(event_id=identifier, robot_id=event["source_id"], kind="water",
                                      value_milli=event["value_milli"], unit="normalized_wetness", simulated=True,
                                      timestamp_seconds=event["timestamp_seconds"])
            payload = observation.model_dump(mode="json", exclude_none=True)
            observations.append(payload)
            groups[(event["mission_id"], event["station_id"])].append(observation)
            mappings.append({"observation_event_id": identifier, "mission_id": identity[0],
                             "source_id": identity[1], "gateway_event_id": identity[2]})
        scenarios = [Scenario(mission_id=mission, station_id=station, simulated=True,
                             scenario_id="consumed-fleet-page", observations=sorted(rows, key=lambda row: (row.timestamp_seconds, row.event_id)))
                     .model_dump(mode="json", exclude_none=True)
                     for (mission, station), rows in sorted(groups.items())]
        return {"observations": observations, "scenarios": scenarios, "opaque_evidence": opaque, "event_id_mapping": mappings}

    def fetch_once(self, url, *, allow_remote=False, limit=100):
        """Explicitly read exactly one page; remote origins require HTTPS and auth."""
        origin, local = _origin(url)
        if self.source_id != "gateway:" + hashlib.sha256(origin.encode()).hexdigest():
            raise ValueError("Construct the consumer with FleetConsumer.from_url for this exact origin")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Page limit must be 1 to 100")
        if not local and (allow_remote is not True or not origin.startswith("https://")):
            raise ValueError("Remote reads require HTTPS and explicit allow_remote=True")
        token = os.environ.get("RELAY_FLEET_API_TOKEN")
        if (not local and not token) or (token and not re.fullmatch(r"[A-Za-z0-9._~-]{32,512}", token)):
            raise ValueError("A valid fleet service token is required; never use the DigitalOcean account token")
        cursor = self.cursor()
        if cursor["review_required"]:
            return _result("needs_review", cursor["reason"], cursor=cursor, network_requests=0)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(origin + f"/events?after_sequence={cursor['after_sequence']}&limit={limit}", headers=headers, method="GET")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=5) as response:
                body = response.read(MAX_PAGE_BYTES + 1)
                if response.status != 200 or len(body) > MAX_PAGE_BYTES:
                    raise ValueError
                page = json.loads(body)
            return {**self.consume_page(page), "network_requests": 1}
        except urllib.error.HTTPError as error:
            return _result("failed", "gateway_http_error", http_status=error.code, cursor=self.cursor(), network_requests=1)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return _result("failed", "gateway_read_not_verified", cursor=self.cursor(), network_requests=1)


def fixture_page(scenario):
    """Build the existing gateway's station/rover wire fixture without its ASGI app."""
    scenario = Scenario.model_validate(scenario)
    if not scenario.simulated or any(not observation.simulated for observation in scenario.observations):
        raise ValueError("The offline fixture accepts only simulated observations")
    events, active = [], False
    for observation in scenario.observations:
        if observation.kind != "water" or observation.value_milli is None:
            raise ValueError("The offline fixture requires normalized water readings")
        common = {"mission_id": scenario.mission_id, "station_id": scenario.station_id, "simulated": True}
        events.append(_Envelope(**common, event_id=observation.event_id, source_id=scenario.station_id,
                                kind="water_reading", timestamp_seconds=observation.timestamp_seconds,
                                value_milli=observation.value_milli))
        if observation.value_milli <= 200:
            active = False
        if observation.value_milli >= 700 and not active:
            events.append(_Envelope(**common, event_id="rover-" + observation.event_id, source_id="intellio-rover",
                                    kind="inspection_observation", timestamp_seconds=observation.timestamp_seconds + 1,
                                    evidence_ref="synthetic-" + observation.event_id, status="observing"))
            active = True
    payloads = [event.model_dump(mode="json", exclude_none=True) for event in sorted(events, key=lambda event: event.timestamp_seconds)]
    if len(payloads) > 100:
        raise ValueError("Fixture exceeds the single-page 100-envelope limit")
    return {"stream_id": "fixture-" + _digest(payloads)[:32], "durability": "process_memory",
            "latest_sequence": len(payloads), "retained_from_sequence": 1, "next_after_sequence": len(payloads),
            "gap_detected": False, "events": [{"sequence": index, "sha256": _digest(event), "event": event}
                                              for index, event in enumerate(payloads, start=1)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=WORKSPACE_ROOT / "scenarios" / "leak.json")
    parser.add_argument("--url", help="Explicit gateway origin; never include credentials or a token")
    parser.add_argument("--fetch-live", action="store_true", help="Perform one gateway GET; no model calls or provider writes")
    parser.add_argument("--allow-remote", action="store_true", help="Permit the explicitly supplied HTTPS gateway origin")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--ack-stream", help="Explicitly acknowledge the pending gap/reset for this stream")
    parser.add_argument("--ack-after", type=int)
    parser.add_argument("--ack-reason")
    parser.add_argument("--export-stream", help="Read saved evidence for this stream without fetching or advancing")
    parser.add_argument("--after-sequence", type=int, default=0, help="Exclusive starting sequence for --export-stream")
    args = parser.parse_args(argv)
    try:
        if args.fetch_live and not args.url:
            raise ValueError("--fetch-live requires an explicit --url")
        if sum((args.fetch_live, args.ack_stream is not None, args.export_stream is not None)) > 1:
            raise ValueError("Fetch, loss acknowledgement, and stored export are separate operations")
        if args.url and not args.fetch_live and args.ack_stream is None and args.export_stream is None:
            raise ValueError("A URL requires fetch, loss acknowledgement, or stored export")
        if args.after_sequence != 0 and args.export_stream is None:
            raise ValueError("--after-sequence requires --export-stream")
        consumer = FleetConsumer.from_url(args.url) if args.url else FleetConsumer()
        if args.ack_stream is not None:
            if args.ack_after is None or args.ack_reason is None or args.fetch_live:
                raise ValueError("Loss acknowledgement requires stream, after-sequence, and reason without --fetch-live")
            result = consumer.acknowledge_loss(args.ack_stream, args.ack_after, args.ack_reason)
        elif args.ack_after is not None or args.ack_reason is not None:
            raise ValueError("Use all acknowledgement fields together")
        elif args.export_stream is not None:
            result = consumer.export_stored(args.export_stream, args.after_sequence, args.limit)
        elif args.fetch_live:
            result = consumer.fetch_once(args.url, allow_remote=args.allow_remote, limit=args.limit)
        else:
            if args.scenario.stat().st_size > 256_000:
                raise ValueError("Scenario exceeds the local input limit")
            result = consumer.consume_page(fixture_page(json.loads(args.scenario.read_text(encoding="utf-8"))))
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in {"completed", "acknowledged_loss"} else 2
    except (ValueError, OSError, sqlite3.Error):
        # Pydantic and network errors can otherwise reflect external input.
        print(json.dumps(_result("failed", "invalid_configuration_or_local_state")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
