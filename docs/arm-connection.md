# Arm connection after the simulated inspection

The user reports the Hiwonder 6-DOF LeArm moving through the Bluetooth app
named **LeArm**, with no USB cable available. The simulator exports a repeatable
**place-marker proposal** from rover or crawler inspection evidence. A real BLE
connection has answered an LSC voltage query. The recorder saves and previews
commanded waypoints. Explicit Bluetooth teaching/replay runners are prepared
and tested with fake transports; physical recording/playback remains unverified.

## Virtual arm fallback

The **Simulated arm** section on `/simulator` rehearses the response without a
Bluetooth connection. Start the preset to watch a virtual marker move from the
source to the destination, or set six illustrative joint angles, move to the
pose, capture it and replay the captured routine. Pause, single-step, stop and
reset support a paced demo. Joint-stall and grip-loss injection freeze playback;
clear the fault explicitly before resuming, or reset the virtual scene.

This model interpolates joint angles and draws illustrative links. Marker
attachment/release uses a synthetic proximity-and-gripper fixture, not measured
contact, forces or physical grip. A completed routine means the virtual sequence
finished. A dropped marker is not silently counted as a successful placement.
Clearing grip loss explicitly restores the pre-fault **virtual** payload state.

The separate `GET /api/simulator/arm` and `POST /api/simulator/arm/actions` routes
operate only on process-memory simulation state. Captured routines export as
`schema_version="arm-simulation/1"`, `recording_kind="simulated_joint_angles"`
and `angle_unit="degrees"`, with simulation provenance and actuation disabled.
They contain no physical pulse profile or operator-confirmed starting reference.
The physical recording parsers reject these exports; virtual poses are not
calibrated hardware programs. Tests in `tests/test_arm_simulator_boundary.py`
verify that boundary using captured-routine and completed-scene JSON.

## Inspection proposal

`relay_gateway.arm_handoff.build_arm_handoff` validates a simulated inspection
event, retains its evidence reference and produces an offline review preview.
Only `place_marker` addressed to `learm` is accepted. The proposal always has
`preview_only=true`, `actuation_enabled=false`, `physical_connected=false`,
`human_review_performed=false`, and no physical result. Its stable proposal ID
is a preview identity, not an execution token. Calling it costs no API/cloud
money and opens no port, network connection or hardware driver.

```python
from relay_gateway.arm_handoff import arm_connection_status, build_arm_handoff

status = arm_connection_status()
proposal = build_arm_handoff(
    event_id="inspection-demo-1", mission_id="demo-1",
    source_id="freenove-hexapod", station_id="station-a",
    evidence_ref="sim://demo-1/close-inspection", simulated=True,
)
```

Run this in the project's `.venv` or inspect the simulator's exported mission
JSON. `python -m pytest tests/test_arm_handoff.py` verifies proposal provenance
and rejection of physical confirmations/commands. Simulation review does not
establish that the physical arm zone is clear or a marker has been placed.

The existing `robotcode.arm.ArmController` is also simulation source. Its
`prepare_transfer` / `confirm_transfer` operations model a payload handshake;
they do not contain a LeArm driver. The fleet API accepts observations and
heartbeats, not motion commands. Keep these boundaries until the actual working
interface is identified.

## Handoff needed to record and repeat the working motion

Record the controller-board identifier and hardware generation, vendor app
version, Bluetooth advertised name, and the supported programming example that
matches that board. Original LeArm and LeArm AI documentation must not be mixed.
Include the exact working command/script if available, its environment and
dependencies, the matched power adapter label, and the observed stop procedure.

For a taught-motion demo, save an explicit sequence of approved waypoints or
vendor action groups with durations. Determine from the matching interface
whether joint positions can be read back; app-based movement alone does not
establish physical position recording. Replaying timed commands and recording
measured positions are distinct capabilities. Do not assume hand-guiding is
supported or drive an unpowered joint to produce a recording.

Once the interface is verified, attach one bounded recorded routine to the
reviewed proposal in a separate, deliberately enabled local runner. That runner
must use the known stop procedure, preserve uncertain/interrupted completion,
and record a physical result separately from the simulated inspection. The
operator must be present for the first connection, recording and playback.
The simulator and ordinary API remain offline regardless of environment keys.

Done when the simulation exports the reviewed evidence, the exact controller
interface is documented, and an operator observes one recorded routine replay
and stop through the verified local adapter. The inspection proposal and offline
motion recorder are implemented; live motion remains a separate verification.

## Bluetooth investigation, September 27, 2026

Hiwonder lists the [LeArm app](https://www.hiwonder.net/app-software) separately
from its other robot apps. The manufacturer's [iOS LeArm release history](https://apps.apple.com/us/app/learm/id1192117647)
includes action editing and identifies an early release as LSC-6. This suggests
the older controller family, but the app name alone does not identify the board.
Hiwonder's [LSC-6 product specification](https://www.hiwonder.com/products/lsc-6)
confirms Bluetooth 4.0, TTL serial communication and stored action groups.

The [official LSC serial protocol](https://wiki.hiwonder.com/projects/24-Channel-Servo-Controller/en/latest/docs/2_Communication_Protocol.html)
describes bounded servo moves and action-group playback. Its stop command stops
an action group; it is not a verified general stop for individual servo moves.
The [older manufacturer protocol V1.2, mirrored by a distributor](https://probots.co.in/technical_data/6%20DOF%20Robotic%20Arm_%20%20Servo%20Controller%20Communication%20Protocol%20V1.2.pdf)
also describes a position-read command. Support on this particular board and
whether it returns measured positions or controller targets remain unverified.
An actual six-servo position query received no reply. Neither measured positions
nor current controller targets can currently be captured automatically.
These serial documents do not specify BLE UUIDs. The device's interface was
therefore inspected directly, followed by the non-motion voltage query below.

The local read-only discovery command is:

```powershell
.\.venv\Scripts\python.exe -m robotcode.arm.ble_discover --seconds 8 --output .state/learm-bluetooth-scan.json
```

The optional `arm-bluetooth` dependency supplies Bleak. Discovery observes
advertisements only; it never connects or sends a command. A second scan found
the user-confirmed name **Hiwonder**. GATT inspection found service `fff0` and
characteristic `ffe1` at handle 24, plus a second `ffe1` under a different
service. Select the inspected service and handle, not UUID alone. Handles must
be checked again after reconnecting; they are not a universal LeArm constant.

`robotcode.arm.ble_diagnostics` sent only `55 55 02 0f` to the inspected
characteristic and received `55 55 04 0f c9 1e`: the controller reported **7881
mV**. This verifies that query over Bluetooth; it does not verify calibration,
position feedback, stop behavior or motion. Local evidence is in
`.state/learm-gatt.json` and `.state/learm-battery.json`. Device addresses stay
in ignored `.state/`, not source control. The simulator has no live connection.
The shareable [sanitized Bluetooth proof](../artifacts/learm-bluetooth-proof.json)
includes the successful voltage query and unanswered position query.

## Record and preview a finite commanded sequence

`robotcode.arm.motion` is a transport-free recorder/editor and LSC frame encoder.
It saves the six command targets and each movement duration, and generates a
replay trace. It does not listen to the phone app, read physical joint positions,
or move the arm. A review label in a profile records who supplied bounds; it is
not authentication or evidence that a physical check occurred.

Supply a profile JSON with exactly these fields (the placeholders are deliberate;
replace them with reviewed values before use):

```json
{
  "schema_version": "1",
  "profile_id": "my-learm-reviewed-bounds",
  "controller_family": "LSC",
  "units": "microseconds",
  "reviewed_by": "operator-id",
  "joint_bounds_us": [[null, null], [null, null], [null, null], [null, null], [null, null], [null, null]]
}
```

`joint_bounds_us` is ordered servo 1 through 6. Each pair must contain integer
minimum/maximum pulse targets reviewed for that joint. No hardware defaults or
taught positions are included. The [LSC software's documented 500–2500 envelope](https://docs.hiwonder.com/projects/24-Channel-Servo-Controller/en/latest/docs/1_User_Manual_formatted.html)
is enforced as an outer bound, not mechanical approval for an assembled LeArm.
The operator's profile must supply the narrower applicable range.

```powershell
.\.venv\Scripts\python.exe -m robotcode.arm.motion create --profile .state/learm-profile.json --name marker-demo --recording .state/marker-demo.json
.\.venv\Scripts\python.exe -m robotcode.arm.motion add --help
.\.venv\Scripts\python.exe -m robotcode.arm.motion preview --recording .state/marker-demo.json --repeats 2
```

Use `add --recording PATH --pulses P1 P2 P3 P4 P5 P6 --duration-ms DURATION`
with six reviewed integer values to save a waypoint. Use `edit` with the same
arguments and `--index N` to replace a zero-based waypoint. `preview` requires
at least one saved waypoint and emits the ordered frames and intended start
times. These are commanded timing targets, not measured motion durations.

The local application limits are 60 waypoints, 100–10,000 ms per waypoint,
1–5 repetitions and at most 120 seconds for the entire repeated preview.
Creation refuses to overwrite an existing file. Edits validate before atomically
replacing it. Duplicate JSON fields, unrecognized fields, oversized files,
out-of-bounds targets and physical-feedback claims are rejected.

`group-preview --group-id N --repeats N` encodes a previously taught LSC group
without sending it. It does not establish that the group exists or how long it
runs. Infinite repetitions are rejected. A six-servo move frame is 25 bytes;
a future BLE runner must verify the characteristic's write/fragmentation behavior
before sending whole frames. `CMD_ACTION_GROUP_STOP` cannot be presented as an
emergency stop for these individual waypoint commands.

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_arm_motion.py tests/test_arm_handoff.py -q
```

The offline tests cover protocol byte order, repeat timing, bounds, file updates,
CLI behavior and provenance. Physical success requires a separate operator-
observed replay through the verified adapter. Capturing a trajectory made in
the phone app remains a separate capability and is not currently implemented.

## Explicit Bluetooth teaching and replay

`python -m robotcode.arm.motion_live teach --help` describes the teaching
interface. It requires `--profile PATH`, a new `--recording PATH`, `--name NAME`
and `--start-pulses P1 P2 P3 P4 P5 P6`. Without `--live`, it validates and prints
a preview without importing Bluetooth, connecting, saving or moving.

Live use also requires `--live`, `--operator-present`, `--initial-pose-confirmed`,
`--address ADDRESS` and `--handle HANDLE`. The operator supplies an initial
**commanded reference**, checks the actual starting pose, power, clear workspace
and available physical/vendor stop. These flags do not establish measured
readback. No starting pose is sent automatically. Names such as `Servo1` through
`Servo6` do not supply numeric starting references, a controller-board identity
or reviewed joint bounds. Those remain missing from the user handoff. No neutral
position or usable live profile has been invented.

During live teaching, enter six integer targets followed by duration in ms;
`done` ends the session. Each joint stays within its profile and changes by at
most 100 microseconds from its last commanded reference. Duration is
1000–10000 ms. These application limits constrain pace; they do not certify a
collision-free movement.

The runner checks the inspected BLE service, characteristic and explicit handle,
then obtains a voltage reply on the same connection. Six 10-byte single-joint
frames are sent sequentially; the runner waits the duration after the last write.
This is staggered motion. A waypoint is saved only after all writes return and
the wait finishes. Timeout, cancellation or partial write ends the session with
an unknown result and no retry. Already issued direct moves may continue.
Ctrl+C prevents later writes; the group-stop packet is deliberately not used
for direct moves. Discovery, connection and disconnect have finite deadlines.

Saved `initial_pose` metadata has `source="operator_commanded_reference"` and
`measured=false`. `python -m robotcode.arm.motion_live replay --recording PATH
--repeats 1` previews the individual frames. The explicit live flags require the
operator to restore and confirm that saved starting reference. There is no
automatic return-home. The first step, all following steps and every repeated
loop transition are checked before any movement command is sent.

`robotcode.arm.ble_group` separately supports an already taught group. Default
mode is preview. Live mode requires `--group-contents-verified` along with
presence, address and handle; it does not assume a group exists. It permits
1–5 repetitions with a 1–120 second completion deadline, preflights voltage and
waits for matching controller completion. Timeout/cancellation attempts the
documented group-only stop and keeps the result unknown. The user has not
identified a saved group, so none has been selected or executed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_arm_motion_live.py tests/test_arm_ble_group.py tests/test_arm_motion.py tests/test_arm_handoff.py -q
```
