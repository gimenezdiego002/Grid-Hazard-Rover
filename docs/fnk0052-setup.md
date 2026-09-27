# Freenove FNK0052 setup and bring-up

## Status and scope

The primary robot is the **Freenove Big Hexapod Robot Kit for Raspberry Pi,
model FNK0052**. This repository has not touched the physical kit. Mock mode,
interfaces, safety behavior, Relay telemetry, and the Grid image/risk flow are
software-tested; servo movement, camera hardware, ultrasonic hardware, power,
and Raspberry Pi networking are not.

Official sources:

- [Freenove FNK0052 repository](https://github.com/Freenove/Freenove_Big_Hexapod_Robot_Kit_for_Raspberry_Pi)
- [FNK0052 online documentation](https://docs.freenove.com/projects/fnk0052/en/latest/)
- [Software installation](https://docs.freenove.com/projects/fnk0052/en/latest/fnk0052/codes/tutorial/1_Installation.html)
- [Assembly](https://docs.freenove.com/projects/fnk0052/en/latest/fnk0052/codes/tutorial/2_Assembly.html)
- [Module tests](https://docs.freenove.com/projects/fnk0052/en/latest/fnk0052/codes/tutorial/3_Module_Test.html)
- [Hexapod control](https://docs.freenove.com/projects/fnk0052/en/latest/fnk0052/codes/tutorial/4_Hexapod_Robot.html)

Use the downloaded documentation included with the current official repository
when it differs from the online pages. Review Freenove's license before copying
or redistributing vendor code. Grid Hazard Rover does not vendor their gait,
inverse-kinematics, or GPIO implementation.

## Hardware and operating system expectations

Freenove lists Raspberry Pi 5, 4B, 3B+, 3B, and 3A+ as recommended; several
other Pi models need extra parts. The Pi and batteries are not included. Their
current release notes say the `Code/Server` implementation supports Pi 1–5 and
uses the appropriate modern GPIO layer. Use Raspberry Pi OS with Desktop for
the vendor workflow, enable I2C/camera features exactly as their installer and
tutorial specify, and complete mechanical assembly and leg calibration first.

Freenove specifies four flat-top 3.7 V 18650 cells and a charger; consult
`About_Battery.pdf` from the official package before buying, charging, or
installing cells. Do not infer battery chemistry, polarity, protection, or
charger compatibility from this project. Power off the Pi before attaching the
camera cable. Connect ultrasonic VCC/Echo/Trig/GND only as shown in the official
assembly guide.

## Software installation on the Pi

Follow Freenove's installer/tutorial first. A typical official source checkout
is:

```bash
cd "$HOME"
git clone --depth 1 https://github.com/Freenove/Freenove_Big_Hexapod_Robot_Kit_for_Raspberry_Pi.git
```

Then clone Grid Hazard Rover separately, create its Python 3.11+ virtual
environment, and install the repository dependencies. Picamera2 and GPIO
packages are normally supplied by Raspberry Pi OS/vendor setup; do not replace
working system packages blindly.

```bash
cd "$HOME/Grid-Hazard-Rover"
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pip install -e ".[dev,integrations]"
```

Set the vendor path to the directory containing lowercase `control.py`,
`ultrasonic.py`, `camera.py`, and `point.txt`:

```bash
export ROBOT_MODE=freenove
export ROBOT_ID=freenove-fnk0052-01
export ROBOT_FREENOVE_SERVER_PATH="$HOME/Freenove_Big_Hexapod_Robot_Kit_for_Raspberry_Pi/Code/Server"
export ROBOT_ALLOW_PHYSICAL_ACTUATION=false
export ROBOT_NAVIGATION_ENABLED=false
```

Keep both safety switches false until the non-moving checks, Freenove module
tests, calibration, and supervised movement checklist pass.

## Architecture

```text
camera + ultrasonic
        |
RobotController (mock or Freenove FNK0052)
        |
deterministic local navigation -> RobotActuationGateway -> STOP on failure
        |
Relay telemetry gateway -> Relay consumer / missions
        |
trusted image + location + timestamp -> Grid /ingest/photo
        |
Gemini visual classification -> canonical Hazard
        |
Matias public records + utility projects -> matching -> deterministic risk
        |
dashboard
```

Freenove's `Control.run_gait()` owns gait and servo motion. The wrapper issues
bounded vendor-format move commands. Forward/backward use the vendor's Y-axis
pattern; turning uses the vendor command's angle field. Direction and gait must
still be confirmed with the robot safely lifted before floor testing. The
vendor interface has no verified sit primitive, so physical `sit()` fails safe
after stopping instead of guessing a body pose.

## Location

FNK0052 has no assumed GPS receiver. Image ingestion is blocked conceptually
until a trusted provider supplies `[longitude, latitude]`. Supported now:

- `ROBOT_LOCATION_MODE=none` — default; no location is fabricated.
- `ROBOT_LOCATION_MODE=fixed` with both `ROBOT_FIXED_LONGITUDE` and
  `ROBOT_FIXED_LATITUDE` — an operator/mission-provided location whose source
  is recorded.

`GPSLocationProvider` is an explicit future extension and currently raises an
unavailable error.

## Safe diagnostics and commands

```bash
.venv/bin/python -m rover diagnostics
.venv/bin/python -m rover status
.venv/bin/python -m rover demo
```

Diagnostics never initialize the physical controller or move a leg. In mock
mode they verify the simulated controller, distance reading, and JPEG. In
physical mode they verify only that the expected official files exist, then
mark controller/shield/servos/camera/ultrasonic as `not_tested`.

There is intentionally no unattended `test-motion` command. Physical
initialization requires `ROBOT_ALLOW_PHYSICAL_ACTUATION=true`, but setting it is
not proof that assembly or calibration is safe.

## First physical test checklist

1. Read the current official tutorial and `About_Battery.pdf` completely.
2. Confirm the package and board are FNK0052 and record the shield version.
3. Confirm the Raspberry Pi model and camera type/port.
4. Assemble and wire exactly per Freenove; inspect polarity and connectors.
5. Keep the robot supported so its legs cannot strike the table or a person.
6. Install Freenove's current server dependencies and run their non-motion I2C
   checks. Expected addresses must come from the current tutorial/board.
7. Run Freenove's individual module tests under supervision.
8. Perform Freenove's six-leg calibration using their calibration graph.
9. Keep `ROBOT_ALLOW_PHYSICAL_ACTUATION=false` and run Grid diagnostics.
10. Confirm diagnostics find the exact official `Code/Server` directory.
11. Establish an immediate power-cut/stop procedure with one operator assigned.

## First movement checklist

1. Disconnect autonomous navigation and external mission execution.
2. Lift/support the chassis with clear space around every leg.
3. Enable physical actuation only in the current supervised shell.
4. Initialize and stand using a single bounded command.
5. Confirm leg numbering, calibration, and expected pose.
6. Test STOP before directional motion.
7. Test one low-duration forward gait, then STOP.
8. Validate backward and left/right signs individually; update mappings only
   from observed results.
9. Test failure/interrupt behavior and Ctrl+C with a person ready to cut power.
10. Return both physical-actuation and navigation flags to false after testing.

## First camera checklist

1. Power off before attaching the camera cable.
2. Configure the correct camera generation and Pi port using Freenove's current
   installer/tutorial.
3. Verify Picamera2 with the vendor camera test.
4. Run a single still capture while motion is disabled.
5. Confirm the result is a complete JPEG under the backend size/pixel limits.
6. Confirm no frame or model output is being used as a GPS source.

## First ultrasonic checklist

1. Verify the exact VCC/Echo/Trig/GND wiring from the official guide.
2. Run the vendor module test with servos disabled.
3. Compare readings at several known, safe distances.
4. Confirm missing, invalid, stale, and exception paths all command STOP.
5. Only then enable the deterministic navigation policy in a clear test area.

## First Relay telemetry checklist

1. Keep the Relay gateway in mock mode for simulated envelopes only.
2. Confirm one heartbeat and one inspection envelope are accepted.
3. Resend the same envelope and confirm it is marked duplicate.
4. Confirm sequence gaps/restarts require the existing Relay review flow.
5. For real telemetry, configure Relay live mode and its bearer token outside
   Git; do not reuse a DigitalOcean account token.
6. Confirm Relay still reports `actuation_enabled: false`; mission planning is
   not permission to move hardware.

## First backend upload checklist

1. Configure a trusted fixed/operator location or a separately tested GPS.
2. Start the combined backend and verify `/health`, `/relay/health`, and
   `/relay/fleet/health`.
3. Use `simulate_upload.py --dry-run` first.
4. Submit one camera JPEG with trusted location, offset-aware timestamp, and
   robot ID.
5. Confirm Gemini classifies only visible evidence and cannot supply location,
   time, distance, timeline, or risk.
6. Confirm no-hazard produces no canonical entity.
7. Confirm a detected hazard appears in `/api/hazards`, then in matching/risk
   responses alongside the utility projects and Matias public records.

## Troubleshooting and safety

- Initialization failure, sensor error, stale readings, malformed/stale
  commands, camera exceptions, lost control, Ctrl+C, and shutdown must end in
  STOP. Never bypass the actuation gateway to debug a mission.
- If import fails, verify the configured directory contains the official
  lowercase current-release files and that Freenove dependencies were installed
  on Raspberry Pi OS.
- If camera setup differs by Pi version, rerun the current Freenove installer
  and use its documented camera port selection.
- If turn direction is reversed, stop and correct the semantic mapping only
  after a supported, supervised test—never compensate in AI prompts.
- Do not run servos from an improvised power source or infer electrical values
  from this repository.
