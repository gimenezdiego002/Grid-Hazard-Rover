# Eight MLH integrations

The [official ShellHacks MLH prize page](https://www.mlh.com/events/shellhacks-b9/prizes) lists the eight categories below (checked 2026-09-26). Category listings alone do not confirm a submission's eligibility or active credits. The distinction here is **implemented/tested locally**, **connected to an actual provider**, and **demonstrated end to end**.

| Category | Relay responsibility | Live proof required | Current status |
|---|---|---|---|
| Best Use of Gemini API | Turn selected sensor metadata and bounded reference passages into structured suspected-hazard findings | Real SDK response, model/usage metadata, validated finding and source evidence | Two live text-only smoke calls verified on synthetic readings, including the new GCP project key. Reference propagation is tested offline. No camera decoding or physical evidence proof; dashboard stays mock. |
| Best Use of ElevenLabs | Generate reviewed spoken mission briefings and incident announcements for StackChan | Real generated audio, its corresponding report, and playback | Reviewed-text adapter, output validation and cache tested. Guarded CLI reserves shared funds before explicit live dispatch and retains uncertain billing. Account key/voice absent; integrated replay returns a descriptor with no audio. |
| Best Use of Solana | Anchor a finalized report hash on devnet | Confirmed transaction link; original report validates and modified copy fails | Receipt/signing/verification adapter and bounded [receipt CLI](receipt-cli.md) implemented. Dedicated devnet wallet created. One airdrop failed with `-32603`; latest read-only check verified zero lamports. No report transaction submitted. Integrated replay verifies local hashes only. |
| Best Use of Tiger Data | Store timestamped sensor readings and query the window around an incident | Real batch insert, idempotent replay and time-range read-back | PostgreSQL adapter, schema and bounded shared-ledger proof CLI implemented/tested. Database credentials/service/schema not connected. |
| Best Use of DigitalOcean | Host a separate persistent fleet simulator/device gateway | Deployed gateway, health check and mission event through it | Standalone gateway and finite durable local consumer implemented; loopback insertion/deduplication, gap review and recovery export tested. DigitalOcean account/deployment absent; no automatic forwarding to cloud sinks. |
| Best Use of Snowflake API | Retrieve reference passages with source IDs for Gemini's analysis | Real bounded SQL API result and retrieved sources used by the model | SQL REST adapter, bootstrap and bounded proof CLI implemented/tested; saved passages can feed the guarded Gemini CLI. Account/token/warehouse/schema absent; replay uses explicitly synthetic passages. No continuous Cortex Search service required. |
| Best Use of MongoDB Atlas | Persist mission snapshots, reports and review state | Upsert a reviewed mission, recreate the client, retrieve the same remote record | Atomic upsert/read-back adapter and bounded fresh-client proof CLI implemented/tested. Atlas credentials/network access absent; replay uses an in-memory transport. |
| Best Domain Name from GoDaddy Registry | Publish the project on an eligible registered domain | Verified offer/extension eligibility, domain ownership and live HTTPS app | MLH offer/login and eligible domain selection pending; no domain registered. |

## GCP foundation

GCP is the primary cloud. The user selected a separate project: `shellhacks-relay-2026-0926`, region `us-east1`. The project exists with linked billing, required APIs enabled, dedicated service accounts, the `relay` Artifact Registry repository, a private evidence bucket with seven-day lifecycle, and a staging bucket with two-day lifecycle. The restricted Gemini project key is stored in Secret Manager as `relay-gemini-api-key`; the dashboard receives no secret.

The private [Cloud Run service](https://relay-gateway-345149168663.us-east1.run.app) is deployed as revision `relay-gateway-00005-z5h`. Verification observed unauthenticated HTTP 403, authenticated health HTTP 200, and an authenticated integration replay completing six mock stages with 12 rows. The new mission planner completed a directed rehearsal (4/4); a zero-request mission stayed `needs_review` after simulated acknowledgement. Verification checked 100% traffic to the expected revision before and after these requests. Its limits are minimum zero/maximum one instance, concurrency one, one CPU, 512 MiB, and request-based billing. The API remains mock-only and has no secret attached. A synthetic report was uploaded to private Cloud Storage and read back identical to the local file. See [cloud setup evidence](cloud-setup.md) and [deployment/cleanup notes](../deploy/README.md).

Those results verify GCP hosting/storage and the separate Gemini calls. They do not turn the hosted adapter fixtures into live Atlas, Tiger Data, Snowflake, ElevenLabs or Solana connections. Gemini remains the LLM; Snowflake's implementation is bounded SQL API retrieval from an existing warehouse.

## Run the implemented offline pipeline

```powershell
.\.venv\Scripts\python.exe -m relay_gateway integrations
```

Or start the dashboard with `scripts/start-demo.ps1`, open [the integration section](http://127.0.0.1:8765/#integrations), and choose **Run integration replay**. The HTTP route is `POST /api/integrations/demo`. It always uses mocks and exposes reference IDs, model findings, telemetry deduplication, report read-back, a briefing descriptor and local receipt/tamper verification. It does not initialize the live spending ledger. See [the integrated demo contract](integrated-demo.md).

Tests are meaningful implementation evidence, but they are not remote-account evidence. Default mock code remains offline even when credentials and live-enable flags are present. For data account prerequisites and SQL setup, see [data integrations](data-integrations.md). For the independent fleet service, see [DigitalOcean setup](../deploy/digitalocean.md).

The saved [offline rehearsal packet](rehearsal-packet.md) checks both mission modes, refusal, comparison and all six mock stages. The current Cloud Run image includes the proof CLI modules and dashboard recovery. Only the mock HTTP workflow was exercised in cloud; the CLI proofs remain local and do not establish live provider connections. Served HTML/JavaScript hashes and the actual revision digest were verified against the tested source. See [software verification](../artifacts/software-verification.json) and [devnet balance check](../artifacts/solana-balance-check.json).

## Keep the dependencies useful

Telemetry goes to Tiger Data; mutable mission documents go to Atlas; reference material and completed-incident history go to Snowflake. Images belong in object storage, with references in records. One significant incident may trigger one announcement and one finalized receipt. Do not call speech generation, historical search, or a blockchain transaction on every sensor sample merely to increase integration counts.

A report hash proves consistency with the anchored bytes. It does not validate a sensor, establish physical truth, or demonstrate a real-world inspection. Use devnet for prototype receipts and label them accordingly.

The earlier Gemini smoke recorded 202 tokens and $0.000179 estimated model cost in `.state/gemini-smoke.json`. The new project-key smoke recorded 275 tokens and $0.0002565 estimated model cost in `.state/gemini-project-smoke.json`; the shared ledger rounds that upward to $0.000257. Both used synthetic text readings. The cumulative recorded model estimate is $0.000436, with $3 reserved for cloud setup at this checkpoint; actual provider invoices remain unverified. The current cumulative gate is `.state/spend.sqlite`, initialized from the earlier setup history. Do not use a fresh store or old JSON snapshot to reset the allowance.

Track credentials available, connection verified, demo captured, and incremental cost separately for every provider. The offline `scripts/check-connections.py` inventory reports environment presence only; optional metadata checks prove only that endpoint check. Solana uses a fixed devnet RPC and a dedicated local wallet, not arbitrary RPC/keypair environment variables. No free/trial tier is assumed. New charges share the aggregate policy in [budget-policy.md](budget-policy.md) and [spending contract](integration-contract.md).
