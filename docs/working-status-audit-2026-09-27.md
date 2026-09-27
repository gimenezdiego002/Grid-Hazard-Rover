# Relay audit — September 27, 2026

Checked around 10:56–11:05 EDT against commit `212800751979248d2e2fcaa2472268362fa9e896` plus the existing uncommitted simulator, arm, Bluetooth, API and documentation work. This is a snapshot of the local working tree, not just committed or deployed code. Existing work was preserved. Provider proofs were reinspected; this audit issued no remote provider requests, inference, Bluetooth commands, physical motion, or new cloud deployment.

The companion [Devpost writeup](devpost-writeup.md) translates these findings into submission prose. The [official MLH ShellHacks page](https://www.mlh.com/events/shellhacks-b9/prizes) was checked again and lists the same eight category technologies. This audit does not establish eligibility or cover unlisted organizer awards.

## Changes since the previous audit

- New project-owned simulated robot controllers in `robotcode/` cover patrol/report, directed inspection, carrier inspection, kit pickup and return, and transfer failure handling. Freenove FNK0052 is now operator-confirmed; vendor source is pinned and attributed separately.
- A spatial rover/crawler simulator adds local metric navigation, obstacle clearance, directed targets, review, return, failure injection and modeled inference accounting.
- An independent six-joint arm simulator demonstrates marker pick/place, virtual pose capture/replay, and explicit fault recovery. Physical motion parsers reject its simulation exports.
- Real LeArm BLE discovery, GATT inspection, and a non-motion controller voltage response are recorded. No motion command was sent in that proof; physical position read-back failed to respond.
- The user additionally reports that a teammate completed the **domain and a physical robot demo**. The user confirmed **fieldsight.biz**, registration through the GoDaddy Registry offer, and that the domain is **not connected yet**. The physical demo's exact device/action/control method was not supplied; the public draft credits a physical demonstration without attributing it to Relay's control path. These are direct team-reported results, not independently observed by this audit.
- The local OpenJev worker, which answered the previous audit's health check, is now unavailable or unverified. Its recorded successful inferences remain historical evidence.
- The existing four live application proofs have not changed: Gemini, ElevenLabs, MongoDB Atlas, and Snowflake. Tiger Data still has database-side proof without a completed local-adapter connection. No new DigitalOcean deployment or Solana transaction evidence was found.

## Technology claims and their evidence

| Technology | Supported claim | Boundary / next proof |
|---|---|---|
| Gemini | Two real text-only SDK calls on synthetic readings, with validated findings and provider usage. | No camera proof or live Snowflake-source use. The newer supervisor's five attempts had zero successful role responses; latest failure HTTP 400 `INVALID_ARGUMENT`. |
| ElevenLabs | Real 165-character synthetic briefing produced a 10.263-second MP3 using River / Eleven Flash v2.5. Existing file and digest match today; full decoding was recorded previously. | Audible semantic review, connected-report linkage and StackChan playback remain unverified. |
| MongoDB Atlas | Insert, simulated-review update without duplicate insertion, and exact fresh-client digest read-back. | Latest snapshot only, not revision history. Dashboard missions are still process-local; joined workflow remains mocked. |
| Snowflake | Authenticated SQL API returned two exact synthetic passages and a statement handle. | No demonstrated live Gemini use; no Cortex Search/inference or completed-incident retrieval. Saved warehouse state is suspended, auto-resume disabled. |
| Tiger Data | Browser SQL on the real service proves insert=1, duplicate insert=0, and exact post-commit incident-window read-back. | TLS/application access unresolved; restricted runtime user absent. Ordinary indexed PostgreSQL table, not a hypertable. |
| Solana | Receipt hashing, signing and verification implementation; original-pass/modified-fail offline proof. | Last recorded balance zero; funding failed; no submitted or confirmed report transaction. |
| DigitalOcean | Account/project, authenticated fleet gateway, finite consumer, local loopback tests and App Platform specification. | No deployed app or remote intake/read-back evidence. |
| GoDaddy / domain | User confirms teammate registered **fieldsight.biz** through the GoDaddy Registry offer. | User says it is not connected yet. No hosted site or HTTPS connection is claimed; registration was not independently rechecked. |
| GCP | Historical private Cloud Run mock health/replay/missions and Cloud Storage exact report read-back. | Revision `relay-gateway-00006-w89` predates the new simulators. No current remote health check or new deployment. |
| Pollard | Actual runtime integration, meters, durable recording/verification, budget refusal; shared cross-provider ledger is separate. | Mock comparison is workload-specific; application admission is not a provider invoice cap. |
| OpenJev / ngrok | Recorded real laptop GPU inferences and an authenticated HTTPS inference; dry continuation and wet/conflicting abstention. | Worker currently unavailable/unverified; other Gemini roles were fixtures. No demonstrated improvement in overall accuracy/cost. Hosted TypeSafe Jev has no live proof. |
| LeArm / Bleak | Real BLE connection and controller-reported 7,881 mV. User additionally reports a completed physical robot demo. | No reply to position query; zero motion commands in saved proof. Physical demo's device/action/control method was not supplied, so it is not attributed to the Relay control path. |

Evidence: [provider inventory](mlh-integrations.md), [ElevenLabs](../artifacts/elevenlabs-live-proof.json), [Atlas](../artifacts/mongodb-live-proof.json), [Snowflake](../artifacts/snowflake-live-proof.json), [Tiger](../artifacts/tiger-browser-proof.json), [Solana](../artifacts/solana-balance-check.json), [Gemini role failures](../artifacts/jev-verification.json), [Cloud Run](../artifacts/cloud-verification.json), [OpenJev](../artifacts/jev-openjev-runtime.json), [ngrok](../artifacts/jev-openjev-ngrok-proof.json), and [LeArm BLE](../artifacts/learm-bluetooth-proof.json).

## Fresh checks

| Command / check | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **931 passed, 21 subtests passed**, one existing Starlette/httpx deprecation warning; 26.75 seconds. Includes `tests` and `robotcode/tests`. |
| `node --test tests/test_dashboard_recovery.cjs tests/test_simulator_ui.cjs tests/test_arm_simulator_ui.cjs` | **35 passed**. |
| `node --check` for `web/app.js`, `web/simulator.js`, and `web/arm-simulator.js` | Passed. |
| `.venv\Scripts\python.exe -m pip check` | No broken requirements. |
| `.venv\Scripts\python.exe -m shared.test_schemas` | Contract checks passed. |
| Original `scripts/rehearse-demo.py` `build_packet()` | **29/29 passed**. |
| `scripts/rehearse-simulator.py` `rehearse()` | Preset and directed missions completed; exhausted allowance remained `needs_review`. |
| `scripts/rehearse-arm-simulator.py` `rehearse()` | Preset, taught replay, grip-loss freeze and explicit recovery completed; no hardware/model calls. |
| Current local HTTP on port 8766 | Health, spatial state and arm state all returned 200; mock/simulated and actuation disabled. |
| Older local HTTP on port 8765 | Health/spatial returned 200; arm route unavailable. Use the verified newer port for the full local demo. |
| Existing ElevenLabs audio | 165,137-byte file exists and SHA-256 matches proof. |
| OpenJev read-only local status | Worker unavailable or unverified; no restart/inference attempted. |
| `SpendLedger().snapshot()` | Canonical ledger totals read successfully. |

Rehearsals were invoked through `runpy` in isolated in-memory instances, without modifying the running browser scenes or duplicating saved rehearsal folders. Test success does not validate physical motion or current remote availability.

## Numbers suitable for a public writeup

- Original twelve-reading fixture: **12 baseline versus 1 economy mock model call**, with **3,743 versus 312 simulated tokens**. This is 91.67% fewer calls on that fixture, not measured production or energy savings.
- Fresh spatial preset: **80 modeled baseline versus 3 admitted requests**. Of 80 observations, 57 were filtered as routine and 20 as duplicates. Actual model requests and API cost were zero; token/dollar calculations used fixed illustrative assumptions.
- Fresh virtual arm: preset completed; two captured virtual poses replayed twice; grip loss froze progress and explicit recovery/resume completed. Taught pose replay is not an independently demonstrated physical pick-and-place.
- Four separate live application integrations plus Tiger database-side proof and user-confirmed GoDaddy registration. This is separate from physical-demo reports, cloud hosting and local GPU inference; it does not mean all services ran together live.

## Submission boundaries

The simulator is a local floor plan, not the Grid Hazard Rover Leaflet utility map. `/shared` schemas are present and valid; the team-owned `backend/`, `frontend/`, and `rover/` implementations are absent in this checkout. No Relay connection to utility matching, risk calculation, public-record ingestion or photo ingest is demonstrated here. Other teammate work may exist elsewhere.

The separate Jev comparison must not be promoted as a proven efficiency improvement: its recorded synthetic comparison reduced Gemini attempts while increasing overall attempts/tokens, with the same missed hazard frames. The Pollard fixture and spatial modeled comparison above are distinct experiments.

Snowflake's saved token expires September 27 at **20:34:29 EDT**. Atlas access is temporary; exact expiry is not in the shared proof. The recorded ngrok lease ends September 28 at **05:00 EDT**, but that lease does not establish current worker availability. None of these private runtime details needs to be included in the public project description.

Budget snapshot before the separate Vercel reservation: **$0.000436 estimated settled usage + $5.458659 reservations = $5.459095 committed**, with **$9.540905** left in the $15 operating envelope and $5 contingency retained inside the $20 authorization. See the [current spending snapshot](current-spend.json) for the later totals including Vercel. Actual invoices remain unknown. Existing resources can accrue costs independently of this audit.

**Done when for this audit:** current source and artifacts are reconciled, fresh verification is recorded, new teammate-reported work is attributed accurately, and each Devpost technology paragraph distinguishes implemented behavior, observed proof, and remaining work. Completing deployments, repairing live integrations, or actuating robots is outside this writing request.
