# Finite fleet gateway consumer

`relay_gateway.fleet_consumer` closes the local gateway-to-Relay data path. One explicit read consumes at most 100 retained envelopes. It saves original validated envelopes, their hashes, sequence records and a source-bound cursor in the fixed workspace file `.state/fleet-consumer.sqlite`.

It does not call Gemini, forward to cloud databases, create a wallet, generate speech, or command hardware. Default CLI execution is an offline fixture. An explicit HTTP fetch only reads the fleet gateway. Existing account keys or live flags cannot switch the offline default into network mode.

## What is consumed

The consumer validates the gateway's `GET /events` page metadata, ordering, envelope schema and SHA-256 values before advancing a cursor. The page is capped at 100 envelopes and 512 KB; each envelope is capped at 4 KB. Reads use a five-second HTTP timeout, no retries, no redirects and no inherited HTTP proxy. Remote reads require an explicitly selected HTTPS origin and the fleet service bearer token. Do not provide the DigitalOcean administrative API token.

Only envelopes explicitly marked `simulated: true` are accepted by this prototype:

- `water_reading` becomes an existing Relay `Observation`, with `kind: "water"`, `unit: "normalized_wetness"`, the original relative timestamp and `robot_id` equal to the gateway source ID.
- `inspection_observation` and `heartbeat` remain opaque evidence/status records. A rover's evidence reference is not an image, a decoded camera finding or a second water measurement.
- Ground-truth evaluation labels are neither accepted in gateway envelopes nor added to inference observations.

Event identity is `(gateway source, mission_id, source_id, event_id)`. The original identity remains in saved envelope evidence. Relay observation IDs use a stable bounded hash of the mission/source/event tuple to avoid collisions between devices without exceeding the existing 128-character field limit. The output includes that mapping.

New observations are grouped into existing `Scenario` objects by mission and station, ordered by relative timestamp. These dictionaries can be passed to the deterministic `run_scenario` path explicitly. **The consumer itself never runs inference.** A normal consume result covers only newly accepted water readings from the current page, or its saved contiguous prefix when a sequence hole is found. Explicit export returns previously saved readings from the selected local sequence range. Neither operation claims to reconstruct an entire mission or maintain analysis state across pages.

## Durable cursor and failure behavior

`FleetConsumer(source_id="offline-fixture", workspace_root=None).consume_page(page)` accepts an already fetched page. Production use defaults to the repository workspace; the optional workspace root supports isolated tests. There is no arbitrary database-path CLI option. Linked `.state` or database paths are rejected. SQLite commits the accepted envelope evidence, sequence records and cursor atomically, with a bounded lock timeout.

`FleetConsumer.from_url(origin)` binds the cursor namespace to a hash of the canonical gateway origin. `fetch_once(origin, allow_remote=False, limit=100)` verifies that binding and issues exactly one GET using the stored sequence. `cursor()` returns stream ID, sequence and any pending review boundary. Multiple explicit runs can read subsequent pages; there is no background loop.

- Repeated identical event identities are deduplicated and are not emitted again for inference.
- A gateway `stream_id` change latches `needs_review: stream_reset`. The old cursor and all envelope evidence remain intact.
- A retention gap or unannounced sequence hole latches `needs_review`. For an internal sequence hole, the validated contiguous prefix and cursor are saved atomically with the review latch; nothing beyond the hole is accepted. For example, a page containing sequences `1, 3, 4` saves sequence `1`, stops at cursor `1`, and proposes acknowledging only the missing sequence `2`. Subsequent reads remain blocked until explicit acknowledgement. No missing records are skipped automatically.
- A changed payload under an existing identity or sequence, sequence regression, or real measurement blocks processing. Identity conflicts are not cleared by the gap/reset acknowledgement method.
- Malformed pages, digest mismatches or oversized responses cannot advance the cursor. Authentication/network errors return sanitized status without tokens or native response bodies.

The gateway has an expiring process-memory cache. Local persistence can preserve events already consumed; it cannot recover records the gateway lost before they were read. A hash verifies consistency with the received bytes, not physical sensor truth.

## Recover saved output after a restart

The cursor can commit before a caller receives the returned observations. If that caller crashes, ordinary consumption correctly deduplicates the same page; use the explicit read-only export to recover the saved output:

```python
consumer = FleetConsumer.from_url("http://127.0.0.1:8787")
saved = consumer.export_stored(stream_id="SAVED-STREAM-ID", after_sequence=0, limit=100)
```

The method opens SQLite in read-only mode and reads at most 100 saved sequence records, strictly after the requested sequence. It returns the original envelopes, mapped observations/scenarios, opaque evidence, and `next_after_sequence` for another explicit export. Every export is marked `replay: true` and `export_only: true`; it performs zero network requests, changes no cursor or review state, and never dispatches inference. It also works while a gap/reset is awaiting review. Missing or corrupt saved evidence returns `needs_review` without emitting a partial export.

The CLI equivalent selects the same source namespace using its original URL, without contacting that URL:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.fleet_consumer --url http://127.0.0.1:8787 --export-stream '<SAVED-STREAM-ID>' --after-sequence 0 --limit 100
```

For the offline fixture, omit `--url`. Take the saved stream ID from an earlier result or `cursor()`; do not use the pending replacement stream ID to recover the old stream. Export is a separate operation from fetch and acknowledgement. Repeat explicitly using the previous `next_after_sequence` to read more stored records. It preserves sequence evidence while deduplicating identical event identities within that export's mapped observations. A downstream caller must still deduplicate stable observation IDs across exports or previous handoffs. This is manual recovery, not an automatic delivery queue, and it cannot reconstruct events never received.

## Offline proof

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.fleet_consumer
.\.venv\Scripts\python.exe -m pytest tests/test_fleet_consumer.py -q
```

The first CLI command reads the existing leak fixture locally and records 13 synthetic envelopes: 12 station water readings plus one rover observation. Running it again records no new events and emits no duplicate observations. Its deterministic fixture stream is separate from every URL-bound gateway cursor. Changing the offline fixture changes the stream identity, so it also requires deliberate reset acknowledgement.

Tests cover actual loopback HTTP against the FastAPI gateway, durable replay, pagination, gateway restart, retention gaps, sequence-prefix preservation and resumption, read-only recovery after lost output, export bounds and stored corruption, conflicting payloads, response validation, auth errors, and offline execution with hostile live environment settings. The test suite uses temporary workspaces and never contacts a cloud account.

## One-page loopback demonstration

Start the separate gateway in a terminal, with its mode explicitly mock:

```powershell
$env:RELAY_FLEET_MODE = 'mock'
.\.venv\Scripts\python.exe -m relay_gateway.fleet_gateway serve --port 8787
```

In another terminal, send the existing finite fixture and read one page:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.fleet_gateway send-fixture --scenario scenarios/leak.json
.\.venv\Scripts\python.exe -m relay_gateway.fleet_consumer --fetch-live --url http://127.0.0.1:8787 --limit 100
```

Here `--fetch-live` means a real HTTP read from the local gateway, not a model call or physical input. Output should include `events_accepted: 13`, 12 mapped observations, one opaque rover record and `model_calls: 0`. A second read is a separate explicit GET and should return no new observations while the gateway has no new events.

For a deployed DigitalOcean gateway whose origin and TLS certificate have already been verified, use the service authentication token in the process environment and explicitly opt into that origin:

```powershell
# RELAY_FLEET_API_TOKEN must already be set securely; do not paste it in a command.
.\.venv\Scripts\python.exe -m relay_gateway.fleet_consumer --fetch-live --allow-remote --url https://YOUR-VERIFIED-GATEWAY-ORIGIN --limit 100
```

Remote HTTP, URL credentials, URL paths, query strings and redirects are refused. Existing hosting/transfer charges still belong in the cumulative project budget. This consumer creates no cloud resource and does not establish that a DigitalOcean deployment exists.

## Explicitly acknowledge a reset or known loss

When a result reports `needs_review`, inspect its `cursor.pending_stream_id`, `cursor.pending_after_sequence`, and reason. Resolve the loss or choose deliberately to continue from the exact proposed boundary. Acknowledgement records the old/new boundaries and reason in SQLite; it does not delete past evidence or claim recovery.

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.fleet_consumer --url http://127.0.0.1:8787 --ack-stream '<PENDING-STREAM-ID>' --ack-after 0 --ack-reason 'Reviewed gateway restart; accept the new stream from its beginning'
```

Replace the stream and sequence with the actual pending values. A restart may propose zero; a retention gap generally proposes a later sequence. The acknowledgement command performs no HTTP request. Run a separate `--fetch-live` command afterward to obtain a fresh page. For the offline fixture, omit `--url`. Do not delete the consumer database merely to hide a gap or reset the cursor.
