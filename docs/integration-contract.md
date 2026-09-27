# Shared integration and spending contract

All adapters remain mock by default. The orchestrator owns live opt-in and the shared spending gate; finding a credential never enables network writes. Each integration should make a bounded, meaningful contribution to a mission and return reviewable evidence. Physical robot actuation is outside this setup.

## Durable spending gate

`relay_gateway.integrations.ledger.SpendLedger` uses one canonical SQLite file, `.state/spend.sqlite`, under the source workspace containing the installed module, independently of the launch directory. The default constructor requires that this file **already exists as an initialized cumulative ledger**. It checks the reviewed workspace files, then opens SQLite read-only to validate table structure, schema/currency/authorization metadata and the completed historical-import marker. A missing, empty, unrelated, unimported or inconsistent database is refused without creating, importing or repairing it. Reopening a valid default ledger performs no initialization writes.

The ledger admits up to **$15 in settled estimates plus active reservations**, holding $5 within the user's $20 total. A fresh mission, process or provider shares the same allowance. Fresh clones and packaged installations remain mock-only until the lead restores or shares the authorized canonical ledger with all current settled usage and unresolved reservations. The old `docs/setup-spend.json` snapshot omits later operations and must never bootstrap a new clone's live allowance. A read-only copy or exported snapshot is evidence, not a separate admission authority. Do not operate independently writable ledger copies in parallel: all live callers must coordinate against the same durable transactional state. A second ledger never grants a second allowance. Cloud replicas require a shared transactional store before live multi-instance admission.

Explicit-path construction remains available for isolated tests and deliberate, reviewed initial setup/migration. That path can initialize tables and import a reviewed history atomically once, including historical estimates and unresolved reservations. Its availability is not permission to bypass the canonical state. The original setup imported the **$0.000179 Gemini usage estimate**; all later reservations and settlements belong in the cumulative SQLite ledger. Import is recorded once and cannot reset spending. Later edits to the old JSON are not reimported. `history_path=None` is for isolated tests, not live recovery. Invalid or inconsistent historical totals block import. Do not delete the canonical file or put it on ephemeral storage; restore the authoritative current state through a reviewed recovery procedure before resuming live work.

```python
from relay_gateway.integrations.ledger import SpendLedger

ledger = SpendLedger()
ticket = ledger.reserve("speech:mission-001:report-v1", "ElevenLabs", "0.02")
if ticket.created:
    # Perform local validation BEFORE this transition. This can succeed only once.
    ledger.mark_dispatched(ticket)
    try:
        result = call_provider_once()
    except Exception:
        ledger.mark_unknown(ticket.operation_id, reason="unclassified")
        raise
    else:
        if result_has_reliable_usage(result):
            ledger.settle(ticket.operation_id, estimate_usd_from_usage(result))
        else:
            ledger.mark_unknown(ticket.operation_id, reason="missing_usage")
else:
    # Reconcile or display this existing operation; do not call the provider again.
    display_existing_operation(ticket.operation_id)
```

The functions representing a provider call, pricing, and display above are application code, not ledger methods. Every intentional retry needs a new explicit operation ID and a new reservation. IDs should include mission/report revision and attempt, but no credentials or personal data. Use provider idempotency keys where supported; the local gate cannot ensure exactly-once external execution after a network failure.

`reserve(operation_id, provider, maximum_usd)` is idempotent for identical parameters. Only its first successful caller receives a dispatch claim. `mark_dispatched(ticket)` atomically consumes that claim before any outbound attempt. Duplicate callers, reused claims, changed providers and changed reservation amounts are refused. `cancel_before_dispatch(ticket)` releases only an owned, never-dispatched reservation. After dispatch, explicitly verified zero-cost failure can settle at zero; a timeout cannot.

`settle(operation_id, actual_estimated_usd)` reconciles usage, releasing unused reservation. Repeating the same amount is idempotent; conflicting rewrites are refused. An overrun already incurred is recorded even if it exceeds the reservation or allowance, and later reservations are denied. `mark_unknown(operation_id, reason=...)` retains the full reservation. Allowed reasons are `unclassified`, `timeout`, `connection_lost`, `missing_usage`, `provider_pending`, and `process_restart`. Reserved, dispatched and unknown operations never expire automatically.

Money inputs are decimal strings, `Decimal`, or integers. Binary floats, negative amounts and non-finite values are rejected. Storage uses integer micro-dollars; sub-micro-dollar estimates round upward. SQLite `BEGIN IMMEDIATE` serializes mutations and has a bounded lock timeout; `LedgerBusy` authorizes no external work. Do not hold the database transaction open during provider work.

`snapshot()` returns `settled_estimated_usd`, `reserved_usd` (all unresolved states), `unknown_reserved_usd` (the unknown subset), `committed_estimated_usd`, `remaining_planned_usd`, overrun amounts, and operation records. Actual invoices remain `actual_billed_usd: null` until independently established. The ledger does not automatically discover cloud resources, shut them down, meter external SDK retries, or cap provider bills. Hosting reservations must include a bounded resource lifetime, storage and network expectations. Pollard separately accounts for model tokens/requests; the outer shared ledger must wrap live model calls too.

Native Gemini calls reserve text-input estimates plus the configured maximum output before SDK dispatch. The current text-only input estimate includes UTF-8 prompt, system instruction and response-schema bytes plus framing; it is conservative, not a proven tokenizer bound. Provider usage settlement includes reported thinking tokens and charges cached prompt tokens at the full input rate conservatively. Missing or inconsistent usage retains the reservation. No images, tools or streaming are enabled. If these inputs, model configuration or prices change, review the reservation calculation before enabling them; an application estimate is not a provider invoice limit.

## Mission event

Keep the existing `Observation` schema in `src/relay_gateway/models.py` for the simulator. Future connected adapters should normalize events to this conventional envelope, with unit conversion explicit:

```json
{
  "schema_version": "1",
  "event_id": "station-a:water:00042",
  "mission_id": "inspection-001",
  "station_id": "station-a",
  "robot_id": "station-a",
  "observed_at": "2026-09-26T18:00:00Z",
  "kind": "water",
  "value_milli": 850,
  "unit": "wetness",
  "evidence_uri": null,
  "simulated": true
}
```

`timestamp_seconds` is the simulator's relative time; `observed_at` is an adapter contract for real UTC timestamps, not an already accepted simulator field. Ground-truth labels belong only to evaluation fixtures and never enter inference prompts. Evidence URIs do not prove that media was decoded. Readings alone cannot establish a leak source or gas identity.

## Integration result

The orchestrator can normalize adapter-specific return values into:

```json
{
  "schema_version": "1",
  "operation_id": "provider:mission-001:report-v1:attempt-0",
  "provider": "provider-name",
  "mode": "mock",
  "status": "completed",
  "simulated": true,
  "evidence": {},
  "usage": {},
  "estimated_usd": "0.000000",
  "actual_billed_usd": null,
  "limitations": []
}
```

Status is `completed`, `blocked`, `unknown`, or `failed`. Do not report completed solely because an asynchronous provider accepted a job. Missing cost information is `null`, never zero. Mock cost estimates must be identified as illustrative; actual paid usage for mocks is zero. A budget denial yields blocked/needs-review evidence and keeps local alarms available.

Useful evidence by integration:

| Integration | Evidence |
|---|---|
| Gemini | Model ID, prompt/result digests, bounded config, normalized usage, Pollard node ID |
| ElevenLabs | Voice/model IDs, character count, generated audio path and digest; distinguish placeholder audio |
| Tiger Data | Inserted/read-back event IDs, row counts and query window |
| MongoDB Atlas | Mission/report document ID, recorded state, read-back confirmation |
| Snowflake | Statement/query ID, completion state and cited retrieved rows; pending handles remain unknown |
| Solana | `devnet` cluster, transaction signature, report SHA-256, verification result |
| DigitalOcean/GCP | Resource IDs, region, verified endpoint, bounded lifetime, reservation and shutdown state |
| GoDaddy Registry | Eligible registered domain and verified DNS/HTTPS target; a suggested name is not registration |

Keep raw credentials, connection strings, authorization headers and provider exception bodies out of reports. Solana proves integrity of a committed report digest, not truth of its observations. Fewer requests and tokens are resource-use measurements/proxies; do not convert them into measured carbon savings without a defensible energy and emissions measurement.
