# Data integrations

Implemented adapters live in `src/relay_gateway/integrations/data.py`. They use deterministic in-memory transports by default. `live=True` is explicit and required even when credentials exist. Importing a module or constructing the default adapter never opens a connection. The orchestrator must apply the [shared spending gate](integration-contract.md) before any live method call.

Implementation tests exercise provider-shaped request/response contracts without sockets. Subsequent provider evidence is recorded separately below: Atlas passed a guarded live application proof; Tiger Data passed a browser SQL proof while its local adapter remains blocked; Snowflake passed its browser SQL setup/read-back proof and a subsequent guarded SQL API retrieval of both synthetic reference passages. None of these results changes the mock-only integrated replay.

## Interfaces and ownership

| Adapter | Operations | Stored or returned data |
|---|---|---|
| `MongoMissionStore` | `upsert_mission(mission)`, `get_mission(mission_id)`, `close()` | A latest mission snapshot, keyed by mission ID; a SHA-256 of the canonical snapshot supports read-back comparison. |
| `TigerTelemetryStore` | `insert_telemetry(events)`, `query_range(mission_id, start, end, limit=100)` | Immutable timestamped sensor readings. Query windows include `start` and exclude `end`. |
| `SnowflakeReferenceStore` | `retrieve(hazard_type, limit=3)` | At most five reference records from `RELAY_REFERENCES`, including source ID/URL and a simulation flag. |

Each constructor accepts explicit configuration and optional `client=` injection. All three also expose `from_environment(live=False)`. The default ignores environment configuration entirely. Mock clients are public as `MockMongoClient`, `MockTigerClient`, and `MockSnowflakeClient`; an injected client in mock mode must explicitly declare `relay_mock=True`.

Results carry `provider`, `mode`, `status`, `simulated`, `evidence`, `usage`, `estimated_usd` and `actual_billed_usd`, plus the operation's records/counts. `completed` means the operation returned a valid result, not that a provider invoice was reconciled. Live costs are `null` because these operations do not supply billable usage; the orchestrator retains the reservation until independent reconciliation. Exceptions and incomplete responses return `unknown` with no native error text. There are no automatic retries.

### MongoDB Atlas

Configuration: `MONGODB_URI` or `POLLARD_MONGODB_URI`; when both exist they must agree. `MONGODB_DATABASE` defaults to `POLLARD_MONGODB_DATABASE`, then `relay`. The fixed collection is `relay_missions`, separate from Pollard's recording collections. Existing `pymongo==4.15.1` is sufficient.

The upsert uses `_id=mission_id` and one `$set` of the snapshot and digest. Repeating an identical snapshot does not insert a second document. A reviewed snapshot intentionally replaces the previous snapshot for that mission; it is not a revision-history store. Mission payloads must be finite JSON, at most 256 KB, with a string `mission_id` and a Boolean `simulated` when supplied. Mongo's unique `_id` protects identity. This uses the driver's documented [update/upsert operation](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/update/).

Live connections require validated TLS, majority writes, five-second client/selection/socket timeouts, and no automatic read/write retries. Insecure TLS URI options are rejected. Certificate and hostname verification follow [PyMongo's TLS guidance](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/security/tls/).

Before live proof: select an Atlas replica set/sharded deployment, verify its actual credit/tier terms, create a limited database user, and permit the intended operator/runtime network. Do not open the cluster to all addresses as an implicit convenience. After a budget reservation, upsert a synthetic mission, change its review status, create a fresh adapter instance, and read it back. Capture the mission ID, digest, reviewed state and counts. Mock read-back across two objects sharing one mock transport does **not** prove remote persistence.

### Tiger Data

Configuration: `TIGER_DATABASE_URL`; optionally `TIGER_SSLROOTCERT` for an approved CA file. The default is the libpq system trust store. The adapter uses `psycopg[binary]==3.3.6`, verified on PyPI with Python 3.12 Windows/Linux wheels. It follows Tiger Data's [Python/PostgreSQL integration approach](https://www.tigerdata.com/learn/understanding-postgresql) and Psycopg's [bound-parameter API](https://www.psycopg.org/psycopg3/docs/basic/params.html).

Connections force `sslmode=verify-full`, which authenticates the server hostname and certificate chain; a supplied URI cannot downgrade that setting. Certificate trust must work in the actual runtime. See [PostgreSQL TLS verification](https://www.postgresql.org/docs/current/libpq-ssl.html). Connect timeout is five seconds; each SQL statement has a five-second timeout and a two-second lock timeout. A batch has at most 100 events in one transaction; statement timeouts apply per statement, not to the entire batch.

Apply [the telemetry schema](../deploy/sql/tiger-telemetry.sql) manually to an already selected, budgeted Tiger Data service. The SQL does not provision a database service. Give the runtime user `SELECT` and `INSERT` on `relay_telemetry`; schema creation uses a separate authorized setup role. The prototype uses an ordinary indexed PostgreSQL table so `(mission_id,event_id)` remains unique independently of observation time.

Each event has `mission_id`, `event_id`, `robot_id`, timezone-aware `observed_at`, `kind`, nullable integer `value_milli`, Boolean `simulated`, and optional `latitude`/`longitude`. The simulator's `timestamp_seconds` must be converted using a documented mission start timestamp. Do not substitute the current wall clock on every replay; that would misrepresent observation times. Ground-truth labels stay out of these operational records.

Insertion uses bound parameters and `ON CONFLICT (mission_id,event_id) DO NOTHING`, followed by a bounded read-back of the submitted identities in the same transaction. An identical replay succeeds without a duplicate. If any existing identity has a different payload, the operation returns `status: "failed"`, `error: "telemetry_identity_conflict"`, and the conflicting IDs. The entire batch rolls back, including otherwise-new events; original readings remain unchanged. Corrections require a new event identity. Conflicting duplicate IDs within a single submitted batch are rejected before connecting.

The adapter only inserts and reads; it never updates or deletes existing rows. With PostgreSQL's normal READ COMMITTED isolation, the uniqueness check waits for competing inserts, and the subsequent read-back verifies their committed payloads before this batch commits. Input identities are sorted to keep insertion order consistent. The runtime still needs only `SELECT`/`INSERT`; no broad update permission is added. See [PostgreSQL conflict handling](https://www.postgresql.org/docs/current/sql-insert.html). Schema changes or administrators mutating old rows are outside this insert-only contract.

Live proof: insert a small synthetic batch, repeat it and observe zero additional inserts, then read its exact time window. Capture event IDs, counts, UTC timestamps and simulation flags. Use a distinct mission ID for a new physical mission. Query results are bounded to 100 records and an indexed mission/time window.

### Snowflake SQL API

Configuration: `SNOWFLAKE_ACCOUNT` as the account identifier rather than a URL; `SNOWFLAKE_TOKEN`; `SNOWFLAKE_DATABASE`; `SNOWFLAKE_SCHEMA`; `SNOWFLAKE_WAREHOUSE`; optional `SNOWFLAKE_ROLE` and `SNOWFLAKE_TOKEN_TYPE`. Supported token types are `PROGRAMMATIC_ACCESS_TOKEN` (default), `OAUTH`, and `KEYPAIR_JWT`. Use an expiring role-restricted token and the selected account's network policy. Review inherited PUBLIC privileges as part of the effective credential scope; role restriction alone does not make it strictly read-only. No Snowflake SDK is needed: the adapter uses Python's HTTPS client with certificate verification and no redirect forwarding.

Apply [the reference-table SQL](../deploy/sql/snowflake-references.sql) in an explicitly selected existing database/schema/warehouse after reserving its setup cost. It creates a small table and rerunnable synthetic seed passages, not a warehouse or continuously running Cortex Search service. The runtime role needs only warehouse/database/schema usage and table select. Standard Snowflake table uniqueness is not enforced here; run seed setup serially.

Retrieval sends one `POST /api/v2/statements` with a fixed SELECT, typed bindings for the hazard and row limit, a five-second statement timeout and ten-second HTTP timeout. The request contains the chosen warehouse/database/schema/role; it cannot submit arbitrary caller SQL. Body text is truncated to 2,000 characters by SQL and at most five rows are accepted. This follows [Snowflake's request/binding contract](https://docs.snowflake.com/en/developer-guide/sql-api/submitting-requests) and [SQL API response metadata](https://docs.snowflake.com/en/developer-guide/sql-api/reference).

An HTTP 202 remains `unknown`, retaining the statement handle for reconciliation. No automatic poll, retry or resubmission follows. Partial partition responses or malformed rows do not become successful retrievals. The seed sources use `relay://fixtures/...` and remain `simulated: true`, including when retrieved from a real account. Retrieved passages are untrusted evidence; Gemini must not treat their contents as instructions.

Live proof: reserve the selected warehouse's bounded compute cost, retrieve `standing_water`, save the statement handle and returned source identifiers, and demonstrate their use in a finding. A cold warehouse can take time to resume or cause a pending response. Do not retry blindly; reconcile the first statement. Review warehouse and storage usage afterward and suspend the demo warehouse when finished. A short SQL timeout is not a whole-account spending cap.

## Offline proof commands

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_data_integrations.py -q
```

The following complete round trip is also offline, even if the shell holds live keys:

```powershell
@'
from relay_gateway.integrations.data import MongoMissionStore, TigerTelemetryStore, SnowflakeReferenceStore

mongo = MongoMissionStore.from_environment()
assert mongo.upsert_mission({'mission_id': 'data-demo', 'simulated': True, 'review_status': 'reviewed'})['status'] == 'completed'
assert mongo.get_mission('data-demo')['mission']['review_status'] == 'reviewed'

tiger = TigerTelemetryStore.from_environment()
events = [{'mission_id': 'data-demo', 'event_id': 'water-001', 'robot_id': 'station-a',
           'observed_at': '2026-09-26T18:00:00Z', 'kind': 'water', 'value_milli': 850, 'simulated': True}]
assert tiger.insert_telemetry(events)['inserted'] == 1
assert tiger.insert_telemetry(events)['inserted'] == 0
assert len(tiger.query_range('data-demo', '2026-09-26T18:00:00Z', '2026-09-26T18:01:00Z')['rows']) == 1

snowflake = SnowflakeReferenceStore.from_environment()
assert snowflake.retrieve('standing_water')['references'][0]['simulated'] is True
print('Offline mission, telemetry, and reference round trips passed; no remote connection verified.')
'@ | .\.venv\Scripts\python.exe -
```

## Finite provider proof command

`relay_gateway.integrations.data_cli` runs a small synthetic acceptance proof for one provider. These commands remain offline even when credentials and live-enable variables exist; they read no environment configuration and never initialize the spending ledger:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.integrations.data_cli mongodb
.\.venv\Scripts\python.exe -m relay_gateway.integrations.data_cli tiger
.\.venv\Scripts\python.exe -m relay_gateway.integrations.data_cli snowflake
```

MongoDB writes a pending snapshot, updates its state to `simulated_review`, closes the writer, and retrieves the exact snapshot/digest with a separate adapter instance. In mock mode those instances deliberately share one in-memory transport; this does not prove remote persistence. Tiger Data inserts one synthetic water event, repeats that identical event, and reads back the complete payload in a fixed UTC minute. The first insert can return zero if the identical event already exists; the replay must insert zero. Snowflake retrieves at most two `standing_water` passages in one SQL API request. An empty result cannot satisfy the proof. It preserves each source's simulation flag and an available statement handle. Retrieval alone leaves `model_use_verified: false`.

For live proof, first verify the selected account's pricing/credits, target resources, schema, network permissions, and bounded resource lifetime. Reserve provisioning/setup costs separately before creating cloud services or SQL schemas; this command provisions neither. MongoDB upserts can implicitly create the configured database or `relay_missions` collection within the selected deployment, so choose a dedicated Relay database and include its storage in the reservation. Account compute/storage can outlive a query, so verify the whole planned lifetime fits the existing cumulative allowance and arrange shutdown before that lifetime ends. The `--max-usd` value is an operator-selected conservative reservation for this proof, **not a provider billing hard cap**. No free tier or zero billing is inferred.

Configure the provider locally as described above, then deliberately enable `RELAY_ALLOW_LIVE_DATA=1`. Supply a non-secret `--operation-id` and a positive `--max-usd` of at most $1 (at most six decimal places). For example, only after checking that $0.10 covers the chosen proof:

```powershell
$env:RELAY_ALLOW_LIVE_DATA = '1'
.\.venv\Scripts\python.exe -m relay_gateway.integrations.data_cli mongodb --live --operation-id atlas-proof-20260926-v1 --max-usd 0.10
.\.venv\Scripts\python.exe -m relay_gateway.integrations.data_cli tiger --live --operation-id tiger-proof-20260926-v1 --max-usd 0.10
# Historical command, already consumed; do not rerun or overwrite the saved proof:
# .\.venv\Scripts\python.exe -m relay_gateway.integrations.data_cli snowflake --live --operation-id snowflake-proof-20260926-v1 --max-usd 0.10 | Set-Content -Encoding utf8 artifacts/snowflake-live-proof.json
```

The Snowflake command above records the completed one-shot proof; do not rerun it or overwrite its saved artifact. Its operation ID is already consumed. Run only a provider whose account and specific operation have been prepared. Each live command uses the canonical `SpendLedger()` and one operation named `data:<provider>:<operation-id>`. Local arguments and adapter configuration are checked before reservation where possible. Reservation and dispatch admission precede every network operation. A repeated operation ID cannot dispatch again, even if the earlier proof failed or its output was lost. A different ID represents a deliberate new attempt and new reservation; changing IDs to evade unresolved work is not recovery. The synthetic mission identity is derived from the operation identity, keeping separate proof attempts distinct.

Each invocation performs at most three adapter operations for MongoDB/Tiger Data or one for Snowflake, with no automatic retries. A failed or uncertain step stops later steps. A pending Snowflake statement remains `unknown` and retains its handle under `steps`; reconcile that query through the account before any deliberate new attempt. Native provider errors, credential values and connection strings are never printed. The output distinguishes overall proof status, `remote_verified`, synthetic inputs, and spending status; exit code 0 means the bounded proof passed, not that its billing was reconciled.

All live results retain the entire reservation as unknown because these adapters do not supply reliable USD usage. `actual_billed_usd` and `spending.estimated_usd` remain null. If recording the unknown status fails, the dispatched reservation remains held and `spending.status` becomes `dispatched_reconciliation_required`. Reconcile the original operation against verified account usage and pricing; never settle an uncertain timeout to zero. Keep the saved JSON as proof evidence and inspect it before presenting a completion claim.

The saved Snowflake proof can feed the existing mock Gemini gateway, preserving the exact bounded reference context:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway demo --scenario scenarios/leak.json --references-file artifacts/snowflake-live-proof.json --store .state/reference-proof.sqlite
```

This replay remains mock. Loading a saved proof validates its format, not its remote provenance. A separate `--live` run requires the existing Gemini opt-in, pricing configuration, and shared spending admission; only its recorded findings/usage can demonstrate that real Gemini used the retrieved sources. Reference passages remain untrusted data, and synthetic sources remain labeled synthetic even when retrieved from a live account.

Run the command checks with `.venv\Scripts\python.exe -m pytest tests/test_data_cli.py -q`. These tests prohibit sockets, inject fake transports and temporary ledgers, and exercise admission order, duplicate rejection, uncertainty and failed read-back. Do not paste a bare `from_environment(live=True).retrieve(...)` into a shell: that bypasses the [shared budget wrapper](integration-contract.md). Supplying credentials never grants a new allowance.

## Current account setup and remaining proof

The following provider setup was observed on September 26, 2026. Created resources and accepted registration alone do not establish authenticated application access. Atlas and Snowflake have passed separate guarded live application proofs with synthetic data. Tiger Data has separate database-side browser SQL evidence; its local adapter has not passed live application proof. The adapter test suite and integrated replay remain offline.

| Provider | Verified setup | Remaining step |
|---|---|---|
| Tiger Data | Created `shellhacks-relay-telemetry` on AWS `us-east-1`, Shared compute; the Operations panel shows **750 MiB** and a **$0/hour, $0/month** quote. Provider browser SQL on PostgreSQL 18.6 applied the canonical table/index schema, asserted one synthetic insert, zero rows from identical replay, and exact bounded-window payload/count; a separate post-commit SELECT returned the same row. [Sanitized browser proof](../artifacts/tiger-browser-proof.json) and [SQL](../artifacts/tiger-browser-proof.sql). | The local adapter remains blocked: TCP connects, PostgreSQL SSL negotiation times out, and a direct TLS diagnostic failed certificate-chain validation (`SELF_SIGNED_CERT_CHAIN`, code 19). Retain certificate and hostname verification. Current rotated-password authentication is unverified, and a `SELECT`/`INSERT`-only runtime user has not been created. Browser SQL success does not establish either of these or application integration. |
| MongoDB Atlas | Created isolated project `shellhacks-relay-2026` and free M0 cluster `relay-missions` on GCP `us-central1`, with 512 MB shown. Runtime user `relay-demo` has one-day expiry and `readWrite` on `relay`, restricted to this cluster. With a temporary current-IP allowlist, the guarded CLI inserted a synthetic mission, updated `simulated_review`, and verified the exact digest through a fresh adapter. [Sanitized live proof](../artifacts/mongodb-live-proof.json). No teammate database was reused. | Link the connected incident's actual report and review to the store. The proven isolated snapshot has `human_review_performed: false`; no physical inspection or all-provider live chain is established. Reconcile the separate $0.10 proof reservation, which remains unknown. |
| Snowflake | Authenticated Snowsight on Standard GCP `us-east4` displayed **$400 remaining / 119 days** at the [browser setup proof](../artifacts/snowflake-browser-proof.json). The subsequent [live SQL API proof](../artifacts/snowflake-live-proof.json) retrieved both exact synthetic passages from `SHELLHACKS_RELAY.INSPECTION.RELAY_REFERENCES` with a statement handle on its first guarded dispatch. The [access proof](../artifacts/snowflake-access-proof.json) records the expressly approved one-day token, sole explicit reader role, four object grants, exact user-level operator IPv4 /32 policy without bypass, and Windows DPAPI storage with a verified decryption round trip. Warehouse `RELAY_REFERENCE_WH` was suspended afterward; X-Small Gen1, 60-second auto-suspend, auto-resume disabled and five-second statement/queue limits remain. | Live Gemini use of those passages remains pending (`model_use_verified: false`); no joined incident workflow is established. Inherited PUBLIC grants include AI/compute permissions, which the user expressly reviewed and approved, so this credential is not strictly read-only in effective scope. The [recorded access SQL](../deploy/sql/snowflake-runtime-access.sql) is not a rerun instruction. Displayed credits do not reconcile billing; the $1 setup hold and separate $0.10 proof reservation remain. |

Snowflake service user `RELAY_REFERENCE_CLIENT` has `RELAY_REFERENCE_READER` as its sole explicit role. Its token metadata showed `ACTIVE`, created `2026-09-27T00:34:29.052Z` and expiring `2026-09-28T00:34:29.052Z`, with no network-policy bypass. This records the approved credential's one-day lifetime; it does not authorize a replacement token or repeat query. The warehouse was successfully suspended after the proof.

The canonical ledger retains conservative resource reservations of $0.10 for Tiger Data, $0.10 for Atlas and $1.00 for Snowflake, plus $0.10 each for the completed Atlas and Snowflake API proofs with unknown billing. Tiger's schema setup and browser SQL proof were covered by its existing $0.10 resource hold; no new reservation was added and actual billing remains unknown. A displayed free-service quote does not settle these holds or establish a provider hard cap. Confirm the bounded lifetime and actual billing before releasing them; reserve each subsequent live application proof separately through the existing CLI.
