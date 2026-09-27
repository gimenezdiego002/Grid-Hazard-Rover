# Freenove FNK0052 hexapod controller

This folder contains project-owned, Python 3.11+ **simulation controller source**
and an **unmodified Freenove hardware-source snapshot** in `vendor/fnk0052/`.
The project controller never imports that snapshot, opens a device connection or
moves a servo. Its I/O and acknowledgements are marked simulated by the shared
runtime. The vendor source can actuate real hardware and has not been run here.
Neither part is a flashable microcontroller image.

## Basic use

Run from the repository root with the project-local Python environment:

```python
from robotcode.hexapod import HexapodController

hexapod = HexapodController()
hexapod.command("dispatch-1", "dispatch", target="inspection-site-1")
hexapod.command("arrival-1", "arrive", target="inspection-site-1")
hexapod.command("inspection-1", "inspect", evidence_ref="simulated:inspection-1")
print(hexapod.snapshot())
```

Dispatch only enters `travelling`; it does not claim that the hexapod arrived.
`arrive` must name the dispatched target. `inspect` accepts an evidence reference
and completes the local inspection step, returning to `idle`. The caller supplies
that reference; this controller does not capture images, classify hazards or
upload records to the team backend.

## Optional station visit and payload transfer

Navigate to a station using `dispatch(target=station_id)` and acknowledge arrival.
Then use this sequence:

| Action | Required parameters | Result |
| --- | --- | --- |
| `dock` | `station_id` matching the acknowledged location | `docked` |
| `prepare_transfer` | `station_id`, unique `transfer_id`, `payload_id`; optional `direction` defaults to `load` | `transferring` |
| `confirm_transfer` | matching `transfer_id`, `payload_secured=True`, `arm_clear=True` | `docked`, custody updated |
| `undock` | `arm_clear=True` | `at_target` |
| `dispatch` | next `target` | `travelling` |

`load` means arm/station to hexapod and requires an empty carrier. `unload` means
hexapod to arm/station and requires that exact payload aboard. `payload_secured`
acknowledges security at the destination, including the arm/station when unloading.
The mission coordinator must obtain matching acknowledgements from both devices;
this controller does not infer the arm's state. Carrier geometry, payload mass,
physical docking and retention hardware still need verification.

An inspection can precede or follow a station visit. A station visit may load,
unload or skip payload transfer. Mission routing belongs to the coordinator.

## Stop, timeout and recovery

`stop(reason=...)` stops the simulated I/O. A stop while docked or transferring
latches `transfer_reconciliation_required`; `reset` cannot clear that latch.
While stopped, call `reconcile_transfer(payload_id=<observed ID or None>,
arm_clear=True, evidence_ref=<inspection reference>)`. The payload value is an
explicit observed custody input, not an assumption that the transfer succeeded.
Then `reset` clears navigation/docking acknowledgements and returns to `idle`,
retaining the reconciled payload. Repeated transfer IDs are rejected even after
reset; repeating the original command ID uses the runtime's idempotent receipt.

`tick(elapsed_s=<positive finite number, at most 3600>)` advances the simulation clock. Unacknowledged
navigation times out after 120 seconds and transfer after 30 seconds, entering
`stopped`. A transfer timeout requires reconciliation. These are test deadlines,
not a physical watchdog; there is no background loop and wall-clock time does not
advance the controller automatically. A live adapter must implement independent
hardware stop/watchdog behavior. Docked waits do not trigger the transfer timeout.

## Hardware programming path: FNK0052

The user confirmed **FNK0052** on September 27, 2026. The PCB revision, Raspberry
Pi model and camera still need confirmation. Follow the supervised bring-up
requirements in [`docs/hardware-bringup.md`](../../docs/hardware-bringup.md).

Freenove's official FNK0052 resources describe Python server code on the Pi and
a client communicating over TCP/IP. This is a Raspberry Pi device application
deployment path, not a microcontroller firmware image to flash. Their
[software setup guide](https://docs.freenove.com/projects/fnk0052/en/latest/fnk0052/codes/tutorial/1_Installation.html)
links the [vendor source repository](https://github.com/Freenove/Freenove_Big_Hexapod_Robot_Kit_for_Raspberry_Pi).
The [robot programming guide](https://docs.freenove.com/projects/fnk0052/en/latest/fnk0052/codes/tutorial/4_Hexapod_Robot.html)
describes custom Python programs using that kit's server code. Follow the
instructions bundled with the selected vendor revision: server-folder guidance
has changed across releases, as the [official release notes](https://github.com/Freenove/Freenove_Big_Hexapod_Robot_Kit_for_Raspberry_Pi/releases)
explain.

## Included vendor snapshot

[`vendor/fnk0052/`](vendor/fnk0052/) contains all 23 files from upstream
`Code/Server/`, plus Freenove's original `LICENSE.txt` and `README.md`: 25 upstream
files totaling 131,729 bytes. The source is from Freenove's official repository,
pinned to commit `b7d228cc870b0a802d3768bfcf742f85fa8695f6` and retrieved on
September 27, 2026. No upstream file was modified, imported or executed.

[`SOURCE.json`](vendor/fnk0052/SOURCE.json) records the repository, commit,
retrieval date, file sizes, Git blob SHA-1 values and SHA-256 digests. Each
download's length and Git blob hash matched GitHub's recursive tree for that
commit before it was saved. This verifies source identity, not safe operation.
The manifest itself is locally generated metadata.

The copied Freenove files retain their [original CC BY-NC-SA 3.0 license](vendor/fnk0052/LICENSE.txt)
and [upstream attribution](vendor/fnk0052/README.md). That vendor license applies
to the vendored Freenove materials; the independently written project simulation
controller is separate and does not incorporate their source.

This is the server-source subset, not a complete Raspberry Pi installation.
Vendor setup tooling, GUI client, tutorials and binary applications were not
copied. For the matching full resources, use the
[archive for the same pinned commit](https://github.com/Freenove/Freenove_Big_Hexapod_Robot_Kit_for_Raspberry_Pi/archive/b7d228cc870b0a802d3768bfcf742f85fa8695f6.zip)
outside this repository and follow its tutorial with a present operator.

Static inspection identified these concrete bring-up concerns:

- `Code/Server/myCode.py` starts walking examples at module import, and
  constructing `Control()` initializes hardware and writes servo positions.
  Do not import vendor modules during simulation, test discovery or laptop checks.
- `Code/Server/server.py` accepts plaintext TCP control on port 5002 and streams
  camera data on port 8002 without an authentication handshake. Keep any later
  supervised vendor demonstration on a trusted isolated network; do not expose
  that server publicly.
- A keyword scan found no embedded password, token or API-key assignments in
  the copied server source. This was a limited static inspection, not a complete
  security or hardware-safety audit.

With a present operator, match the Pi model, camera, board revision and power
requirements to the vendor guide before installing dependencies, starting the
server or calibrating. Record supervised stop, short movement and image-capture
demonstrations before implementing a live adapter for the mission controller.
No live adapter or device upload has been performed.
