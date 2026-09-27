# Rover, crawler and arm simulator demo

Hosted demo: **https://shellhacks-relay-robotics.vercel.app**. It runs the same
simulation engines inside each visitor's browser, with independent scenes and
no connected hardware. Reloading resets that tab's state and virtual recordings.

Run `scripts/start-demo.ps1`, then open **http://127.0.0.1:8765/simulator**.
The existing mission lab remains at `/`. Both pages run offline with mock
inference and zero paid provider calls. No keys are required.

If an older server already occupies that port, run
`scripts/start-demo.ps1 -Port 8766` and open **http://127.0.0.1:8766/simulator#arm-simulator** for the updated
arm fallback. The current local verification session uses port 8766.

## Main demonstration

1. Start the preset inspection. Use 4× or 8× playback for a short presentation.
   The rover follows its patrol, routes around equipment and approaches the
   synthetic wet area. Read the distance, proximity and battery displays as
   simulation telemetry.
2. Follow the crawler to the station, through the synthetic kit pickup, and to
   its close-inspection position. The arm station transfer is an animation and
   fixture acknowledgment, not a connected arm command.
3. The mission waits for review. Inspect its arm proposal, acknowledge the
   simulated evidence, and watch the rover return home and crawler return its
   kit. This does not establish that any physical hazard is safe or resolved.
4. Show the economy comparison: the baseline would analyze every observation;
   the governed policy filters routine evidence and deduplicates findings per
   robot. Tokens and prices use the assumptions printed in the returned
   metrics. All actual model calls and API cost are zero.
5. Reset and select a free map location for a directed inspection. Test an
   obstacle, sensor dropout or low battery. Clear the synthetic fault, then
   explicitly resume. A budget-exhaustion test leaves the next novel finding
   awaiting review; acknowledging review cannot replenish its allowance.

The map uses local meters, four-neighbor A* navigation, obstacle clearance and
different illustrative speeds for each robot. It is a **2D kinematic model**,
not validated terrain, gait, traction, camera, energy or multirobot collision
physics. Sensor readings and findings are generated from the fixture geometry.
There is no real Gemini vision classification in this simulator.

## Saved rehearsal

```powershell
.\.venv\Scripts\python.exe scripts/rehearse-simulator.py
```

This runs a separate in-memory simulator and saves JSON under a new
`artifacts/simulator-rehearsal/run-*` directory. It verifies the preset,
pause/resume, review/return, directed inspection, fault recovery and budget
refusal. It does not alter the running browser scene, use cloud APIs or connect
hardware. The script exits nonzero on a failed check.

## State and controls

`GET /api/simulator` returns the scene. `POST /api/simulator/actions` accepts
`run_id`, a distinct `action_id`, an action and its relevant parameters. Exact
retries do not repeat movement. Reset creates a new run ID; stale commands
conflict. State, events and receipts are bounded and process-local. Restarting
the server clears them. Export a record before resetting if it is needed.

Time advances only through explicit step requests. Browser playback sends
bounded steps locally; the server has no background robot or inference loop.
The default scene is shared within one server process, so use one controlling
browser for the presentation.

The [arm connection notes](arm-connection.md) track the separate Bluetooth
work. Motion recording and playback require their own verified device
interface and taught sequence. A simulated dock or review cannot substitute
for a physical confirmation.

## Arm fallback when hardware is unavailable

Open the arm simulator section on the same page. It has its own clock and
controls, so it can run before or after the rover/crawler mission. Play the
virtual marker pick-and-place preset, pause or step through its poses, then
replay it for the demonstration. This requires no arm, Bluetooth or cloud API.

The six joint controls set illustrative angles for the virtual model. Record
the virtual poses you want and replay the taught routine. These are simulation
records, not physical joint readings, calibrated pulse targets or inputs for
the live LeArm runner. The schematic model does not validate reach, collisions,
grasp strength, mechanical travel or real-world safety.

Inject a joint stall or lost grip to demonstrate a failed action. The arm freezes.
Clearing the fault restores the pre-fault virtual payload checkpoint and leaves
playback paused until explicitly resumed; resetting starts a fresh virtual
scene. This restoration is a rehearsal shortcut, not a physical recovery method.
No failure in this panel commands or reconnects
the physical arm. If hardware fails during a live demonstration, stop the real
session using its verified physical procedure and start this independent
simulated rehearsal; the simulator does not inherit an uncertain physical pose.

Arm state is served at `GET /api/simulator/arm`; bounded, idempotent actions use
`POST /api/simulator/arm/actions`. Like the fleet scene, it is process-local,
advances only on explicit steps and is shared across browsers on that server.

Run `.\.venv\Scripts\python.exe scripts/rehearse-arm-simulator.py` for a separate,
finite proof of the preset, two-pose recording/replay, lost-grip freeze and
explicit checkpoint restoration. It saves synthetic results under a new
`artifacts/arm-simulator-rehearsal/run-*` directory without changing the browser
scene or opening a hardware transport.

Use the [economy pitch](economy-demo-story.md) to explain why fewer unnecessary
model requests and repeatable robotics workflows matter. Keep current counts
separate from the older sensor-fixture comparison in the mission lab.

Done when both simulated robots complete the inspection and return after
review, the virtual arm completes its preset and taught replay, faults stop
progress until explicit recovery, budget refusal remains visible, and all model
costs/telemetry are honestly labeled. All hardware commands and paid model calls
remain zero. Physical movement is not a requirement for this fallback demo.
