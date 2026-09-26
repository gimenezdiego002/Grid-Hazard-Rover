# Official Jev adapter

`src/relay_gateway/jev_provider.py` connects the simulated Relay supervisor to
TypeSafe's hosted Jev service. It does not connect to a robot. Gemini remains
responsible for mission interpretation, selected evidence and reports; deterministic
local code owns alarms, numeric thresholds, freshness, permitted actions and safe holding.

Verified September 26, 2026: the pinned model is `jev-1.13.0`, priced at **$0.042
per million input tokens**, with free output. Jev accepts text, not images. The
published context limit is 64k tokens per request, with 32k for state plus the
longest question. Version aliases may change. These are reviewed list prices,
not an account invoice or measured cost. [Official models](https://docs.typesafe.ai/models)

The adapter sends one `choice` question to `POST https://api.typesafe.ai/v1/systemone`.
It checks the returned version, chosen option, probability distribution, confidence
and integer usage. The official API reports input/output tokens, but no USD charge
in the documented response; `provider_reported_cost_usd` and `actual_billed_usd`
therefore remain null. Direct HTTP avoids SDK retries; HTTP failures never trigger
automatic retries. [Official API](https://docs.typesafe.ai/api)

Arithmetic, dates and invariants stay in application code because the provider
documents weaknesses in those tasks. A high confidence value is not a safety
authorization. [Documented limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13)

## Interface and safeguards

```python
decision = provider.decide(
    state=compact_json,
    choices=("hold", "request_evidence", "escalate_gemini", "continue_monitoring"),
    operation_id="jev:mission-001:observation-002:attempt-0",
    timeout_seconds=5.0,
)
```

Offer only the subset the local controller permits. `JevDecision` exposes `choice`,
`status`, `reason`, `confidence`, `model`, `operation_id`, `simulated`, `metrics` and
`as_dict()`. Only `status="completed"` carries a choice. The controller must still
validate the current observation and action before performing any simulated step.
The adapter itself never declares a hazard clear or dispatches an action.

- Input is limited to 8,192 UTF-8 bytes, four known choice labels, one question,
  and a requested timeout between zero (exclusive) and 30 seconds (inclusive).
- Before dispatch, the canonical cumulative ledger reserves the full reviewed
  65,536-token input allowance: **$0.002753 rounded upward**. This conservative
  application estimate includes more context than the small request; no guessed
  tokenizer ratio authorizes dispatch. Output is free at the pinned price.
- `JevTaskLedger` also applies the persistent **$0.50 combined Gemini/Jev task cap**.
  Its records share the original $15 planned/$20 total authorization. No new
  allowance is initialized. The actual ledger operation ID is included in metrics.
- A reservation claim dispatches once. Duplicate IDs are blocked even after a
  successful settlement. Intentional retries need a new explicit attempt ID and
  reservation. Timeouts, network errors, missing usage and unknown models retain
  the reservation. Reliable usage settles even if the answer is invalid or late.
- The transport limits response bytes and applies socket timeouts. DNS and repeated
  socket reads are not a strict total wall-clock bound. A response beyond the
  total decision deadline is rejected; an independent local watchdog must keep
  holding during all network work. This adapter is not a real-time control loop.
- Logs/results contain fixed error categories, hashes and metrics; no response
  bodies, authorization headers or provider exception text are returned.

`estimated_usd` derives from reported tokens and reviewed prices, not a provider
invoice. `reservation_held_usd` identifies unresolved exposure where known; it can
be null when admission failed or an existing operation was not re-read.

## Offline demonstration and verification

`FixtureJevProvider()` needs no keys, network or ledger. It chooses from compact
`health` and `local_alarm` fields; `choice_override` and `failure` inject invalid
answers, network/time failures or exhausted budget. Its token/cost values are
explicitly illustrative and paid cost is zero. It measures simulator behavior,
not real Jev quality. The low-level adapter tests inject `offline_transport` and
an isolated ledger to verify accounting without modifying the canonical ledger.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_jev_provider.py -q
```

Live construction requires both `JevProvider.from_environment(allow_live=True)`
and `RELAY_ALLOW_LIVE_JEV=1`, plus a backend-only `TYPESAFE_API_KEY`. It always uses
the canonical `JevTaskLedger`; explicit test ledgers are refused. Merely setting
credentials enables nothing. This module adds no HTTP route or default CLI hook.
Use the separate reviewed integration CLI for a metered smoke run; do not place
keys in examples, source, frontend configuration or command output.

All provider tests are offline. This adapter alone establishes no live account
access, hosted decision quality, Pi performance, physical inspection, measured
energy use or carbon saving.
