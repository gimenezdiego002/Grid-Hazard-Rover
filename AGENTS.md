# Grid Hazard Rover - Agent Context

## Mission

Grid Hazard Rover is a ShellHacks 2026 project built during an approximately
36-hour hackathon. It identifies where future utility projects, public
construction activity, and rover-observed physical hazards collide in space
and time, then explains which areas deserve attention first.

The primary product is utility-to-utility construction coordination. Public
records and rover hazards enrich that signal; they never replace it.

Favor working, testable, demo-ready behavior over elegant but unfinished
architecture. Avoid unnecessary abstractions, speculative services, and
sponsor-feature creep.

## Demo story

The core demonstration should prove this sequence:

1. At least two utilities have future construction projects.
2. Their geometries cross or come near one another.
3. The system computes their actual closest-point distance and distance tier.
4. Their schedules overlap or fall within the coordination window, or the
   system honestly reports that timeline status is unknown.
5. FDOT and Miami-Dade activity enrich the surrounding context.
6. A rover photograph becomes structured hazard data through Gemini.
7. A deterministic Coordination Risk Index increases from those factors.
8. The dashboard shows the corridor and explains why it is high risk.

Routing, voice, alerts, deployment, and a custom domain come after the core
coordination demonstration is stable.

## Sacred features

Do not break these while adding integrations:

1. Gemini hazard classification
2. Spatial overlap matching
3. Coordination Risk Index and geographic risk layer
4. Interactive Leaflet map

If a change threatens one of these features, stop and raise the concern
before implementing it.

## Repository ownership and structure

- `/shared` - canonical Pydantic schemas and shared fixtures. Once
  `schemas.py` exists, it is the contract.
- `/backend` - FastAPI, configuration, MongoDB access, ingestion integration,
  spatial/timeline matching, risk calculation, routes, briefings, and alerts.
- `/frontend` - React, Vite, TypeScript, Leaflet dashboard.
- `/rover` - Raspberry Pi capture and upload code owned by the robotics
  teammate.

Do not overwrite or duplicate teammate work.

### Robotics teammate

Owns the Raspberry Pi, Pi camera, `picamera2`, `gpiozero`, motors, L298N,
JPEG capture, coordinate/timestamp attachment, and posting photos to
`POST /ingest/photo`. Backend development must support mock uploads so it does
not depend on physical hardware. Do not implement motor control unless asked.

### Data pipeline teammate

Owns Miami-Dade and FDOT ArcGIS ingestion, utility-source ingestion, utility
PDF extraction, geocoding, and normalization into the shared contract.

Preferred ingestion path:

- Miami-Dade ArcGIS API -> structured JSON/GeoJSON -> normalize -> MongoDB
- FDOT ArcGIS API -> structured JSON/GeoJSON -> normalize -> MongoDB
- Utility PDF or messy planning document -> Gemini -> normalize -> MongoDB
- Unstructured HTML site -> crawler only when no structured source is usable

Do not send already-clean ArcGIS data through an LLM unnecessarily.

## Shared schema contract

`/shared/schemas.py` is the single source of truth for at least:

- `Project`
- `Record`
- `Hazard`
- `Match`
- `RiskCell`

Before touching a model shape, read that file. Do not redefine these models
inside backend modules. Before changing a field, inspect consumers and update
them intentionally so teammate integrations do not break.

If `shared/schemas.py` does not exist yet, do not invent an implicit contract
inside another subsystem. Create it only when explicitly requested.

## Non-negotiable geospatial rules

- Backend, database, and API GeoJSON coordinates are always
  `[longitude, latitude]`, for example `[-80.36, 25.76]`.
- Leaflet expects `[latitude, longitude]`. Convert only at frontend render
  time; never store or transmit Leaflet-order coordinates as GeoJSON.
- Never treat Shapely distance in EPSG:4326 degrees as meters.
- Transform WGS84 geometry with `pyproj` into an appropriate metric projected
  CRS before real-world distance calculations.
- Use closest-point distance between geometries, not centroid distance.
- Intersecting or touching geometries have distance `0` and tier `crossing`.
- Distance tiers are:
  - `crossing`: 0 m
  - `under_1_6km`: greater than 0 m and less than 1,600 m
  - `under_8km`: at least 1,600 m and less than 8,000 m
  - `under_40km`: at least 8,000 m and less than 40,000 m
  - 40,000 m or more: ignore for coordination matching

Utility-to-utility comparison is the fundamental Sperry/GridLock signal.
Utility-to-record and utility-to-hazard matches are enrichment and must not be
presented as satisfying that requirement.

## Timeline rules

- Use an approximately 180-day coordination window between relevant date
  ranges.
- Support partial or missing dates safely.
- Never fabricate dates to simplify matching.
- Preserve and expose uncertainty when timeline overlap cannot be determined.

## Coordination Risk Index

Risk scoring must be deterministic, explainable, and reproducible. Never ask
Gemini to invent a risk score.

Candidate inputs include utility distance, timeline relationship, rover
hazard severity and confidence, nearby FDOT activity, and nearby Miami-Dade
activity. Every result must expose its final score, level, component scores,
and human-readable reasons.

Illustrative, not final, weights are distance 40, timeline 25, rover hazard
20, and public infrastructure 15. Illustrative levels are 0-29 LOW, 30-59
MODERATE, 60-79 HIGH, and 80-100 CRITICAL. Do not treat these examples as a
finalized contract unless the shared schema or a later decision adopts them.

The geographic risk layer should derive explainable `RiskCell` features from
projects, matches, records, and hazards.

## Service and integration rules

### Gemini

- Use Gemini where it adds value: multimodal hazard classification and
  extraction from messy planning documents.
- Use `GEMINI_API_KEY` and `GEMINI_MODEL`; never scatter a hardcoded model
  name through the code.
- `gemini-3.8-flash` is currently a configured candidate, not a verified model
  identifier. Verify current availability before depending on it.
- For structured output, set JSON response MIME type and a response schema.
- Still strip possible Markdown code fences defensively before JSON parsing.
- Do not add Google Cloud Vision; it is not needed for the intended pipeline.

### MongoDB Atlas

Expected collections include projects, records, hazards, matches, and risk
cells. Every collection with a GeoJSON `location` field must have a
`2dsphere` index.

### Google Routes

Google Routes does not accept arbitrary hazard polygons as avoid regions.
Request alternatives with `computeAlternativeRoutes: true`, decode candidate
polylines, score each against our risk geometry, and select the lowest-
exposure option. Do not claim Google directly avoids our custom hazards.

Leaflet and OpenStreetMap remain the primary dashboard map; include required
OpenStreetMap attribution. Do not add Google Maps JavaScript, Vision, Roads,
or Street View APIs without a concrete need.

### ElevenLabs

Generate voice briefings only on user action from already-computed facts.
Do not regenerate audio on every dashboard render or depend on permanent
local MP3 storage; DigitalOcean App Platform filesystems are ephemeral.

### DigitalOcean, Discord, and GoDaddy

- Deploy the backend to DigitalOcean App Platform only after it works locally.
- Production FastAPI must listen on `0.0.0.0`, use the platform-provided port,
  and expose a simple `GET /health` endpoint.
- Discord webhook alerts are optional and come after the core dashboard.
- A GoDaddy custom domain is optional and must not delay core functionality.

## Security and data handling

- Never hardcode secrets or commit `.env` files.
- Keep secret values in backend environment variables loaded through the
  chosen configuration layer.
- `.env.example` contains names and safe defaults only.
- Never expose backend credentials through `VITE_*` variables. The frontend
  may use `VITE_API_BASE_URL` for the public API origin.
- If a new credential is required, add only its empty name to `.env.example`
  and tell the project owner.
- Never ingest or store CEII (Critical Energy Infrastructure Information).
  Public project descriptions are not necessarily CEII, but detailed power-
  flow or similarly sensitive grid data may be. Ask when uncertain.

## Technology stack

- Backend: Python 3.11, FastAPI, Uvicorn, Pydantic 2, pymongo, Shapely,
  pyproj, google-genai, requests and/or httpx, python-dotenv, and polyline when
  needed.
- Frontend: React, Vite, TypeScript, Leaflet, react-leaflet, OpenStreetMap,
  and Tailwind only if useful or already configured.
- Rover: Python, picamera2, gpiozero.
- Data: MongoDB Atlas with geospatial indexes.
- Deployment: DigitalOcean App Platform for the backend and Vercel for the
  frontend.
- Voice: ElevenLabs. Alerts: Discord webhook. Domain: GoDaddy if time permits.

## Expected API direction

These are architectural targets, not permission to create them prematurely:

- `GET /health`
- `GET /api/projects`
- `GET /api/records`
- `GET /api/hazards`
- `GET /api/matches`
- `GET /api/grid`
- `POST /ingest/photo`
- Later: `POST /api/route`, `POST /api/briefing`, and
  `POST /api/alerts/test`

## Development order

Work in explicit, user-authorized steps. The intended order is:

1. Repository and environment sanity
2. Shared schema contract
3. FastAPI skeleton and configuration
4. MongoDB abstraction and indexes
5. Controlled mock integration dataset
6. Spatial engine
7. Timeline engine
8. Match engine
9. Coordination Risk Index
10. Geographic risk grid
11. Backend data endpoints
12. Leaflet frontend foundation
13. Risk dashboard
14. Gradual connection of real teammate data
15. Rover upload integration
16. Gemini hazard classification pipeline
17. Hazard-aware routing
18. ElevenLabs briefing
19. Discord alerts
20. DigitalOcean and Vercel deployment
21. GoDaddy domain only if the core remains stable

Do not advance to the next major step without instruction.

## Working style and verification

- Build each subsystem against controlled mock data so progress does not wait
  on another teammate or physical hardware.
- Design fixtures that exercise a crossing/very-close case, an under-8-km
  case, and an irrelevant far-away case.
- Replace mocks incrementally, not all at once.
- Write small, testable scripts before API wiring when practical.
- Do not silently alter architecture, overwrite teammate work, duplicate
  models, or perform broad unrelated refactors.
- If a task is likely to exceed roughly two hours or requires an unlisted
  external service, stop and flag it before starting.
- After meaningful work, report files changed, verification commands and
  results, and a precise "done when" check.
- If a test fails, fix that scoped failure before proceeding.

## Current baseline

At the time this guide was updated:

- The Git repository is on `main` and has no commits.
- `backend/`, `frontend/`, `rover/`, and `shared/` exist and are essentially
  empty except for `shared/__init__.py`.
- `shared/schemas.py`, `backend/requirements.txt`, and
  `frontend/package.json` do not exist yet.
- `.gitignore`, `.env.example`, and this file are untracked.
- `.venv` uses Python 3.11.9 and is ignored by Git.
- Pydantic 2 is installed in `.venv`; no application framework or frontend
  dependencies have been installed.
- No secret `.env` exists.

Re-check the repository rather than assuming this baseline remains current.
