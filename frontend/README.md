# Grid Hazard Rover dashboard

React + TypeScript + Vite + Leaflet. The supplied **High-Fidelity Web Dashboard**
Figma export informed the navigation, map/detail layout, and workflows. This
implementation replaces its simulated map, data, upload results, and service
status badges. The original ZIP is unchanged.

## Run locally

From the repository root, in one terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api`, `/ingest`, and `/health` to
port 8000. For a separately deployed backend, set `VITE_API_BASE_URL` to its
public HTTPS origin at build time and configure backend `FRONTEND_URL` for
the exact frontend origin. Never put service credentials in Vite variables.

## Implemented workflows

- A single `/api/demo-summary` snapshot supplies all canonical entities and
  computed matches/risk cells from the active backend repository.
- Real OpenStreetMap/Leaflet map, all five canonical geometry types, layer
  toggles, feature selection, and closest-point match lines.
- Explainable risk components/reasons, fixture labels, unknown schedules,
  utility-to-utility versus enrichment filters, source search and links.
- JPEG upload through `/ingest/photo`, explicit coordinates and local capture
  time converted to UTC, result/error display, and snapshot refresh on save.
- Download the loaded canonical JSON snapshot, without credentials.
- Responsive layouts, keyboard-accessible native modal, loading/error/empty
  states, and retained last successful snapshot on refresh errors.

## Dashboard surfaces

- **Operations workspace** shows cross-company coordination, rover findings,
  risk explanations, protected AI call review, and Relay device inventory.
- **Company portal preview** scopes projects, matches, related findings, and
  risk areas to one selected utility. It demonstrates the intended tenant
  experience; production tenant identity still requires real authentication
  and server-enforced authorization.
- **Robot fleet** includes a clearly labeled, non-actuating FNK0052 street
  rehearsal with inspection/photo points. Evidence cards use a canonical
  hazard's `image_url` when available and otherwise state that no photo preview
  is available. Hiwonder LeArm remains disconnected and physically blocked.

During local development Vite proxies `/api`, `/ingest`, `/health`, and
`/relay` to the combined backend on port 8000.

## Verification

```powershell
npm run build
npx playwright install chromium
npm test
# Optional: running real backend, read-only smoke test
$env:LIVE_DASHBOARD = '1'
npm test
```

Tests mock photo submission and do not make paid Gemini requests or write to
MongoDB. Screenshots and reports are under ignored `tmp/`.

## Honest boundaries

API loaded means a snapshot was received; it is not an independent MongoDB
or Gemini readiness probe. The backend can use an in-memory demo repository.
`persisted` means saved to that active repository, not necessarily durable
Atlas storage. Images are not hosted by the upload endpoint. Fixture status
comes from `metadata.demo` or `metadata.is_fixture`; unlabeled data is not
automatically verified real. Basemap tiles and optional Google Fonts require
network access; overlays and system font fallbacks still work without them.
Routing, voice, alerts, source ingestion, and database writes beyond hazard
submission are not invented as frontend controls. Existing backend APIs and
the canonical shared schemas are unchanged.
