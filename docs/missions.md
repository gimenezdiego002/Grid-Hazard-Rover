# Offline mission planner

`relay_gateway.missions.MissionEngine` plans and rehearses missions without drivers, network requests, model calls or physical actuation. Its inventory declares **simulated roles**, not verified device capabilities or connections. Intellio scouts, the standalone station monitors, StackChan announces, and an available hexapod can provide an optional second observation. The default hexapod is unavailable. LeArm remains disconnected and never receives a mitigation task, even if an inventory declares it available or observation text asks it to act.

```python
from relay_gateway.missions import MissionEngine

engine = MissionEngine()
mission = engine.create_mission("water-001", "create-001", mode="preset",
                                station_id="station-a", target_id="inspection-area")
mission = engine.apply("water-001", "start-001", "start")
mission = engine.apply("water-001", "observe-001", "complete_task",
                       {"task_id": "monitor", "outcome": "suspected_hazard"})
```

`create_mission` also accepts `mode="directed"`, a selected `scout_id`, and `second_view=True`. Station and target are logical identifiers; selecting them does not navigate a robot. Assignment uses declared capability and simulated availability, then sorts by device ID for deterministic selection. An unavailable or incompatible selected scout produces `needs_review` with an explanation, without silently substituting another device. Missing required monitor/scout assignments block mission start; unavailable optional second views are skipped.

All mutation methods return a JSON-compatible snapshot with `planned_roles`, `proposed_tasks`, `progress`, `events`, `allowed_actions`, and `next_task`. `snapshot(mission_id)` and `inventory()` return independent copies. Actions are:

| Action | Payload | Effect |
|---|---|---|
| `start` | `{}` | Start a valid plan |
| `complete_task` | `task_id`, `outcome`, optional `summary` | Complete only the next simulated observation/announcement |
| `simulate_review` | `decision: "acknowledge"` or `"request_followup"` | Rehearse a review; never record actual human approval |
| `pause` / `resume` | `{}` | Preserve and restore running or review state |
| `cancel` | `{}` | Stop progression; preserve prior events and observations |

Task outcomes are `completed`, `suspected_hazard`, `needs_review`, or `budget_refused`. Observation completion does not mean safety. After observations, the engine stops at `needs_review`; only an explicit `simulate_review` can advance the demo review stage. Budget refusals, missing required devices, ambiguous outcomes and requested follow-ups stay blocked even after simulated acknowledgement. `human_review_performed` is always false and `environment_safety` is always `not_established`. A completed mission means the **simulated workflow** finished, not a real inspection or hazard clearance. Physical-action commands are always refused.

Mission and action IDs use 1–96 alphanumeric, period, underscore, colon or hyphen characters. Repeating an identical action ID and command returns its original accepted snapshot without appending an event; reusing it for different content raises `MissionConflict`. Invalid commands also preserve state. Unknown missions raise `KeyError`; validation raises `ValueError`; state/order conflicts raise `MissionConflict`; physical commands raise `PhysicalActionBlocked` (a conflict subclass).

The engine is thread-safe and process-local, with at most 32 missions and 64 accepted actions per mission by default. Capacity exhaustion refuses new work without deleting deduplication records. State disappears on restart and is not shared across cloud replicas. A durable event store and real operator authentication are separate future work; this simulator must never be used as an actuator authorization service.

The dashboard retains a pending mission request until its outcome is known. After a failed response it reads the mission back and checks for that request's exact action ID. A recorded action refreshes the display without repeating the task. If the outcome remains uncertain, **Retry pending request** reuses the identical request and action ID, including for mission creation; other mission controls stay paused. An explicit API rejection refreshes the current record when available. If the service has restarted, the last visible record stays on screen with its commands disabled, and a new simulation can be planned. Pending browser requests are memory-only: keep the page open while resolving an interruption.

The 32-mission limit includes completed and cancelled missions. Repeated rehearsals can reach it; reloading the page does not release server capacity. Save any wanted mission JSON before a deliberate local service restart to begin a fresh rehearsal session. Check the running executable/module before stopping it, and preserve any other work using that process. The simulator has no silent eviction or reset endpoint.
