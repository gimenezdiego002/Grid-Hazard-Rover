# Spending and usage policy

The user authorized **at most $20 total in new API/cloud spending** for this setup. This is cumulative across providers, agents, projects, reruns, and processes; restarting the app does not reset it. Hardware purchases are outside this API/cloud ledger. The current durable admission ledger is `.state/spend.sqlite`; `docs/setup-spend.json` is its one-time historical import, and `docs/current-spend.json` is a reviewable snapshot. Read the durable ledger before billable work.

The ledger is excluded from Git. A fresh clone may run mock workflows, but default live admission must refuse a missing or uninitialized canonical ledger. The historical setup record omits later commitments and must not be used to bootstrap a new allowance. Keep all live callers on the existing operator checkout, or perform a deliberate migration of the full ledger while stopping its old callers. Two independent copies cannot safely share this authorization.

| Envelope | Limit | Use |
|---|---:|---|
| Planned operating spend | $15.00 | All automated callers and intentionally provisioned resources combined |
| Held contingency | $5.00 | Lead-managed recovery and delayed/unavoidable billing within the authorized total |
| Absolute total | $20.00 | Never increase this total without a new user instruction |

The reserve does not require another approval within the already authorized total, but automated callers must not release it themselves. Leave it unallocated until the lead checks the cumulative ledger and expected remaining charges. Mock work incurs no paid provider usage.

## Admission and reconciliation

For a billable model request, use an explicit model and price revision, bounded input, bounded output, and a conservative cost reservation. Atomically reserve the amount against the mission and the shared operating envelope before dispatch. Count retries and concurrent in-flight requests. Record provider-reported usage afterward and reconcile the reservation. Retain a conservative reservation for requests that time out with unknown billing status.

Mission caps also bound request count and token use. Pollard's token allocation can help a single run; it does not replace this aggregate policy. The backend's actual enforcement scope must be documented and checked before enabling live calls. A fresh session cap is not a cumulative multi-provider cap.

On denial, keep the evidence and report `needs_review` or a pending inspection. Budget exhaustion never implies that a suspected hazard is clear. Local sensor alarms and stopping stay available without an LLM call.

## Costs outside model tokens

Record Gemini, speech generation, database/warehouse compute, hosting, storage, and network charges in the same dollar ledger. Reserve a bounded planned resource lifetime before deployment and shut resources down when their purpose ends. Check the provider's real meter and applicable credits; do not equate an application counter or a billing alert with a guaranteed provider hard stop.

The ledger should retain: provider, operation/resource identifier, start time, mode, estimated maximum, settled amount, unresolved reservation, currency, and remaining allowance. Display simulated estimates, provider-metered usage, and actual billed/paid costs separately. Never represent sample pricing as a verified invoice.

## Default behavior

- Use mocks for unattended development, fixture replays, and tests.
- Route all live LLM requests through the gateway; do not embed credentials in device firmware or the browser.
- Prefer a small selected evidence packet and short structured output. Meter accepted work rather than free-form prompt size guesses alone.
- Only add model cascades, caching, or batching when measured against detection delay and missed incidents. Preserve freshness checks and flag stale evidence.
- Before enabling a new live provider, check the cumulative spend plus unresolved reservations plus its bounded expected cost against the operating envelope.

This policy specifies the intended controls. It does not claim that every provider adapter, shared ledger, resource shutdown, or provider-level cap has already been implemented.
