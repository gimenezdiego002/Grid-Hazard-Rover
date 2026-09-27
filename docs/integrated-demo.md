# Integrated offline mission

`relay_gateway.integrations.workflow.run_integration_demo(scenario=None)` now exercises the complete application workflow with deterministic mocks. It has **no live argument**. API keys, live-enable environment variables, and a configured remote store cannot activate provider calls through this function.

The six stages are:

1. **Snowflake:** retrieve synthetic reference passages for the observation type. Their IDs and bodies enter the model gateway's bounded, untrusted reference context.
2. **Gemini gateway:** use `MockProvider` to produce findings and cite supplied reference IDs. The stage does not call Gemini. Pollard records the rehearsal in a temporary SQLite database that is removed afterward.
3. **Tiger Data:** normalize readings to a fixed UTC fixture timeline, insert them into the mock transport, replay the same events, and query the complete observation window. Replay inserts must be zero.
4. **MongoDB Atlas:** upsert the mission and its simulated reviewed report, then compare the retrieved record with the stored snapshot.
5. **ElevenLabs:** prepare a bounded briefing descriptor. No speech/audio file is generated. The fixture review is explicitly marked `human_review_performed: false`.
6. **Solana:** create a mock receipt, verify the original report's hash, and demonstrate that changing the report revision invalidates the comparison. No wallet, devnet transaction, or chain verification is claimed.

All step objects include `mode: "mock"`, `simulated: true`, `remote_verified: false`, status and compact evidence. A step marked `completed` completed only its offline rehearsal. Hosting on GCP/DigitalOcean and GoDaddy domain registration are listed separately as not exercised. All eight MLH technologies plus GCP appear in the returned service inventory; no remote service is verified by this demo.

## Input and output

Input is an optional dictionary accepted by the existing `Scenario` model. Omitting it uses `default_scenario()`. An empty or invalid dictionary raises a validation error rather than silently substituting the default. The function deep-copies supplied input and marks the replay and every observation simulated, leaving the caller's dictionary unchanged.

Relative `timestamp_seconds` values are added to the fixed fixture epoch `2026-09-26T18:00:00Z`. This preserves event identity and deterministic report hashes across replays; it does not assert a real measurement time. Evaluation ground-truth labels do not appear in the operational report or reference prompt. Robot identifiers are preserved, so a supplied two-robot scenario retains both identifiers without claiming physical coordination or actuation.

Useful returned fields for the dashboard:

| Field | Contents |
|---|---|
| `steps` | Six ordered provider/action/status/evidence objects. |
| `services` | All eight MLH providers plus GCP, with explicit remote-verification status. |
| `report`, `findings`, `mission_outcome` | The finalized simulated report and its findings. Budget denial and unsupported sensors remain `needs_review`. |
| `accounting` | Pollard's illustrative mock token/cost estimates and zero actual paid usage. |
| `references`, `reference_context` | Retrieved fixture records and the validated model-context representation. |
| `telemetry`, `telemetry_persistence` | Timestamped rows, insert/replay/read-back counts, and verification result. |
| `mission_persistence` | Mission ID, snapshot digest and read-back verification. |
| `briefing` | Text, mock voice/model IDs and a descriptor with `audio_path: null`. |
| `receipt`, `receipt_verification`, `tamper_verification` | Mock receipt, successful original comparison, and rejected modified copy. |

Top-level `network_requests` is zero, `actual_paid_usd` is `"0.000000"`, and `production_spend_ledger_modified` is false. The function does not instantiate `SpendLedger`, alter existing cloud-cost history, create account resources or persist wallets/audio. It creates only a temporary offline Pollard recording. A completed workflow can contain `mission_outcome: "needs_review"`; completing the rehearsal does not turn an unresolved finding into a clear result.

## Run the proof

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_integration_workflow.py -q
```

To view a compact run without saving files or calling providers:

```powershell
@'
import json
from relay_gateway.integrations.workflow import run_integration_demo

result = run_integration_demo()
print(json.dumps({
    'status': result['status'],
    'mode': result['mode'],
    'mission_outcome': result['mission_outcome'],
    'steps': result['steps'],
    'telemetry_persistence': result['telemetry_persistence'],
    'mission_persistence': result['mission_persistence'],
    'original_report_valid': result['receipt_verification']['valid'],
    'modified_report_valid': result['tamper_verification']['valid'],
    'network_requests': result['network_requests'],
    'actual_paid_usd': result['actual_paid_usd'],
}, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

Tests cover all stages, actual reference-ID propagation, deterministic reports/receipts, two-robot input preservation, budget-denial handling, unsupported sensors, invalid timestamps, and secret suppression. They block sockets and spending-ledger initialization. A test supplies credentials and live-enable flags, points the store environment at MongoDB, and confirms an existing spending-ledger sentinel stays byte-for-byte unchanged.

Live demonstrations remain separate, explicit operations through the [shared spending contract](integration-contract.md). This offline workflow does not remove the account/credential/schema prerequisites in [data integration setup](data-integrations.md), generate speech, connect a blockchain, or establish cloud/domain deployment evidence.
