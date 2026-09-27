# Robot application source and vendor software

The three requested robot folders are here:

| Folder | Owned robot | Included software |
| --- | --- | --- |
| [`arm/`](arm/README.md) | Hiwonder 6-DOF LeArm; board revision pending | Station payload controller and official programming references |
| [`hexapod/`](hexapod/README.md) | Freenove **FNK0052**, confirmed September 27, 2026 | Carrier controller and pinned, unmodified vendor Raspberry Pi server source |
| [`quarky_intellio_rover/`](quarky_intellio_rover/README.md) | Quarky Intellio Rover Kit | Patrol/inspection controller and PictoBlox firmware upload instructions |

**The project controllers currently run with simulated IO only.** They are
executable application source, not flash-ready firmware images. No hardware
connection, robot motion, docking, payload transfer, camera capture or detection
has been demonstrated by this code. FNK0052 uses a Raspberry Pi application;
Intellio's stock firmware is supplied by PictoBlox. A matching, redistributable
LeArm firmware image has not been verified. See each folder for the exact boundary.

The new [spatial simulator](../docs/simulator-demo.md) adds visible rover/crawler
navigation in the Relay dashboard. Separate tools in `arm/ble_discover.py`,
`arm/ble_inspect.py` and `arm/ble_diagnostics.py` have now demonstrated a
non-motion Bluetooth connection and controller voltage reply. The
[sanitized proof](../artifacts/learm-bluetooth-proof.json) records exactly what
worked; the position query received no reply. The original application
controllers and default `python -m robotcode` workflow remain simulated.

The [arm recorder and explicit Bluetooth runners](../docs/arm-connection.md)
provide commanded-waypoint teaching/replay. Preview is the default. Physical
playback has not been demonstrated and requires reviewed bounds, an
operator-provided starting reference and attended operation. They are separate
from the simulator API; no simulator review dispatches physical motion.

## Run the basic workflow

From the repository root, using the existing project `.venv`:

```powershell
.\.venv\Scripts\python.exe -m robotcode --workflow basic
.\.venv\Scripts\python.exe -m pytest robotcode/tests -q
```

On Linux/Pi, the equivalent Python path is `.venv/bin/python`. The offline application
controllers and default workflow use only Python's standard library; tests reuse the repository's
pytest installation. The default CLI is finite and offline. It never imports
the vendor server, opens serial/GPIO/network connections, starts a background
loop, reads credentials, or calls a cloud/model provider. There is no live flag.

The JSON trace rehearses this sequence:

1. The rover starts a waypoint patrol and receives explicit synthetic scans.
2. A suspected hazard stops its motion and creates a report for the coordinator.
3. The hexapod is dispatched to the intermediate arm station.
4. Arrival and docking are separately acknowledged. Both devices reserve the
   same transfer ID and payload. The arm loads an inspection kit; payload
   security and arm clearance are explicitly confirmed before departure.
5. The hexapod visits the reported location and records inspection evidence.
6. It returns to the station, where the arm unloads the kit. Inventory returns
   to the station only after the corresponding confirmations.

Every arrival, scan and confirmation in this demo comes from a **synthetic
fixture**, not a sensor. Waypoint names are symbolic: no localization,
path planning, obstacle detour or gait controller is implemented. A hazard flag
is supplied to the rover; it is not a verified camera/Gemini classification.

Other runnable workflows keep the basic sequence extensible:

```powershell
.\.venv\Scripts\python.exe -m robotcode --workflow directed
.\.venv\Scripts\python.exe -m robotcode --workflow inspection-only
.\.venv\Scripts\python.exe -m robotcode --workflow report-only
```

`directed` retasks the rover from patrol before the carrier's pickup/inspection/
drop-off sequence. `inspection-only` dispatches the hexapod without a payload
station visit. `report-only` holds the rover's report without dispatching it.
Robot actions are separate from the demo sequence, so subsequent plans can
compose station visits, inspections, loading and unloading in a different order.

## Command and failure behavior

Each controller exposes `command(command_id, action, **parameters)` and
`snapshot()`. A repeated command ID with identical parameters returns its
original receipt without repeating work; changed parameters are rejected.
**Stop is the exception:** a repeated valid stop still stops the current state.
Receipts are bounded to 256 new commands per controller/session; capacity
exhaustion stops the simulation and refuses additional work.

The arm permits one transfer at a time and the carrier cannot leave during a
transfer or without explicit arm clearance. Interrupted station operations
retain custody uncertainty and require reconciliation before reset. The demo
coordinator stops all three robots and latches review if a command fails. These
are local, in-process interlocks; they are not a distributed transaction or proof
that two real devices agree about payload ownership.

`tick(elapsed_s=...)` advances deterministic test deadlines. There is no
wall-clock or independent hardware watchdog. Sensor corruption and simulated
IO errors stop the rover. A real adapter needs sensor freshness, authenticated
commands, mission/session identity, durable receipts, localization and independent
watchdog/stop behavior before physical use. Restarting this simulation loses
state and must never be used to infer real payload custody.

## Firmware and hardware handoff

The FNK0052 vendor source is stored with its own attribution and license under
`hexapod/vendor/fnk0052`; nothing in the demo imports or runs it. The independent
project controllers have not been connected to that server. Use the matching
vendor guide and preserve its license when copying those files onto the Pi.

For Intellio, use its documented **PictoBlox → Quarky Intellio → USB Serial →
Upload Firmware** path. Do not upload these CPython modules as an ESP32 binary.
For LeArm, match the actual controller board to its vendor programming guide
before selecting firmware or taught servo actions. Adapter/power details,
supervised calibration, payload geometry/mass and real move/stop demonstrations
remain in the [hardware bring-up checklist](../docs/hardware-bringup.md).

This folder is separate from the team-owned `/rover`, `/backend`, `/frontend`
and canonical `/shared` contract. It does not replace Project, Record, Hazard,
Match or RiskCell, change the existing Relay mission/API models, or connect to
photo ingest, risk maps or the fleet gateway. API/cloud expenditure for the
offline workflow is zero.

Done for this software increment means: all four synthetic workflows complete,
inventory is conserved, interruption/retry tests pass, and these sources are
pushed to the current repository branch. Physical firmware installation and
the real multi-robot workflow remain separate, unverified bring-up work.
