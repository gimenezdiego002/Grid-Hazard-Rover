# Grid Hazard Rover

Grid Hazard Rover combines planned utility work, public infrastructure records,
and rover observations to identify places where field coordination deserves
attention. The repository contains the Grid backend and dashboard, Matias's
public-data ingestion pipeline, and Monty's Relay mission/telemetry subsystem.

## System layout

```text
public records ──> backend.ingestion ───────────────┐
utility projects ────────────────────────────────────┤
JPEG + trusted GPS/time ──> Gemini classifier ──────┤
Relay reviewed finding + trusted field context ─────┤
                                                    v
                                      canonical shared schemas
                                                    |
                                      spatial/timeline matching
                                                    |
                                      explainable risk cells
                                                    |
                                      FastAPI + web dashboard
```

`shared/schemas.py` is the single source of truth for `Project`, `Record`,
`Hazard`, `Match`, and `RiskCell`. Stored and transmitted GeoJSON always uses
`[longitude, latitude]`. Browser map libraries may swap coordinate order only
at the rendering boundary.

Relay remains a deliberate subsystem under `src/relay_gateway`. Its mission,
telemetry, budgeting, and provisional-finding models serve different purposes
from the canonical Grid records and are not silently treated as equivalent.
Integration occurs through an explicit reviewed adapter with trusted location,
time, and severity inputs.

## Components

- `backend/`: FastAPI API, Gemini image classification, storage, spatial and
  timeline matching, explainable risk scoring, and public-record ingestion.
- `shared/`: canonical Pydantic data contract shared by every subsystem.
- `frontend/`: the operator-facing Grid dashboard.
- `src/relay_gateway/`: Relay mission planning, mock replay, telemetry gateway,
  integration proofs, spending controls, and its standalone dashboard.
- `docs/`: Relay operations, evaluation, hardware, cloud, and demo evidence.
- `rover/`: rover-side simulation and supervised hardware adapters.

## Grid backend setup

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python -m pip install -e ".[dev,integrations]"
Copy-Item .env.example .env
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs`. The backend starts without Gemini or MongoDB
credentials; only features requiring those services are unavailable. Keep real
credentials in the ignored `.env` file and never expose server keys through
`VITE_*` variables.

Core endpoints include:

- `GET /health`
- `GET /api/projects`, `/api/records`, `/api/hazards`
- `GET /api/matches`, `/api/risk-grid`, `/api/demo-summary`
- `POST /ingest/photo`
- `POST /api/integrations/relay/hazards`
- `/relay/*` for the namespaced Relay simulator and dashboard
- `/relay/fleet/*` for bounded Relay telemetry intake

`POST /ingest/photo` accepts a bounded JPEG plus trusted longitude, latitude,
timestamp, and optional source. Gemini supplies visual classification only; it
does not invent GPS, timestamps, identity, distance, or risk. A no-hazard result
does not create a fake canonical hazard.

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

The dashboard consumes the canonical API. Leaflet conversion from GeoJSON
`[longitude, latitude]` to display `[latitude, longitude]` belongs only in this
frontend boundary.

## Relay subsystem

Relay has a fully offline mock path and separately gated live proofs. Its mock
workflow does not require an API key, paid model call, cloud deployment, or
physical motion.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,integrations]"
.\.venv\Scripts\python.exe -m relay_gateway demo --scenario scenarios/leak.json
.\.venv\Scripts\python.exe -m relay_gateway compare --scenario scenarios/leak.json
.\.venv\Scripts\python.exe -m relay_gateway integrations
```

The primary Grid startup exposes Relay at `http://localhost:8000/relay/`. The
standalone Relay dashboard can also be launched with `scripts/start-demo.ps1`.
Its mission state is bounded and process-local. Inventory, sensor observations,
review events, model usage, and costs are clearly labeled when simulated.

Read these before claiming or operating integrations:

- [Integration status](docs/mlh-integrations.md)
- [Mission behavior](docs/missions.md)
- [Budget policy](docs/budget-policy.md)
- [Hardware bring-up](docs/hardware-bringup.md)
- [Five-minute demo](docs/demo-runbook.md)
- [Cloud deployment](deploy/README.md)

## Data and environment boundaries

The root `.env.example` documents Grid settings. `deploy/relay.env.example`
documents Relay settings. Neither contains credentials. Runtime state, raw
attachments, private operator handoffs, and canonical spending databases remain
outside Git.

Without a valid `MONGODB_URI`, Grid uses its process-local demo repository.
With MongoDB configured, canonical collections use unique IDs and GeoJSON
collections receive `2dsphere` indexes. Relay mission state and spending records
remain separate unless an explicit integration path says otherwise.

Google Geocoding uses the single server-side `GOOGLE_MAPS_API_KEY`; the same key
may authorize Routes when that feature is enabled. Existing coordinates bypass
geocoding. Routes cannot automatically avoid custom hazard polygons: route
alternatives must be scored against canonical hazards locally.

## Verification

```powershell
python -W error -m unittest discover -v
python -m shared.test_schemas
python -m compileall backend shared src
python -m pip check
```

Frontend tests run from `frontend/`. Relay also has focused tests under `tests/`.
Automated tests use mocks and fixtures; passing them is not proof of a connected
account, paid request, blockchain transaction, or physical robot inspection.

## FNK0052 mock demo

The Freenove FNK0052 software lane is mock-first and physically disabled by
default:

```powershell
.\.venv\Scripts\python.exe -m rover diagnostics
.\.venv\Scripts\python.exe -m rover demo
```

The finite demo connects simulated FNK0052 camera/ultrasonic behavior to Relay
telemetry and the existing Grid hazard, matching, and risk pipeline. See the
[FNK0052 setup and safety guide](docs/fnk0052-setup.md) before the robot arrives.

## Safety and truthfulness

- Never move physical hardware unattended. Motion requires a supervised,
  explicit enable step and an immediate stop path.
- Keep simulated and real observations clearly distinguished.
- Treat model findings as provisional until reviewed.
- Do not fabricate missing location, timestamp, severity, dates, or evidence.
- Keep cumulative paid-service use within the documented shared budget.
