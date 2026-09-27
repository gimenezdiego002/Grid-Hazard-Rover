# Working-status audit — September 26, 2026

Audited around 22:01 EDT on branch `relay/inspection-system`, source commit `8c549b681ea4c53eff514a3b8aaa50ed53e45f49`. Scope: this checkout, its recorded provider evidence, current local services, and fresh offline verification. Remote provider proofs below are historical observations; no remote account was rechecked or charged by this audit. No application behavior, credentials, cloud resources, or hardware were changed.

**Assessment:** Relay has a working simulated inspection demo, four separately demonstrated live application integrations, one additional database-side proof, private GCP hosting evidence, and real local OpenJev inference. It does not yet have a joined live incident workflow, a confirmed Solana receipt, a DigitalOcean deployment, verified domain handoff, or demonstrated physical inspection.

## Provider audit

| Service | Demonstrated capability | Remaining acceptance check |
|---|---|---|
| ElevenLabs | One guarded live request generated a 165-character synthetic briefing with River / Eleven Flash v2.5. The 10.263-second MP3 was fully decoded previously; this audit verified the existing 165,137-byte file against its recorded SHA-256. | Audible semantic review, linkage to the connected incident report, and StackChan playback. Dashboard speech remains a mock descriptor. |
| Snowflake | Real SQL API retrieval returned two exact synthetic reference passages, source IDs, and a statement handle. | Demonstrate those retrieved passages in a successful live Gemini response. Historical-incident retrieval and Cortex Search are not implemented. Saved warehouse state is suspended with auto-resume disabled. |
| MongoDB Atlas | Live synthetic mission insertion, simulated-review update without duplicate insertion, and identical digest read-back through a fresh adapter. | Connect an actual workflow's report/review to persistence. Dashboard mission state remains in memory; real human review and team geospatial collections are not proven by this test. |
| Tiger Data | Provider browser SQL verified schema/index setup, one insert, zero duplicate inserts, exact incident-window retrieval, and a separate post-commit read. Python adapter and offline tests exist. | Resolve the application's TLS connection while retaining certificate/hostname checks, verify rotated-password authentication, create the restricted runtime user, and run the adapter proof. Browser SQL success does not establish application connectivity. |
| Solana | Dedicated devnet wallet, signing implementation, bounded receipt CLI, local hash validation and modified-report rejection. | Obtain devnet funds and confirm one report-hash transaction. Recorded funding attempt failed; last recorded balance was zero. No transaction was submitted. |
| Gemini | Two successful live text-only SDK smoke calls returned validated suspected-hazard findings from synthetic readings. | Camera evidence, real sensor classification, live Snowflake reference use, and the joined mission workflow remain unproven. The separate newer Gemini/Jev role workflow made five failed requests; latest recorded failure was HTTP 400 `INVALID_ARGUMENT`, with zero successful role responses. |
| DigitalOcean | Account/project setup recorded; fleet intake service, deployment specification, and local transport/consumer tests implemented. | Deploy the app and prove authenticated event intake/read-back remotely. No DigitalOcean application deployment is recorded. |
| GoDaddy | Product role and teammate ownership of registration are documented. | Receive eligible registration/ownership and working HTTPS evidence. No verified domain handoff in this checkout. |

Primary evidence: [ElevenLabs](../artifacts/elevenlabs-live-proof.json), [Snowflake](../artifacts/snowflake-live-proof.json), [Atlas](../artifacts/mongodb-live-proof.json), [Tiger Data](../artifacts/tiger-browser-proof.json), [Solana balance](../artifacts/solana-balance-check.json), [receipt verification](../artifacts/receipt-cli-verification.json), [Gemini/Jev failures](../artifacts/jev-verification.json), and [integration inventory](mlh-integrations.md). Earlier successful Gemini smoke results remain in ignored local `.state/gemini-smoke.json` and `.state/gemini-project-smoke.json`.

## Working software and infrastructure

- **Relay dashboard and API:** current local `GET http://127.0.0.1:8765/health` returned HTTP 200, `provider_mode=mock`, paid APIs disabled, and actuation disabled. Preset/directed missions, assignment, start/pause/resume/cancel, ordered task completion, simulated review gating, and repeated-action recovery are implemented. A refused analysis remains `needs_review` after acknowledgement. Mission state is process-local and does not survive a service restart.
- **Six-stage replay:** mock Snowflake references → mock Gemini findings → mock Tiger telemetry → mock Atlas report → ElevenLabs descriptor → local Solana hash/tamper checks. Twelve synthetic readings complete the replay. Explicit `live=False` construction prevents environment credentials from silently activating providers.
- **Fleet software:** authenticated intake, bounded retention, event identity/digest checks and deduplication; finite consumer with durable SQLite events/cursor, gap/reset detection, and read-only recovery export. Local loopback integration is tested. The mock gateway and current finite consumer accept only simulated envelopes; authenticated live intake can accept real-labeled telemetry. No automatic inference, cloud sink forwarding, or physical device connection is established. Gateway retention is process memory with TTL.
- **Pollard and spending controls:** request/token/mission admission, audit evidence, and the canonical cumulative SQLite spend ledger are implemented and tested. They are application controls, not provider billing hard stops. Cloud replicas do not have a demonstrated shared live-spending store.
- **Comparison:** the canonical synthetic fixture reproduces 12 baseline requests versus 1 event-triggered request while detecting its one labeled episode. This is a simulation result, not a measured accuracy, battery, water, energy, or carbon improvement.
- **GCP:** saved evidence proves private Cloud Run revision `relay-gateway-00006-w89`, unauthenticated 403, authenticated health and mock replay, mission actions, and private Cloud Storage report read-back. No live provider secrets were attached to that service. Remote health was not rechecked during this audit. Newer local source/status copy is not established as deployed.
- **OpenJev:** a real pinned model ran on the RTX 4090 Laptop GPU, including one authenticated ngrok inference. Current local status returned ready and idle, with 6/100 requests used. Dry monitoring selected continuation; wet/conflicting synthetic cases abstained below the confidence threshold and preserved review/alarm. Gemini roles in these runs remain fixtures. Hosted TypeSafe Jev has no successful live proof.
- **Hardware:** device inventory and bring-up instructions exist. Camera capture, calibrated sensor readings, robot movement, arm actions, and physical StackChan playback have no verified handoff here.
- **Grid Hazard Rover:** canonical `Project`, `Record`, `Hazard`, `Match`, and `RiskCell` schemas validate. The `backend/`, `frontend/`, and `rover/` implementations are absent in this checkout. Relay's `web/` dashboard is not the team's Leaflet geographic risk dashboard. Utility spatial/timeline matching, Coordination Risk Index calculation, public-record ingestion, photo upload/classification, risk map, Google Routes, Discord alerts, and Vercel deployment are not demonstrated here. This does not establish the state of other teammate branches or machines.

Supporting evidence: [Cloud Run verification](../artifacts/cloud-verification.json), [OpenJev runtime](../artifacts/jev-openjev-runtime.json), [ngrok proof](../artifacts/jev-openjev-ngrok-proof.json), [fleet consumer](fleet-consumer.md), [mission contract](missions.md), and [hardware handoff](hardware-bringup.md).

## Fresh verification

| Check | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q tests shared/test_schemas.py` | 727 passed, one existing Starlette/httpx deprecation warning, 21.29 seconds |
| `node --test tests/test_dashboard_recovery.cjs` | 8 passed |
| `node --check web/app.js` | Passed |
| `.venv\Scripts\python.exe -m pip check` | No broken requirements |
| `.venv\Scripts\python.exe -m shared.test_schemas` | Schema contract checks passed |
| `scripts/rehearse-demo.py` `build_packet()` invoked offline | 29/29 checks; preset and directed complete, zero-request refusal stays `needs_review`, six-stage replay complete |
| Local dashboard `/health` | HTTP 200, mock-only |
| `.venv\Scripts\python.exe -m relay_gateway.jev_open_cli status --local --port 8770` | Real local worker ready, idle, 6/100 requests; no inference triggered |
| Existing ElevenLabs audio | File present; SHA-256 matches saved proof |
| `SpendLedger().snapshot()` | Canonical ledger read successfully; tracked current-spend snapshot matches |

Older verification artifacts describe earlier commits and test totals. Their counts and budget snapshots should not replace these fresh results or the canonical ledger.

## Availability and spending

The Snowflake token's recorded expiry is **September 27, 2026 at 20:34:29 EDT**. Atlas uses a one-day runtime user and temporary operator-IP access; exact user expiry is absent from shared evidence. The [latest ngrok lease](../artifacts/jev-openjev-ngrok-expiry.json) expires **September 28 at 05:00 EDT**, superseding its earlier proof's deadline. These are material demo dependencies, not current remote-health guarantees.

Canonical ledger at audit time: **$0.000436 settled estimated usage + $5.458659 reservations = $5.459095 committed**, leaving **$9.540905** within the $15 operating envelope. The separate $5 contingency remains held inside the $20 total authorization. Unknown-status reservations total $0.258659. Actual provider invoices remain unverified. This audit issued no billable provider calls; existing resource lifetimes remain separate from the audit's activity.

## Completion priorities

1. Fix the failed Gemini role request and prove live use of the already-retrieved Snowflake passages.
2. Restore Tiger adapter connectivity and prove idempotent telemetry insertion/time-window retrieval through application code.
3. Link one incident identity and evidence digest through telemetry, source-grounded finding, reviewed Atlas report, and ElevenLabs audio; verify audible playback.
4. Fund the dedicated devnet wallet and confirm one report receipt with original-pass/modified-fail verification.
5. Deploy and verify the DigitalOcean fleet service, obtain the teammate's domain/HTTPS handoff, and plan expiring credential renewal before the demonstration.
6. With an operator present, connect a real device/sensor/camera and record the physical evidence separately from simulations. Coordinate any Grid Hazard Rover bridge with its owners.

**Done when:** one bounded, explicitly enabled live incident can be traced across those providers with exact source IDs, report digest, remote read-back, playable speech, and confirmed devnet transaction; hosting/domain and physical-device proof are recorded separately. Until then, describe the product as a working simulated demo with separate live component proofs.
