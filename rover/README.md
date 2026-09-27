# FNK0052 rover software

This package prepares the **Freenove Big Hexapod Robot Kit for Raspberry Pi,
model FNK0052** as the primary future inspection robot. Physical hardware has
not been available or tested. Safe mock mode is the default and every mock
record says `simulated: true`.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m rover diagnostics
.\.venv\Scripts\python.exe -m rover status
.\.venv\Scripts\python.exe -m rover demo
```

The demo is finite and offline. It simulates local collision avoidance, camera
capture, Relay telemetry/deduplication, Grid photo ingestion with a mocked
Gemini result, canonical hazard creation, matching, risk generation, and a
final stop. It makes no paid call and never claims real hardware activity.

`simulate_upload.py` remains available for sending an operator-selected JPEG
through the exact deployed multipart API contract:

```powershell
.\.venv\Scripts\python.exe rover\simulate_upload.py `
  --image C:\Users\gimen\Downloads\pothole.jpg `
  --longitude -80.36 `
  --latitude 25.76 `
  --dry-run
```

Remove `--dry-run` only when the backend is running and a Gemini-backed request
is intentional. Downloaded photographs are demo evidence, not observations made
by a physical rover. Do not commit photographs or tokens.

The controller boundary exposes semantic operations; application code never
manipulates 18 servos. `MockHexapodController` works now.
`FreenoveFNK0052Controller` dynamically loads Freenove's official `Code/Server`
modules on the Pi and delegates gait control to `Control.run_gait()`. It refuses
initialization unless `ROBOT_ALLOW_PHYSICAL_ACTUATION=true`, and physical mode
must follow the supervised checklist in [the FNK0052 setup guide](../docs/fnk0052-setup.md).
