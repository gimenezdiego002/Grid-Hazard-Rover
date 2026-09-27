# DigitalOcean fleet telemetry gateway

The separate `relay_gateway.fleet_gateway:app` is implemented and locally testable. **No DigitalOcean account connection, deployment, or spend is claimed here.** GCP remains the main app/control-plane target. DigitalOcean's intended job is the small always-available intake point for station and robot telemetry; it does not run another LLM or issue movement commands.

## Local proof

Use the existing project `.venv`, with no new dependencies. In one terminal:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.fleet_gateway serve --port 8787
```

In another terminal, explicitly send one finite synthetic fixture:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.fleet_gateway send-fixture --scenario scenarios/leak.json
```

The sender converts the existing twelve water readings into station envelopes and one synthetic rover observation at 41 seconds. It sends thirteen POST requests, then exits. It does not animate a robot, read hardware, produce images, call Gemini, or run a background loop. `fixture` in place of `send-fixture` prints the envelopes without sending them.

Read [local health](http://127.0.0.1:8787/health) and [retained events](http://127.0.0.1:8787/events). Repeating the same fixture returns duplicates with the original sequence numbers. Reusing an identity with different content returns 409. IDs are scoped by mission and source.

## Service contract

- `GET /health`: public operational metadata; no credentials or telemetry.
- `POST /telemetry`: one validated envelope, at most 4 KiB. Returns 202 for new intake, 200 for an identical retained event, 409 for conflicting content, or 503 when capacity is full.
- `GET /events?after_sequence=0&limit=100`: bounded pages for the finite downstream consumer. Both write/read routes require bearer auth in live configuration.
- Every envelope requires explicit `simulated`, source/mission/station IDs, timestamp, and a supported kind: `water_reading`, `inspection_observation`, or `heartbeat`. Wetness is normalized 0–1000; an evidence reference is an opaque ID, not a fetched URL.

The cache uses process memory: default 5,000 events with one-hour TTL, guarded by a lock. Unexpired events are not silently evicted when full. Restarting loses the cache and changes `stream_id`; TTL expiry is disclosed with `gap_detected` and retention/cursor fields. This is short-term intake/deduplication, not durable telemetry storage or guaranteed delivery.

The separate [finite Relay consumer](../docs/fleet-consumer.md) now persists accepted envelopes and a source-bound cursor in local SQLite. It normalizes simulated water readings, retains opaque rover evidence, and requires explicit acknowledgement when the gateway resets or a gap occurs. Its default CLI uses an offline fixture; an explicit fetch performs one bounded GET. Neither service automatically forwards to cloud databases, invokes a model, or controls a robot. DigitalOcean hosting remains unverified.

## Live configuration

Set these runtime variables in the future DigitalOcean service:

| Variable | Value |
|---|---|
| `RELAY_FLEET_MODE` | `live` |
| `RELAY_FLEET_API_TOKEN` | A new random 32+ character URL-safe secret; use an encrypted runtime setting |
| `RELAY_FLEET_TTL_SECONDS` | `3600` (allowed 60–86400) |
| `RELAY_FLEET_MAX_EVENTS` | `5000` (allowed 1–10000) |

Live startup fails without a strong token. Supply `Authorization: Bearer <token>` on writes and event reads. The fixture sender reads the same token from the local environment; do not paste it into commands or commit it. A remote fixture send requires an explicit `--allow-remote` and an HTTPS origin. HTTP is permitted only for loopback. Redirects and automatic retries are disabled.

Default mock configuration rejects non-loopback telemetry clients and non-simulated inputs. Set live mode deliberately before hosting; it enables authenticated telemetry intake only, not paid AI or robot control.

## Bounded App Platform recipe

Checked 2026-09-26: the smallest listed web-service size is `apps-s-1vcpu-0.5gb`, with one shared CPU, 512 MiB RAM, and a $5/month listed rate. Service charges are prorated; the documented minimum is $0.01. App Platform's free tier covers static sites, which cannot run this FastAPI intake endpoint. Recheck the account's current quote and any event credits before creation. [Official pricing](https://docs.digitalocean.com/products/app-platform/details/pricing/).

1. Reserve a bounded deployment allowance in the existing cross-provider ledger before creating an app. Keep aggregate planned spending below $15 and total new API/cloud spending below $20. Set a specific UTC destruction deadline (for example, four hours after creation), a responsible operator, and an explicit shutdown step. A reminder or budget alert alone does not stop billing. Do not assume event credits are active.
2. Use an explicit project-owned source repository or image; no existing unrelated app is reused. Choose one web-service component, one instance, the smallest listed size, no managed database, no dedicated IP, and no additional worker. Disable automatic redeployment. These are proposed settings, not an already-created app.
3. Reuse the repository's existing Python image/Dockerfile once it is available. Override its run command with:

   ```text
   python -m uvicorn relay_gateway.fleet_gateway:app --host 0.0.0.0 --port 8080
   ```

4. Set public HTTP port 8080, route `/`, health check `/health`, and the live runtime variables above. Keep the API token out of the image/build arguments. App Platform requires the service to bind to `0.0.0.0`; it supports a run-command override for Dockerfile deployments. [Creation documentation](https://docs.digitalocean.com/products/app-platform/how-to/create-apps/).
5. Record the new app ID, creation time, current quote, actual hostname, and destruction deadline. After its health check succeeds, send the finite fixture using its verified HTTPS origin and `--allow-remote`. Save the intake result and authenticated readback as evidence. Do not claim a DigitalOcean integration until that path has worked there.
6. Before the reserved lifetime ends, export needed telemetry, destroy only this app, verify its absence, and reconcile actual/estimated usage in the shared ledger. Container restarts discard this memory cache; save evidence first. If access or pricing prevents a bounded deployment, keep the local proof and report that blocker.

No deploy command is run by importing the service or executing its fixture tests. No new cost is incurred by this recipe alone.
