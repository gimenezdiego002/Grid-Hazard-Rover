# Arm station controller

`ArmController` is runnable **simulation source**, not a LeArm firmware image.
It uses Python's standard library and records symbolic requests through
`SimulatedIO`. It does not connect to a controller board or move a servo.
The user identified the arm as **Hiwonder 6-DOF LeArm**. Its controller board,
hardware generation and adapter remain unconfirmed; this is not confirmation
that it is the newer LeArm AI.

## Payload handoff

- `prepare_transfer`: requires an idle arm, a docked hexapod, clear arm zone,
  and the arm's configured `station_id` (constructor default: `station-a`).
  `direction="load"` reserves a station payload for the hexapod;
  `direction="unload"` reserves an incoming payload for the station.
- While `transferring`, `station_locked` stays true. An outgoing payload stays
  in inventory until confirmation. A second transfer is rejected.
- `confirm_transfer`: requires the matching transfer ID, receiving-side
  `payload_secured=True` and `arm_clear=True`. Only then does inventory change
  after both the confirmation-received and simulated peer-release IO events
  succeed. A successful command receipt with `last_transfer.outcome="confirmed"`
  acknowledges that local handoff. An IO error at either stage keeps the
  pending reservation and old inventory, stops the arm and requires explicit
  reconciliation, even if a partial event was recorded.
- `check_interlock`: losing docking or zone clearance stops the transfer.
  `tick(elapsed_s=...)` advances the deterministic simulation watchdog; at
  `timeout_s` (default 30), the arm stops. The caller must supply ticks; this is
  not a physical or background watchdog.
- `stop` during a transfer latches `needs_reconciliation`. `reset` cannot
  discard that uncertainty. `reconcile_transfer` requires the matching ID,
  explicit payload location, arm clearance and peer release. A separate
  `reset` is then required.

Commands use `command(command_id, action, **parameters)` with the common
runtime's idempotency rules. Transfer IDs are unique for the controller's
lifetime. Boolean confirmations must be actual booleans, not truthy strings.
All state is in memory; restarting this simulation loses it. Before any live
adapter exists, persistent recovery, real sensor feedback, live watchdogs,
payload retention and the board-specific emergency-stop behavior need hardware
verification with the operator present. A simulation stop is only a log event.

```python
from robotcode.arm import ArmController

arm = ArmController(station_id="station-1", inventory=["inspection-kit"])
arm.command(
    "load-prepare", "prepare_transfer",
    station_id="station-1", peer_id="hexapod-1", transfer_id="transfer-1",
    payload_id="inspection-kit", direction="load",
    peer_docked=True, zone_clear=True,
)
arm.command(
    "load-confirm", "confirm_transfer", transfer_id="transfer-1",
    payload_secured=True, arm_clear=True,
)
```

## Vendor programming path to verify

Hiwonder's current [Robot Debugging Software page](https://www.hiwonder.net/robot-debugging-software)
offers a LeArm graphical servo/action-group editor and downloads. That page
links the newer LeArm AI product, so compatibility with the owned 6-DOF LeArm
still needs confirmation from the board label and its matching vendor guide.
An action-group editor download is not proof of a replacement firmware image.

For **LeArm AI specifically**, Hiwonder documents Arduino example projects
and a compile/upload workflow in its
[Basic Development Course](https://docs.hiwonder.com/projects/LeArm_AI/en/latest/docs/5.Basic_Development_Course.html).
Its [Serial Communication Operation Course](https://docs.hiwonder.com/projects/LeArm_AI/en/latest/docs/9.Serial_Communication_Operation_Course.html)
describes a UART host interface and the matching LeArm PC/App protocol.
These are references for a future adapter after identifying the actual board;
they do not establish compatibility with another LeArm generation. No vendor
firmware has been copied, modified, flashed or verified by this module. A
redistribution license for a matching original LeArm firmware package has not
been verified, so vendor binaries and libraries are not vendored here.
See [hardware bring-up requirements](../../docs/hardware-bringup.md).

From the repository root, run the arm checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest robotcode.tests.test_arm -v
```
