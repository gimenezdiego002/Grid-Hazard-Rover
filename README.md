# Grid Hazard Rover — Relay inspection branch

Source repository: [gimenezdiego002/Grid-Hazard-Rover](https://github.com/gimenezdiego002/Grid-Hazard-Rover), branch `relay/inspection-system`. This branch preserves the team's shared schemas and adds the existing Relay inspection prototype in `src/relay_gateway`, `web`, `tests` and its supporting files. It does not yet connect Relay to the team's photo-ingest, utility coordination or geographic risk workflow.

Credentials, runtime state, raw attachments and private operator handoffs stay outside Git. Scheduled synchronization targets only `relay/inspection-system` and preserves the team's `main` and other branches. Other clones should contribute offline changes; all live spending remains on the operator's canonical ledger.

A student-built robot fleet that investigates suspected leaks while budgeting its AI work. Gemini is the model provider, GCP is the primary cloud, and a local coordinator owns mission decisions and device adapters. A complete offline workflow now exercises reference retrieval, findings, telemetry storage, report persistence, a briefing descriptor and receipt verification while hardware is assembled.

**Current boundary:** the dashboard, API and integration replay always use synthetic data and mock providers. Live Gemini calls, ElevenLabs audio generation, Atlas mission persistence and Snowflake SQL API reference retrieval have been verified separately using synthetic inputs. Listening review, the joined incident workflow and physical-device playback remain unverified. A passing fixture is not a connected account, blockchain transaction, or physical inspection. See [the per-provider status](docs/mlh-integrations.md).

All eight published MLH prize categories have a defined role and a concrete acceptance check in [the prize submission plan](docs/mlh-submission.md). This is complete design coverage, not eight completed live integrations or confirmed prize eligibility.

The separate [Gemini–Jev–Pollard supervisor and comparison](docs/jev-demo.md) rehearses mission supervision on synthetic fixtures. It has no successful live proof and does not establish an efficiency improvement.

The separate GCP project `shellhacks-relay-2026-0926` has linked billing, enabled APIs, dedicated service accounts, the `relay` Artifact Registry repository in `us-east1`, a private evidence bucket with a seven-day lifecycle, and a staging bucket with a two-day lifecycle. A restricted project Gemini API key is stored in Secret Manager as `relay-gemini-api-key`. The mock dashboard receives no secret.

The [private Cloud Run service](https://relay-gateway-345149168663.us-east1.run.app) is deployed and verified: unauthenticated requests return 403; authenticated health and integrated-replay requests succeed, with six mock stages and 12 telemetry rows. A synthetic report was uploaded to private Cloud Storage and read back unchanged. Cloud Run uses minimum zero, maximum one instance and request-based billing. See [cloud verification](docs/cloud-setup.md) and [deployment notes](deploy/README.md) for access, resource controls and cleanup.

Two live text-only Gemini smoke calls used synthetic readings. The latest call with the project key reported **275 tokens**, estimated **$0.0002565**, rounded upward to **$0.000257** in the shared ledger. Including the earlier $0.000179 call, the recorded model estimate is **$0.000436**. Reservations now total **$5.458659**: GCP $3, ngrok $1 for the OpenJev tunnel lease through September 28 at 05:00 EDT, separate from Cloud Run, Tiger Data $0.10, Atlas resource $0.10 plus $0.10 for its completed proof with unknown billing, Snowflake setup $1 plus $0.10 for its completed SQL API proof with unknown billing, ElevenLabs $0.05 held with unknown billing, and $0.008659 held unknown for five attempted Gemini role requests in the Jev task that returned no usable usage/results. Total commitments are **$5.459095**, leaving **$9.540905** in the planned envelope. These are estimates/reservations, not paid invoice totals. Current admission and reconciliation use `.state/spend.sqlite`; [the spending contract](docs/integration-contract.md) explains its scope.

## Start with the local replay

From the repository root, use Python 3.12+. Reuse the project's `.venv` if it already exists; otherwise create it once:

```powershell
py -3.12 -m venv .venv
```

Install the local package into that environment, then run the mock replay. Installing dependencies does not call the model or provision cloud resources.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,integrations]"
.\.venv\Scripts\python.exe -m relay_gateway demo --scenario scenarios/leak.json
.\.venv\Scripts\python.exe -m relay_gateway compare --scenario scenarios/leak.json
.\.venv\Scripts\python.exe -m relay_gateway integrations
```

The replay commands require no API key, paid model request, cloud deployment, or robot motion. `integrations` is strictly offline and has no live option. It uses a temporary Pollard recording and leaves the real spending ledger unchanged. Follow the backend's `--help` output for available options. If using a different prepared environment, replace the Python executable path accordingly.

**Fresh clones are for offline development.** The canonical spending database is intentionally not in Git. Default live admission refuses a missing or uninitialized `.state/spend.sqlite`; it cannot create a new allowance from historical JSON. Keep live operations on the existing operator checkout. A deliberate migration must preserve the full canonical ledger and stop its old callers first; copied independent ledgers cannot enforce one shared budget. `docs/current-spend.json` is review evidence, not a replacement spending store. Cloud verification also requires the operator's ignored `.state/cloud-config.json` and existing authenticated account.

For a saved teammate/judge rehearsal, run `.\.venv\Scripts\python.exe scripts/rehearse-demo.py`. It checks preset and directed missions, the refusal boundary, policy comparison and integration replay, then saves JSON evidence and a self-contained HTML fallback in a new folder under `artifacts/rehearsal`. It uses temporary mock recordings and does not alter the running dashboard. See [the rehearsal packet](docs/rehearsal-packet.md).

The fixture contains a labeled, simulated wetness event at 40 seconds. The comparison sends the same observations through fixed-interval and event-triggered policies. Any mock token counts and dollar estimates must remain labeled **simulated**; actual paid API cost for this replay is zero. See [evaluation](docs/evaluation.md) before quoting results.

## Open the local dashboard

After the Python setup above, run:

```powershell
.\scripts\start-demo.ps1
```

Open [the mission lab](http://127.0.0.1:8765). The server binds to this laptop's loopback interface. Use the existing remote-access connection to view it from a phone; the launcher does not expose a public endpoint. Keep the terminal running and press Ctrl+C to stop it. If PowerShell blocks local scripts, the equivalent command is:

```powershell
.\.venv\Scripts\python.exe -m uvicorn relay_gateway.api:app --host 127.0.0.1 --port 8765
```

The [mission planner](http://127.0.0.1:8765/#mission-console) rehearses preset and directed inspections. Plan an assignment, start or pause it, advance simulated tasks, and explicitly simulate the review before announcing. Scout analysis uses the mock sensor fixture and the selected request allowance. Budget refusal keeps the mission in `needs_review`, even after acknowledgement. Inventory availability is simulated; no device is connected or moved. Mission records are bounded, process-local and lost on restart. See [mission behavior and API](docs/missions.md).

The dashboard also runs economy mode, compares the same fixture against fixed-interval analysis, and tests refusal with a zero-request allowance. Under [Integrations](http://127.0.0.1:8765/#integrations), choose **Run integration replay** to follow six mock adapters through one incident. Its endpoint is `POST /api/integrations/demo`, with no live mode or credential input. The replay exposes source IDs, read-back and deduplication results, a briefing descriptor, and original/modified report-hash checks.

Accounting cards come from backend responses and explicitly distinguish simulated estimates. The briefing contains no generated audio, and the receipt has no blockchain transaction. Review/finalization are fixture states, not human approval. A completed replay does not imply that a physical hazard is clear. See [the integrated demo](docs/integrated-demo.md) for inputs, output fields and verification.

If a mission response is interrupted, the dashboard reloads the saved mission and checks whether the original action was recorded. If its outcome is still unknown, **Retry pending request** reuses that exact request. Mission controls stay paused until it is resolved. The service retains at most 32 missions per process; preserve needed records before a deliberate restart. These recovery assets are also deployed on the private Cloud Run service; authenticated checks matched the served HTML and JavaScript to the recorded build and verified repeated-action read-back. The local ElevenLabs/Atlas status copy is newer than that deployment and awaits deployment/verification.

## Integration configuration

[deploy/relay.env.example](deploy/relay.env.example) lists Relay's implemented variables; no Relay command automatically loads it. The root [.env.example](.env.example) retains the Grid Hazard Rover team's configuration. Choose the template for the subsystem you are running. Keep secret values in the process environment or Secret Manager. Inventory their presence offline with:

```powershell
.\.venv\Scripts\python.exe scripts/check-connections.py
```

Explicit `--check` options perform narrow metadata/DNS checks only. They do not prove a product integration, free credits, successful generation, remote persistence or deployment. A separate guarded [Atlas live proof](artifacts/mongodb-live-proof.json) inserted a synthetic mission, updated its simulated review state without a duplicate insertion, and read back the exact digest through a fresh adapter on the isolated M0 cluster. Human review and linkage to the connected incident remain unverified. Tiger's TLS connection is unresolved. Following its [browser SQL setup proof](artifacts/snowflake-browser-proof.json), Snowflake passed a [guarded SQL API retrieval](artifacts/snowflake-live-proof.json) of both synthetic reference passages with a statement handle. The approved one-day credential uses encrypted local storage and an exact operator-IP policy; its [access record](artifacts/snowflake-access-proof.json) retains the inherited PUBLIC permissions caveat. The warehouse was suspended afterward. Live Gemini use of those passages remains pending. See [the account setup record](docs/data-integrations.md#current-account-setup-and-remaining-proof). DigitalOcean's isolated `shellhacks-relay-2026` project is confirmed, with an app-token form prepared only and no app deployed; see [its deployment recipe](deploy/digitalocean.md). The [finite fleet consumer](docs/fleet-consumer.md) passes local/loopback checks and normalizes simulated intake with a durable local cursor and explicit loss review; it does not automatically invoke models or cloud stores.

The [reviewed speech CLI](docs/speech-cli.md) defaults to a mock descriptor. One guarded live request generated the reviewed 165-character synthetic script with premade River and Eleven Flash v2.5. The 10.263220-second MP3 passed signature, hash and full-decoding checks; it was rendered for playback, but audible semantic review and robot playback remain unverified. ElevenLabs reported 83 provider-defined usage units; these are not USD. The $0.05 reservation stays held until billing is reconciled. See the [sanitized live proof](artifacts/elevenlabs-live-proof.json). The integrated replay still produces only a mock descriptor.

The [bounded data proof CLI](docs/data-integrations.md) now provides equivalent explicit admission for Atlas, Tiger Data and Snowflake. Its default is offline; a live proof requires selected existing services, account pricing/lifetime review, credentials, `RELAY_ALLOW_LIVE_DATA=1`, `--live`, an explicit operation ID and a dollar reservation. It provisions no cloud services or SQL schemas and leaves unknown billing unresolved; MongoDB upserts may create the configured database/collection. A saved Snowflake proof can be passed to `demo --references-file artifacts/snowflake-live-proof.json`; this remains mock unless `--live` is also deliberately enabled. The loader bounds and validates untrusted passages before constructing Gemini, but does not authenticate the saved file's provider claims.

The [report receipt CLI](docs/receipt-cli.md) provides bounded file-based creation and verification. Its default performs local hash checks only. Explicit live mode uses the dedicated project wallet and fixed Solana devnet RPC; it never requests funding, uses mainnet, or automatically resends an uncertain transaction. The single funding request returned error `-32603`, and the latest balance check found zero lamports; no report transaction was submitted. GoDaddy registration is teammate-managed; registration/ownership and working HTTPS evidence are awaited. These do not prevent local mock development, but they remain outstanding before claiming the sponsor integrations.

## Working agreement

- New API/cloud expenditure has a **$20 cumulative ceiling**, shared across all providers and work sessions. Automated callers target $15; the remaining $5 is contingency managed by the lead. See [budget policy](docs/budget-policy.md).
- No physical robot movement while the hardware is unattended. The laptop may run software tests and simulations while its owner is away.
- Keep secrets out of the repository and browser. A successful mock run is not a successful cloud or device connection.
- Every observation and report distinguishes simulated data from real measurements. A model's finding is provisional until reviewed.

## Team work

| Owner | Deliverable | Done when |
|---|---|---|
| Lead | Coordinator, model gateway, cost ledger, integration decisions | One command replays the incident with auditable decisions and usage |
| Teammate A | Hexapod inventory, assembly, vendor calibration | Exact model recorded; supervised walk/turn/stop and image capture demonstrated |
| Teammate B | Intellio rover and sensor station | One supervised move/stop, one accessible image, and one real timestamped sensor reading |
| First available teammate | LeArm and StackChan bring-up | One supervised arm action; one externally triggered status/audio output |

Each handoff includes device model, connection method, a reproducible vendor example, observed result, and the next blocker. Teammates do not need to design the cloud architecture to make progress.

Use [the five-minute demo runbook](docs/demo-runbook.md) for a teammate or judge rehearsal. Read [the implementation sequence](docs/project-plan.md), [all eight MLH integrations](docs/mlh-integrations.md), and [the hardware checklist](docs/hardware-bringup.md).
