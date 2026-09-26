# Gemini–Jev–Pollard Relay demo

This is a separate, **simulated** Relay supervisory workflow. It leaves the
team's `/shared` contract, photo ingest, spatial matching, risk index and Leaflet
dashboard unchanged. Gemini remains the mission/evidence/reporting model and
GCP remains the primary cloud. No robot is connected, actuated or calibrated.

## Verified checkpoint: September 26, 2026

- Full Python suite: **613 passed**, one existing Starlette/httpx deprecation warning.
  Dependency and Git whitespace checks passed; `/shared` and root `.env.example`
  still match team main. No frontend, deployment or shared entry-point changes.
- Pre-publication review fixed a hold-state regression: provider failures and
  decision/escalation budget refusals now remain `hold` / `needs_review` across
  unchanged dry frames. Sixteen additional cases cover these refusals and the
  healthy no-call optimization. The 36-run comparison was reproduced unchanged.
- Offline demo and all 36 comparison runs completed. No accepted unsafe action
  in the fixtures; two labeled hazard frames are missed by every strategy.
- No TypeSafe credential was available, so hosted Jev and the combined live path
  remain unverified.
- Four explicitly metered Gemini-only smoke/diagnostic runs made **five attempted
  role requests**, all without usable usage/results. The latest returned
  `ClientError`, HTTP 400, `INVALID_ARGUMENT`. A scoped REST thinking-field fix
  is covered by SDK request-body tests, but did not resolve the live rejection.
  The first run predates the added failure-stop safeguard and made two requests;
  later runs stop after the first failure and preserve local alarms.
- **$0.008659** remains reserved/unknown in the task scope, below its $0.50 cap.
  Actual billing is unknown. At this checkpoint the shared ledger has $0.000436
  settled estimates, $4.358659 unresolved reservations and $10.640905 remaining
  planned. Read the live ledger before later work; these figures are a snapshot.

Attempt evidence is in `artifacts/jev-gemini-attempt-v1.json`,
`artifacts/jev-gemini-diagnostic-v2.json`, `artifacts/jev-gemini-diagnostic-v3.json`
and `artifacts/jev-gemini-recovery-v4.json`. These record attempts, **not successful
live integration**. Do not redispatch their operation IDs or release their
reservations without reconciliation. The current adapter needs further
provider/account diagnosis before a successful live demonstration can be claimed.

## Run the offline demo

From the repository root, use the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,jev]"
.\.venv\Scripts\python.exe -m relay_gateway.jev_cli demo --strategy hybrid --scenario wet_episode --output artifacts/jev-demo.json
.\.venv\Scripts\python.exe -m relay_gateway.jev_cli compare --output artifacts/jev-comparison.json
.\.venv\Scripts\python.exe -m pytest -q
```

The `jev` extra pins the small `pollard-jev==0.1` package; it does not install
OpenJev, PyTorch or model weights. Normal Relay CLI/HTTP paths are unchanged and
remain mock-only. The new `demo` and `compare` commands also ignore credentials.

For a short judge demonstration, open the JSON's `summary` and then the
`wet_episode`, `conflicting`, `stale`, `invalid_choice`, `deadline_expiry`,
`network_failure` and `budget_exhaustion` runs. Show:

1. Gemini interprets a bounded water-inspection mission, without producing robot commands.
2. Local code validates units/freshness, computes the 700/1000 synthetic wetness
   threshold and latches the warning immediately.
3. Jev sees only compact structured metadata and locally permitted choices.
4. Difficult evidence may reach Gemini, with at most two escalations per mission.
5. Every choice is revalidated against freshness and deadline after inference.
   All actions are simulated receipts. Missing evidence, invalid choices,
   provider failures and budget refusal leave a safe hold and review requirement.
6. Gemini summarizes facts, while local code retains its alarm. A failed provider
   result stops further cloud work in that mission; report data remains reviewable.

The `rules` arm performs no model work. The `gemini` and `hybrid` arms share the
same observations, event trigger, local safety policy and escalation cap. Both
model arms include the same Gemini mission/report roles. Jev adds a selection
stage; it is not compared against an artificially polling Gemini baseline.

## What the evidence means

The 12 synthetic missions include dry and wet episodes, conflicting/missing/
stale/future/unsupported readings, a deliberate sensor blind spot, and injected
provider failures. Ground-truth labels enter evaluation only. The fixture hash
and summary metrics are reproducible; Pollard IDs and local execution timings
can vary. Fixture latencies use virtual supervision time and explicitly injected
deadline delays; they are not hosted-model benchmarks.

`artifacts/jev-comparison.json` is the complete dataset, configuration, per-frame
decisions, provider records and comparison. `artifacts/jev-results.md` is its
readable summary. `nominal_summary` excludes injected provider faults so their
failure behavior does not distort the ordinary resource-use comparison.
Token fields prefixed `known_` are partial sums when a simulated
network failure hides usage. Complete token/cost totals are null in that case.
Fixture costs are illustrative estimates, paid usage is zero, and no provider
reports a billed USD charge. Gemini fixture prices differ from current live
model prices deliberately and must not be presented as an actual bill.

All arms miss two labeled hazard frames: an unsupported sensor and a deliberately
below-threshold hazard. Review is **not** counted as a positive detection. The
fixture does not establish trained-model quality, Pi performance or reliable
leak identification. Reduced Gemini calls may come with more total calls/tokens.
Claim only potential reduction in unnecessary cloud work, never measured energy
or carbon savings. No deployed cloud revision includes this work unless a separate
deployment is verified.

## Explicit live smoke

Live inference is optional and uses synthetic observations only. The canonical
`.state/spend.sqlite` must already exist in the authorized operator checkout.
`JevTaskLedger` serializes task admission across processes and persists a combined
**$0.50** cap inside the existing **$15 planned / $20 total** allowance. New
processes, providers and operation IDs do not reset either cap. Unresolved
reservations remain held. The lock file must not be deleted while callers run.

Backend-only configuration is listed in `deploy/relay.env.example`. For Jev,
inject `TYPESAFE_API_KEY` securely and explicitly set `RELAY_ALLOW_LIVE_JEV=1`.
For Gemini, inject the dedicated ShellHacks project key, set
`RELAY_ALLOW_LIVE_GEMINI=1`, and provide an explicit reviewed model and input/output
prices. Do not paste keys into command history or source. Existing unrelated
environment keys are not proof of authorization to use their cloud project.

```powershell
# After securely configuring the appropriate provider(s):
.\.venv\Scripts\python.exe -m relay_gateway.jev_cli live-smoke --live --provider both --operation-id reviewed-run-001 --output artifacts/jev-live-proof.json
```

`--provider gemini` tests the Gemini mission/evidence/report path alone;
`--provider jev` tests one bounded hosted choice alone; `both` tests the combined
path. No command registers an account or buys a plan. An exclusive proof-file
claim prevents overwriting concurrent proof; pending/failure files and existing
operation IDs require reconciliation, not an automatic retry. An intentional
retry needs a new reviewed attempt ID and another admission reservation. Native
provider retries are disabled. Cloud invoices remain authoritative.

Jev is pinned to `jev-1.13.0`, at reviewed list pricing of $0.042/M input tokens,
with free output. It is hosted text inference and cannot consume photographs.
See the [provider adapter](jev-provider.md) and [package boundary](jev-pollard.md).
Gemini's existing `gemini-3.5-flash-lite` configuration was rechecked at
$0.30/M input and $2.50/M output (including thinking) on September 26, 2026;
verify pricing before future live use. [Google pricing](https://ai.google.dev/gemini-api/docs/pricing)

## Safety and implementation boundary

Local code owns thresholds, permitted actions, freshness, deadlines and alarm
latching. A model score, a `clear` finding, a repeat frame or an empty budget
cannot clear the alarm. A new observation is required for a new decision; no
background polling or self-generated evidence exists. A simulated mission has
at most 100 accepted frames, six supervisory decisions and two escalations.

This implementation is **not a physical controller**. Socket/DNS work does not
guarantee a hard real-time return, even though late answers are rejected. Any
future robot connection requires an independent continuously running local
watchdog and controller for gait, servo timing, numeric invariants and stopping.
Neither network access nor model confidence can be in that safety path.

The offline completion check is: the commands above run without credentials,
all safety/accounting tests pass, every arm receives identical frames, and all
simulated actions retain the local guard. Live completion additionally requires
successful metered Gemini and Jev responses on those inputs; hardware completion
requires a separately authorized controller/robot bring-up.

Source ownership: `jev_provider.py` (hosted/fixture Jev), `jev_pollard.py`
(package contract admission), `jev_gemini.py` (bounded roles and Pollard meters),
`jev_budget.py` (persistent task cap), `jev_supervisor.py` (local simulation
policy), `jev_comparison.py` (recorded synthetic experiment), and `jev_cli.py`
(explicit standalone commands). Tests use isolated ledgers, never a fresh live
allowance. No shared entry point or deployment configuration is wired to live inference.
