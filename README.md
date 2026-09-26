# Grid Hazard Rover — AI and Backend

Grid Hazard Rover finds places where planned utility projects collide in space and time, then enriches that core coordination signal with public roadwork and rover-observed hazards. This repository currently contains the shared data contract and a runnable FastAPI backend. Frontend and Raspberry Pi implementation remain teammate-owned.

## Architecture

```text
JPEG + trusted lng/lat/timestamp
  -> Gemini structured visual classification
  -> canonical shared.schemas.Hazard
  -> optional MongoDB persistence
  -> closest-point spatial matching + timeline comparison
  -> deterministic Coordination Risk Index
  -> canonical Match/RiskCell JSON for the frontend
```

`shared/schemas.py` is the only canonical definition of `Project`, `Record`, `Hazard`, `Match`, and `RiskCell`. Backend helper and response models do not replace those types. All GeoJSON is stored and transmitted as `[longitude, latitude]`; Leaflet must swap to `[latitude, longitude]` only while rendering.

## Setup (PowerShell, Python 3.11)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
```

Put credentials only in `.env`, which is ignored by Git. The backend starts without Gemini or MongoDB credentials; only the features that need those services will be unavailable.

```powershell
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` for Swagger UI. DigitalOcean App Platform can use this production run command (substitute its provided port variable in the UI):

```text
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
```

## Environment variables

| Name | Purpose |
|---|---|
| `GEMINI_API_KEY` | Server-side Gemini API credential |
| `GEMINI_MODEL` | Configurable image-capable Gemini model |
| `GOOGLE_MAPS_API_KEY` | One server-side key shared by Geocoding and future Routes calls |
| `MONGODB_URI` | Optional MongoDB connection string |
| `MONGODB_DB` | Database name; defaults to `grid_hazard_rover` |
| `ELEVENLABS_API_KEY` | Reserved for optional explicit voice briefings |
| `ELEVENLABS_VOICE_ID` | Reserved voice identifier |
| `DISCORD_WEBHOOK_URL` | Reserved for optional explicit alerts |
| `FRONTEND_URL` | Additional exact CORS origin |

Never expose server keys through `VITE_*` values.

## API contract for the frontend

All successful responses are JSON. Geometry coordinates remain longitude-first.

| Method and path | Response |
|---|---|
| `GET /health` | `{"status":"ok"}`; does not require MongoDB |
| `GET /api/projects` | Array of canonical `Project` objects |
| `GET /api/records` | Array of canonical public `Record` objects |
| `GET /api/hazards` | Array of canonical rover `Hazard` objects |
| `GET /api/matches` | Array of canonical spatial/timeline `Match` objects |
| `GET /api/risk-grid` | Array of canonical explainable `RiskCell` polygons |
| `GET /api/demo-summary` | One envelope containing every demo collection |
| `POST /ingest/photo` | AI classification plus an optional canonical `Hazard` |

When MongoDB is configured, `/api/storage/projects`, `/api/storage/records`,
and `/api/storage/hazards` provide paginated `items` envelopes with fixture
filtering and invalid-row counts for data-quality inspection. These do not
replace the raw-array frontend endpoints above.

The offline store starts with safe synthetic Miami-area data: two crossing downtown utility projects, public-roadwork context, a severity-four pothole, and a separate lower-risk comparison. These are demo fixtures, not restricted infrastructure data.

### `POST /ingest/photo`

Send `multipart/form-data`:

- `image` (required): complete JPEG, maximum 8 MiB and 20 megapixels
- `longitude` (required): `-180..180`
- `latitude` (required): `-90..90`
- `timestamp` (required): ISO 8601 with UTC offset, such as `2026-09-26T16:00:00Z`
- `source` (optional): device/source label, maximum 100 characters

Detected hazard response:

```json
{
  "hazard_detected": true,
  "classification": {
    "hazard_detected": true,
    "hazard_type": "pothole",
    "severity": 4,
    "confidence": 0.92,
    "description": "A pothole is visible in the road surface."
  },
  "hazard": {
    "id": "hazard-generated-id",
    "hazard_type": "pothole",
    "severity": 4,
    "confidence": 0.92,
    "description": "A pothole is visible in the road surface.",
    "location": {"type": "Point", "coordinates": [-80.3521, 25.7652]},
    "timestamp": "2026-09-26T16:00:00Z",
    "image_url": null,
    "metadata": {"source": "mock-rover", "classification_provider": "gemini"}
  },
  "persisted": true
}
```

When Gemini reports no visible hazard, `hazard` is `null`, `persisted` is `false`, and no fake entity is created. GPS, timestamp, source, and IDs always come from trusted request/backend data—not Gemini.

## Gemini classifier

The classifier uses the official `google-genai` SDK, a configurable `GEMINI_MODEL`, inline JPEG bytes, JSON MIME type, provider-side response schema, and local Pydantic validation. Allowed labels cover potholes, road/sidewalk damage, vegetation, debris, pole/equipment damage, flooding, construction/lane closures, other visible infrastructure hazards, and a genuine no-hazard state.

Normal tests mock the SDK. An intentional one-call live test is separate:

```powershell
python -m backend.live_smoke C:\path\to\sample.jpg
```

It prints `LIVE SKIPPED` if credentials or the image are absent and never pretends an external call passed.

## Deterministic coordination logic

Spatial matching converts WGS84 geometry to a local azimuthal-equidistant metric CRS using `pyproj`, then uses Shapely closest points. It never treats latitude/longitude degrees as metres and never substitutes centroid distance.

- touching/intersection: `crossing`, 0 m
- `0 < distance < 1,600`: `under_1_6km`
- `1,600 <= distance < 8,000`: `under_8km`
- `8,000 <= distance < 40,000`: `under_40km`
- `>= 40,000`: excluded

Timeline comparison supports overlaps, gaps of at most 180 days, gaps outside that window, partial dates, and unknown dates. Unknown stays `null` in the canonical match rather than becoming false.

The Coordination Risk Index is deterministic:

- distance, max 40: crossing 40; under 1.6 km 35; under 8 km 25; under 40 km 10
- timeline, max 25: overlap 25; gap <=30 days 20; <=90 days 15; <=180 days 10; otherwise/unknown 0
- nearby rover hazard, max 20: severity × 4 (within 8 km)
- nearby public context, max 15: crossing/under 1.6 km 15; under 8 km 10

The total is clamped to `0..100`: LOW `0..29`, MODERATE `30..59`, HIGH `60..79`, CRITICAL `80..100`. Every `RiskCell` includes component scores, human-readable reasons, and related IDs.

## MongoDB and geocoding

Without `MONGODB_URI`, a process-local demo repository is used. With Mongo configured, access stays lazy and canonical projects, records, hazards, matches, and risk cells can be upserted. Every collection gets a unique `id` index; collections with a GeoJSON `location` (`projects`, `records`, `hazards`, and `risk_cells`) also get a `2dsphere` index.

Google Geocoding is isolated in `backend.app.geocoding` and called only when normalized source data has an address but no geometry. Existing source coordinates bypass Google. Results are cached in process and converted from Google's `lat/lng` object to canonical `[lng, lat]`.

The data-pipeline teammate can normalize public ArcGIS/utility inputs directly into the shared models. Gemini is not used for already-structured data and never computes distance, timeline, or risk.

The integrated `backend.ingestion` package provides bounded ArcGIS fetches,
source-specific canonical normalization, rejection manifests, reproducible
fixture tests, and an idempotent FDOT record importer. Records imported into the
shared Mongo collections are immediately visible to the primary API and become
public-context inputs to deterministic matching and risk scoring.

```powershell
python -m backend.ingestion probe fdot_active
python -m backend.ingestion fetch fdot_active --limit 20 --output tmp\fdot.snapshot.json
python -m backend.ingestion normalize tmp\fdot.snapshot.json --output tmp\fdot-export
python -m backend.ingestion.import_records tmp\fdot-export --apply
```

## Tests

```powershell
python -W error -m unittest discover -v
python -m shared.test_schemas
python -m compileall backend shared
python -m pip check
```

Automated tests perform no live Gemini, Google, or MongoDB calls. They cover schema validation, classifier requests and failure modes, canonical hazard conversion, multipart ingest, coordinate order, geometry variants, distance tiers, timeline states, match enrichment, exact risk scoring, API contracts, geocoding, repository behavior, CORS, and optional configuration.

## External integrations not in the core MVP

Google Routes exposure scoring, ElevenLabs briefings, and Discord alerts remain optional follow-ups. The backend does not claim Google Routes can directly avoid custom hazard polygons; a future implementation must request alternatives and score their exposure locally. No frontend, Leaflet rendering, rover hardware, GPIO, camera, or motor code is implemented here.
