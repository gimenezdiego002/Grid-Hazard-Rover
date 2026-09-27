# Quarky Intellio rover

`controller.py` implements **simulation-only** patrol and directed inspection
logic. It is ordinary Python application source, not a Quarky/ESP32 firmware
binary or a PictoBlox upload-mode program. It imports no hardware library.

## Local application behavior

```python
from robotcode.quarky_intellio_rover import RoverController

rover = RoverController()
rover.command("patrol-1", "patrol", waypoints=["corridor-a", "suspect-area"])
rover.command("scan-1", "scan", obstacle_cm=100,
              hazard_detected=False, evidence_ref="fixture-clear-1")
rover.command("arrival-1", "arrive", target="corridor-a")
rover.command("scan-2", "scan", obstacle_cm=80,
              hazard_detected=True, evidence_ref="fixture-suspect-1")
print(rover.snapshot())
```

Run this from the repository root with the project `.venv`. Inputs and outputs
are synthetic. No image is captured and the supplied hazard flag is not a
classification result. `evidence_ref` is an opaque identifier.

| Action | Behavior |
| --- | --- |
| `patrol(waypoints)` | Starts a bounded route of 1–32 symbolic locations |
| `scan(obstacle_cm, hazard_detected, evidence_ref)` | Moves toward the current target only with a clear sample; an obstacle stops and blocks; detection stops and reports |
| `arrive(target)` | Requires the commanded target and a prior clear scan; advances patrol or enters `at_target` |
| `investigate(target)` | Stops and replaces an idle/patrol/reported/blocked task with a directed inspection |
| `complete_inspection(evidence_ref)` | Requires acknowledged arrival and emits an observation report |
| `acknowledge_report(report_id)` | Holds detection until explicitly acknowledged; returns to idle |
| `tick(elapsed_s)` | Advances the synthetic mission deadline, default 30 seconds |
| `stop`, `reset` | Stop and explicit recovery; reset does not restart a patrol |

Clearance defaults to **25 cm as a simulation parameter**, not a measured safe
distance for the actual rover. A blocked rover does not invent an obstacle
detour; it waits for reassignment. Patrol is finite, with each scan supplied by
the caller. Invalid samples, deadline expiry and adapter exceptions stop the
simulated motion. See the [common runtime limitations](../README.md).

## Install stock Intellio firmware with the vendor tool

The official [Intellio connection guide](https://ai.thestempedia.com/docs/quarky-intellio/quarky-intellio-connection-guide/)
uses desktop **PictoBlox 9.1.0 or newer**, board selection **Quarky Intellio**,
USB Serial, and **Upload Firmware**. Code/control and camera communication use
the guide's 2.4 GHz Wi-Fi connection. The
[firmware troubleshooting guide](https://ai.thestempedia.com/docs/quarky-intellio/quarky-intellio-firmware-troubleshooting/)
describes checking the installed firmware version and updating it through
PictoBlox. A public standalone firmware binary and redistribution terms were
not verified, so no `.bin` is included here.

The [Intellio Rover Kit](https://thestempedia.com/shop/quarky-intellio-rover-kit/)
uses the **Quarky Mini Expansion Board** for motor control. Relevant vendor
references are the [motor extension](https://ai.thestempedia.com/extension/quarky-mini-expansion-board/),
[Intellio sensors](https://ai.thestempedia.com/extension/sensors-quarky-intellio/),
and [camera extension](https://ai.thestempedia.com/extension/camera-quarky-intellio/).
These do not establish that the original Quarky motor API works on Intellio.
Some published Python signatures are inconsistent; capture the generated code
from the installed PictoBlox extension and verify its move/stop example before
writing a live adapter. The camera page does not prove a laptop-accessible JPEG
or mission-controller camera endpoint.

Before uploading or powering motors, confirm the installed board/firmware,
expansion wiring, sensor pins, battery and stop procedure with a present
operator. See [hardware bring-up](../../docs/hardware-bringup.md). No upload,
Wi-Fi provisioning or physical test was performed in this change.
