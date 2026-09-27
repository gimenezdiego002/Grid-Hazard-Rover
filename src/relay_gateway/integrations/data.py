"""Explicitly enabled data adapters and deterministic in-memory transports.

Construction and default operations are offline. The caller must reserve live
cost before calling an adapter; these adapters do not bypass the shared ledger.
Provider exceptions and raw HTTP response bodies never enter returned reports.
"""

from contextlib import AbstractContextManager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json as jsonlib
import math
import os
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import urllib.error
import urllib.request
import uuid


MAX_EVENTS = 100
MAX_REFERENCES = 5
TELEMETRY_COLUMNS = (
    "mission_id", "event_id", "robot_id", "observed_at", "kind", "value_milli",
    "simulated", "latitude", "longitude",
)
INSERT_TELEMETRY = """INSERT INTO relay_telemetry
    (mission_id, event_id, robot_id, observed_at, kind, value_milli, simulated, latitude, longitude)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (mission_id, event_id) DO NOTHING"""
SELECT_TELEMETRY = """SELECT mission_id, event_id, robot_id, observed_at, kind,
    value_milli, simulated, latitude, longitude FROM relay_telemetry
    WHERE mission_id = %s AND observed_at >= %s AND observed_at < %s
    ORDER BY observed_at, event_id LIMIT %s"""
SELECT_TELEMETRY_IDENTITIES = """SELECT mission_id, event_id, robot_id, observed_at,
    kind, value_milli, simulated, latitude, longitude FROM relay_telemetry
    WHERE (mission_id, event_id) IN
      (SELECT * FROM unnest(%s::text[], %s::text[]))
    ORDER BY mission_id, event_id"""
SELECT_REFERENCES = """SELECT REFERENCE_ID, HAZARD_TYPE, TITLE, LEFT(BODY, 2000) AS BODY,
    SOURCE_URL, IS_SIMULATED FROM RELAY_REFERENCES
    WHERE HAZARD_TYPE = ? ORDER BY REFERENCE_ID LIMIT ?"""
REFERENCE_COLUMNS = ("reference_id", "hazard_type", "title", "body", "source_url", "is_simulated")
REFERENCE_FIXTURES = (
    {"reference_id": "fixture-water-review-v1", "hazard_type": "standing_water",
     "title": "Synthetic water inspection procedure",
     "body": "Demo procedure: keep a suspected water finding visible for human review. A second independent observation may help corroborate it.",
     "source_url": "relay://fixtures/water-review-v1", "is_simulated": True},
    {"reference_id": "fixture-water-routing-v1", "hazard_type": "standing_water",
     "title": "Synthetic route review note",
     "body": "Demo procedure: propose inspection of the affected area; route and actuator decisions remain with the deterministic coordinator and operator.",
     "source_url": "relay://fixtures/water-routing-v1", "is_simulated": True},
)


def _text(value, name, maximum=128):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(f"Invalid {name}")
    return value


def _limit(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"Limit must be an integer from 1 to {maximum}")
    return value


def _utc(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("observed_at/range timestamps must include a timezone") from None


def _iso(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _result(provider, live, *, status="completed", simulated=True, evidence=None, **details):
    return {"schema_version": "1", "provider": provider, "mode": "live" if live else "mock",
            "status": status, "simulated": bool(simulated or not live),
            "evidence": evidence or {}, "estimated_usd": None if live else "0.000000",
            "actual_billed_usd": None if live else "0.000000",
            "usage": {"adapter_operations": 1}, **details}


def _unknown(provider, live):
    return _result(provider, live, status="unknown", error="data_operation_not_verified",
                   limitations=["No automatic retry. Preserve the live cost reservation and reconcile provider state."])


def _check_injected(client, live):
    if type(live) is not bool:
        raise ValueError("live must be an explicit boolean")
    if client is not None and not live and getattr(client, "relay_mock", False) is not True:
        raise ValueError("An injected mock client must declare relay_mock=True; live clients require live=True")


class MockMongoClient:
    """PyMongo-shaped transport; stores documents only in this object."""
    relay_mock = True

    def __init__(self):
        self.documents = {}
        self.requests = []

    def __getitem__(self, name):
        return self  # This adapter uses one fixed collection, relay_missions.

    def update_one(self, query, update, *, upsert):
        self.requests.append(("update_one", deepcopy(query), deepcopy(update), upsert))
        key = query["_id"]
        existing = self.documents.get(key)
        document = {"_id": key, **deepcopy(update["$set"])}
        self.documents[key] = document
        return SimpleNamespace(matched_count=int(existing is not None),
                               modified_count=int(existing is not None and existing != document),
                               upserted_id=key if existing is None else None)

    def find_one(self, query, projection):
        self.requests.append(("find_one", deepcopy(query), deepcopy(projection)))
        document = self.documents.get(query["_id"])
        return deepcopy(document) if document is not None else None

    def close(self):
        pass


class MongoMissionStore:
    """Atomic latest-snapshot upsert using mission_id as Mongo's unique _id."""

    def __init__(self, uri=None, database="relay", *, live=False, client=None):
        _check_injected(client, live)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", database):
            raise ValueError("Invalid Mongo database name")
        if live:
            if not isinstance(uri, str) or not uri.startswith(("mongodb://", "mongodb+srv://")):
                raise ValueError("Live Mongo requires an explicit Mongo connection URI")
            options = {k.lower(): [v.lower() for v in values]
                       for k, values in parse_qs(urlsplit(uri).query).items()}
            if any("true" in options.get(name, []) for name in
                   ("tlsinsecure", "tlsallowinvalidcertificates", "tlsallowinvalidhostnames")):
                raise ValueError("Insecure Mongo TLS options are prohibited")
            if options.get("tls") == ["false"] or options.get("ssl") == ["false"]:
                raise ValueError("Mongo requires TLS")
        self.live, self._uri, self.database = bool(live), uri, database
        self.client = client if client is not None else None if live else MockMongoClient()

    @classmethod
    def from_environment(cls, *, live=False):
        if not live:
            return cls()
        uri, alias = os.environ.get("MONGODB_URI"), os.environ.get("POLLARD_MONGODB_URI")
        if uri and alias and uri != alias:
            raise ValueError("Mongo URI aliases conflict")
        return cls(uri or alias, database=os.environ.get("MONGODB_DATABASE",
                   os.environ.get("POLLARD_MONGODB_DATABASE", "relay")), live=True)

    def _collection(self):
        if self.client is None:
            from pymongo import MongoClient
            self.client = MongoClient(self._uri, tls=True, tlsAllowInvalidCertificates=False,
                                      tlsAllowInvalidHostnames=False, timeoutMS=5000,
                                      serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                                      socketTimeoutMS=5000, retryWrites=False, retryReads=False,
                                      w="majority", maxPoolSize=2, connect=False)
        return self.client[self.database]["relay_missions"]

    def upsert_mission(self, mission):
        if not isinstance(mission, dict):
            raise ValueError("Mission must be a JSON object")
        mission_id = _text(mission.get("mission_id"), "mission_id")
        if type(mission.get("simulated", True)) is not bool:
            raise ValueError("simulated must be a boolean")
        try:
            encoded = jsonlib.dumps(mission, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        except (TypeError, ValueError):
            raise ValueError("Mission must contain finite JSON values") from None
        if len(encoded) > 256_000:
            raise ValueError("Mission snapshot exceeds 256 KB")
        snapshot = jsonlib.loads(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        try:
            result = self._collection().update_one(
                {"_id": mission_id}, {"$set": {"mission": snapshot, "content_sha256": digest}}, upsert=True)
            return _result("mongodb", self.live, simulated=mission.get("simulated", True),
                           evidence={"mission_id": mission_id, "content_sha256": digest},
                           matched_count=result.matched_count, modified_count=result.modified_count,
                           inserted=result.upserted_id is not None)
        except Exception:
            return _unknown("mongodb", self.live)

    def get_mission(self, mission_id):
        mission_id = _text(mission_id, "mission_id")
        try:
            stored = self._collection().find_one({"_id": mission_id}, {"_id": 0, "mission": 1, "content_sha256": 1})
            mission = stored["mission"] if stored else None
            return _result("mongodb", self.live, simulated=(mission or {}).get("simulated", True),
                           evidence={"mission_id": mission_id, "found": stored is not None,
                                     "content_sha256": stored.get("content_sha256") if stored else None},
                           mission=mission)
        except Exception:
            return _unknown("mongodb", self.live)

    def close(self):
        if self.client is not None:
            self.client.close()


class _MockTigerCursor(AbstractContextManager):
    def __init__(self, client):
        self.client, self.rowcount, self.selected = client, 0, []

    def __exit__(self, *args):
        return False

    def executemany(self, statement, params):
        self.client.requests.append((statement, deepcopy(params)))
        self.rowcount = 0
        for row in params:
            key = row[:2]
            if key not in self.client.rows:
                self.client.rows[key] = tuple(row)
                self.rowcount += 1

    def execute(self, statement, params):
        self.client.requests.append((statement, deepcopy(params)))
        if statement == SELECT_TELEMETRY_IDENTITIES:
            identities = set(zip(*params, strict=True))
            self.selected = [self.client.rows[key] for key in sorted(identities) if key in self.client.rows]
            return
        mission_id, start, end, limit = params
        rows = [row for row in self.client.rows.values() if row[0] == mission_id and start <= row[3] < end]
        self.selected = sorted(rows, key=lambda row: (row[3], row[1]))[:limit]

    def fetchall(self):
        return deepcopy(self.selected)


class _MockTigerConnection(AbstractContextManager):
    def __init__(self, client):
        self.client = client
        self.before = deepcopy(client.rows)

    def __exit__(self, exc_type, *args):
        if exc_type is not None:
            self.client.rows = self.before
        return False

    def cursor(self):
        return _MockTigerCursor(self.client)


class MockTigerClient:
    """psycopg-module-shaped mock; connect never opens a socket."""
    relay_mock = True

    def __init__(self):
        self.rows, self.requests, self.connections = {}, [], []

    def connect(self, dsn, **options):
        self.connections.append(deepcopy(options))
        return _MockTigerConnection(self)


class _TelemetryIdentityConflict(Exception):
    def __init__(self, identities):
        self.identities = identities
        super().__init__("Telemetry event identity conflict")


class TigerTelemetryStore:
    """Bounded transactional inserts and [start, end) timestamp queries."""

    def __init__(self, dsn=None, *, live=False, client=None, sslrootcert="system"):
        _check_injected(client, live)
        if live and (not isinstance(dsn, str) or not dsn.startswith(("postgres://", "postgresql://"))):
            raise ValueError("Live Tiger Data requires an explicit PostgreSQL URI")
        self.live, self._dsn, self.sslrootcert = bool(live), dsn, sslrootcert
        self.client = client if client is not None else None if live else MockTigerClient()

    @classmethod
    def from_environment(cls, *, live=False):
        if not live:
            return cls()
        return cls(os.environ.get("TIGER_DATABASE_URL"), live=True,
                   sslrootcert=os.environ.get("TIGER_SSLROOTCERT", "system"))

    def _connection(self):
        if self.client is None:
            import psycopg
            self.client = psycopg
        return self.client.connect(self._dsn if self.live else "mock://tiger", sslmode="verify-full",
                                   sslrootcert=self.sslrootcert, connect_timeout=5,
                                   options="-c statement_timeout=5000 -c lock_timeout=2000",
                                   application_name="relay-hackathon")

    @staticmethod
    def _event(event):
        if not isinstance(event, dict):
            raise ValueError("Telemetry events must be objects")
        result = {name: _text(event.get(name), name, 40 if name == "kind" else 128)
                  for name in ("mission_id", "event_id", "robot_id", "kind")}
        result["observed_at"] = _utc(event.get("observed_at"))
        value = event.get("value_milli")
        if value is not None and (type(value) is not int or not -(2 ** 63) <= value < 2 ** 63):
            raise ValueError("value_milli must be a signed 64-bit integer or null")
        result["value_milli"] = value
        simulated = event.get("simulated", True)
        if type(simulated) is not bool:
            raise ValueError("simulated must be a boolean")
        result["simulated"] = simulated
        for name, maximum in (("latitude", 90), ("longitude", 180)):
            coordinate = event.get(name)
            if coordinate is not None and (type(coordinate) not in (int, float) or
                                            not math.isfinite(coordinate) or abs(coordinate) > maximum):
                raise ValueError(f"Invalid {name}")
            result[name] = coordinate
        return tuple(result[name] for name in TELEMETRY_COLUMNS)

    def insert_telemetry(self, events):
        if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
            raise ValueError("Provide 1 to 100 telemetry events")
        rows = [self._event(event) for event in events]
        seen = {}
        for row in rows:
            if row[:2] in seen and seen[row[:2]] != row:
                raise ValueError("Conflicting payloads for one telemetry event identity")
            seen[row[:2]] = row
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.executemany(INSERT_TELEMETRY, sorted(rows, key=lambda row: row[:2]))
                    inserted = cursor.rowcount
                    # ON CONFLICT waits for competing unique-key inserts. A
                    # following READ COMMITTED statement observes their committed
                    # rows and our own inserts. Existing rows are never updated by
                    # this insert-only adapter. Verify before committing any row.
                    keys = sorted(seen)
                    cursor.execute(SELECT_TELEMETRY_IDENTITIES,
                                   ([key[0] for key in keys], [key[1] for key in keys]))
                    stored = {tuple(row[:2]): tuple(row) for row in cursor.fetchall()}
                    conflicts = [key for key in keys if stored.get(key) != seen[key]]
                    if conflicts:
                        raise _TelemetryIdentityConflict(conflicts)
            return _result("tiger", self.live, simulated=any(row[6] for row in rows),
                           evidence={"submitted_events": len(rows), "inserted_events": inserted,
                                     "duplicate_events": len(rows) - inserted},
                           inserted=inserted)
        except _TelemetryIdentityConflict as error:
            # The connection context has rolled back the whole batch, including
            # otherwise-new events. No changed payload overwrites the original.
            return _result("tiger", self.live, status="failed", simulated=any(row[6] for row in rows),
                           error="telemetry_identity_conflict", inserted=0,
                           evidence={"conflicting_events": [{"mission_id": key[0], "event_id": key[1]}
                                                             for key in error.identities],
                                     "conflicting_event_ids": [key[1] for key in error.identities],
                                     "inserted_events": 0, "batch_rolled_back": True},
                           limitations=["An existing event identity has a different payload. Use a new identity for a correction."])
        except Exception:
            return _unknown("tiger", self.live)

    def query_range(self, mission_id, start, end, limit=100):
        mission_id = _text(mission_id, "mission_id")
        start, end, limit = _utc(start), _utc(end), _limit(limit, MAX_EVENTS)
        if start >= end:
            raise ValueError("Range start must precede end")
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(SELECT_TELEMETRY, (mission_id, start, end, limit))
                    rows = [dict(zip(TELEMETRY_COLUMNS, row, strict=True)) for row in cursor.fetchall()]
            for row in rows:
                row["observed_at"] = _iso(row["observed_at"])
            return _result("tiger", self.live, simulated=any(row["simulated"] for row in rows),
                           evidence={"mission_id": mission_id, "returned_events": len(rows),
                                     "start_inclusive": _iso(start), "end_exclusive": _iso(end)}, rows=rows)
        except Exception:
            return _unknown("tiger", self.live)


class _Response:
    def __init__(self, status_code, body):
        self.status_code, self.body = status_code, body

    def json(self):
        return deepcopy(self.body)


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _SnowflakeHTTPClient:
    def post(self, url, *, json, headers, timeout):
        encoded = jsonlib.dumps(json, allow_nan=False).encode()
        request = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
        try:
            with urllib.request.build_opener(_NoRedirects()).open(request, timeout=timeout) as response:
                raw = response.read(128_001)
                if len(raw) > 128_000:
                    raise ValueError("Oversized Snowflake response")
                return _Response(response.status, jsonlib.loads(raw))
        except urllib.error.HTTPError as error:
            return _Response(error.code, {})


class MockSnowflakeClient:
    """SQL API-shaped deterministic reference fixture, including row metadata."""
    relay_mock = True

    def __init__(self, references=None):
        self.references = deepcopy(REFERENCE_FIXTURES if references is None else references)
        self.requests = []

    def post(self, url, *, json, headers, timeout):
        self.requests.append({"url": url, "json": deepcopy(json), "headers": deepcopy(headers), "timeout": timeout})
        hazard = json["bindings"]["1"]["value"]
        limit = int(json["bindings"]["2"]["value"])
        rows = sorted((row for row in self.references if row["hazard_type"] == hazard),
                      key=lambda row: row["reference_id"])[:limit]
        return _Response(200, {"statementHandle": "mock-reference-query-v1",
                              "resultSetMetaData": {"numRows": len(rows),
                                                    "rowType": [{"name": name.upper()} for name in REFERENCE_COLUMNS]},
                              "data": [[str(row[name]).lower() if type(row[name]) is bool else row[name]
                                        for name in REFERENCE_COLUMNS] for row in rows]})


class SnowflakeReferenceStore:
    """One bounded SELECT via the Snowflake SQL REST API; no warehouse creation."""

    def __init__(self, account=None, token=None, database=None, schema=None, warehouse=None,
                 role=None, *, live=False, client=None, token_type="PROGRAMMATIC_ACCESS_TOKEN"):
        _check_injected(client, live)
        if live:
            if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*", account):
                raise ValueError("Provide the Snowflake account identifier, not a URL")
            _text(token, "Snowflake token", 16_000)
            for name, value in (("database", database), ("schema", schema), ("warehouse", warehouse)):
                _text(value, "Snowflake " + name, 255)
            if token_type not in {"PROGRAMMATIC_ACCESS_TOKEN", "OAUTH", "KEYPAIR_JWT"}:
                raise ValueError("Unsupported Snowflake token type")
        self.live = bool(live)
        self.account, self._token = (account, token) if live else ("mock-account", "mock-token")
        self.database, self.schema, self.warehouse, self.role = database, schema, warehouse, role
        self.token_type = token_type
        self.client = client if client is not None else _SnowflakeHTTPClient() if live else MockSnowflakeClient()

    @classmethod
    def from_environment(cls, *, live=False):
        if not live:
            return cls()
        return cls(account=os.environ.get("SNOWFLAKE_ACCOUNT"), token=os.environ.get("SNOWFLAKE_TOKEN"),
                   database=os.environ.get("SNOWFLAKE_DATABASE"), schema=os.environ.get("SNOWFLAKE_SCHEMA"),
                   warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"), role=os.environ.get("SNOWFLAKE_ROLE"),
                   token_type=os.environ.get("SNOWFLAKE_TOKEN_TYPE", "PROGRAMMATIC_ACCESS_TOKEN"), live=True)

    def retrieve(self, hazard_type, limit=3):
        hazard_type, limit = _text(hazard_type, "hazard_type", 80), _limit(limit, MAX_REFERENCES)
        request_id = uuid.uuid4() if self.live else uuid.uuid5(uuid.NAMESPACE_URL, f"relay:{hazard_type}:{limit}")
        url = f"https://{self.account}.snowflakecomputing.com/api/v2/statements?requestId={request_id}"
        body = {"statement": SELECT_REFERENCES, "timeout": 5,
                "database": self.database or "RELAY", "schema": self.schema or "PUBLIC",
                "warehouse": self.warehouse or "MOCK_WAREHOUSE",
                "bindings": {"1": {"type": "TEXT", "value": hazard_type},
                             "2": {"type": "FIXED", "value": str(limit)}},
                "parameters": {"query_tag": "relay_reference_lookup", "multi_statement_count": "1",
                               "rows_per_resultset": limit}}
        if self.role:
            body["role"] = self.role
        headers = {"Authorization": "Bearer " + self._token, "Content-Type": "application/json",
                   "Accept": "application/json", "User-Agent": "relay-gateway/0.1.0",
                   "X-Snowflake-Authorization-Token-Type": self.token_type}
        try:
            response = self.client.post(url, json=body, headers=headers, timeout=10)
            if response.status_code == 202:
                payload = response.json()
                handle = payload.get("statementHandle")
                if handle is not None:
                    _text(handle, "statement handle", 128)
                return _result("snowflake", self.live, status="unknown", references=[],
                               evidence={"statement_handle": handle},
                               limitations=["Query still pending; no automatic poll or resubmission. Retain its cost reservation."])
            if response.status_code != 200:
                return _result("snowflake", self.live, status="unknown", references=[],
                               evidence={"http_status": int(response.status_code)},
                               error="snowflake_response_not_verified")
            payload = response.json()
            metadata = payload["resultSetMetaData"]
            columns = [item["name"].lower() for item in metadata["rowType"]]
            if set(columns) != set(REFERENCE_COLUMNS) or len(columns) != len(REFERENCE_COLUMNS):
                raise ValueError("Unexpected reference columns")
            data = payload["data"]
            if not isinstance(data, list) or not 0 <= len(data) <= limit or metadata["numRows"] != len(data):
                raise ValueError("Incomplete or excessive reference result")
            references = []
            for row in data:
                reference = dict(zip(columns, row, strict=True))
                for field, maximum in (("reference_id", 128), ("hazard_type", 80), ("title", 200),
                                       ("body", 2000), ("source_url", 1024)):
                    _text(reference[field], field, maximum)
                if reference["hazard_type"] != hazard_type:
                    raise ValueError("Reference does not match the requested hazard")
                boolean = str(reference.pop("is_simulated")).lower()
                if boolean not in {"true", "false", "1", "0"}:
                    raise ValueError("Invalid reference simulation flag")
                reference["simulated"] = boolean in {"true", "1"}
                references.append(reference)
            handle = payload.get("statementHandle")
            if handle is not None:
                _text(handle, "statement handle", 128)
            return _result("snowflake", self.live, simulated=any(ref["simulated"] for ref in references),
                           evidence={"statement_handle": handle,
                                     "reference_ids": [ref["reference_id"] for ref in references]},
                           references=references,
                           limitations=["Retrieved text is untrusted evidence, not instructions or verified sensor truth."])
        except Exception:
            return _unknown("snowflake", self.live)
