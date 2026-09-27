# Implementation sequence

Relay's core demonstration is: **a fixed station notices water; a rover investigates; a hexapod gathers another view; an operator reviews the evidence; an arm places a marker; StackChan announces the result.** This is the intended physical demo, not a claim that the hardware is connected.

Keep missions small: inspect a named station, capture an observation, stop, run a taught arm action, announce a reviewed finding. Begin with two or three known locations and supervised vendor movement routines. General indoor navigation is outside the first milestone.

## Milestones and acceptance

| Order | Work | Acceptance evidence |
|---|---|---|
| 1 | Local replay and budgeted model gateway | Reproduce the labeled fixture; demonstrate a denied request when a mission budget is exhausted; zero paid calls in mock mode |
| 2 | One real sensor and a read-only rover camera connection | Save a timestamped real reading and image with `simulated: false`; document the connection procedure |
| 3 | Supervised rover mission | A present operator dispatches a bounded action and demonstrates stop; coordinator records request and acknowledgement |
| 4 | One real Gemini call within the aggregate budget | Save structured output, model identifier, provider usage, and cost reconciliation; preserve the original evidence |
| 5 | Second robot and failure handling | Supervisor requests a second view or marks the first robot unavailable; software offers a valid reassignment |
| 6 | All sponsor integrations | Each row in the integration matrix has a recorded live proof and an explicit fallback |
| 7 | Arm/StackChan response and judge rehearsal | Operator approves a known arm action; one announcement plays; sponsor-specific explanations follow the same incident |

The lead handles orchestration and credentials. Student teammates supply small, reproducible hardware handoffs from the README table. After every milestone, save a known-working command and its observed output before adding another dependency.

## Implemented rehearsal

Preset and directed missions now have a bounded offline state engine, HTTP controls and a dashboard planner. It assigns simulated station/scout/announcement roles, skips unavailable optional equipment, supports pause/resume/cancel, and stops for explicit simulated review. A budget refusal remains unresolved after acknowledgement. LeArm actuation is excluded, and no simulated task establishes environmental safety. Mission snapshots currently live only in process memory; this is not durable production scheduling.

The fleet consumer separately saves synthetic gateway envelopes and cursors in local SQLite. It does not dispatch mission actions or run inference automatically. A guarded reviewed-speech CLI is ready for an explicitly configured account. These pieces extend the software rehearsal; they do not complete the supervised hardware milestones above. See [missions](missions.md), [fleet intake](fleet-consumer.md), and [speech execution](speech-cli.md).

## Intended architecture

```text
Sensor station / rover / hexapod
        | readings, selected images, acknowledgements
        v
Local coordinator and device adapters
        | candidate evidence packets
        v
Budgeted Gemini gateway -> provisional structured finding -> operator review
        |                             |
        | usage ledger                +-> bounded response / report / announcement
        v
Mission report and evaluation
```

GCP is the primary deployment target for the app and evidence storage. DigitalOcean has the distinct proposed job of hosting the persistent gateway or simulator. Network outages must leave local stopping available. Cloud model output never becomes raw motor/servo instructions.

The gateway owns model credentials and validation. The event path should not depend on all three databases being available at once: Atlas is intended for operational documents, Tiger Data for telemetry, and Snowflake for historical/reference retrieval. Publish completed events to optional sinks rather than giving every sink control over a robot.

## Model economy

Implement sensor gating first: a rising wetness threshold, a reset threshold, and deduplication. Add bounded image packets when actual camera access exists. An LLM does not need every dry sample. Start with one selected Gemini model; introduce a cheap/expensive cascade only when a recorded evaluation shows that the extra call improves the cost/quality tradeoff.

Pollard may provide in-run token allocation, while Relay must own the aggregate dollars, persistence, concurrency reservations, and non-LLM spending. Verify the selected Pollard version and adapter behavior in the backend; do not treat a library's token budget as a provider billing limit.

## Leave-behind status

While the lead is away, software work can continue with mocks, fixture replays, docs, and device-interface code. Do not enable real actuation, flash a connected device, or start a physical calibration unattended. Record anything needing a present person in the hardware checklist. No completed checkbox should be inferred from a vendor's feature list.
