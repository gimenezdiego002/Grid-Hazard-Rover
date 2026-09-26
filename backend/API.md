# Dashboard read API

Run from the repository root using the existing root `.env`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` to try the endpoints. MongoDB credentials stay
in the backend; the frontend only needs the API's public base URL.

| GET path | Result |
|---|---|
| `/health` | Process health, independent of MongoDB availability |
| `/api/projects` | A page of canonical utility Project objects |
| `/api/records` | A page of canonical public Record objects |
| `/api/hazards` | A page of canonical Hazard observations |
| `/api/projects/{entity_id}` | One Project by its canonical ID |
| `/api/records/{entity_id}` | One Record by its canonical ID |
| `/api/hazards/{entity_id}` | One Hazard by its canonical ID |

List endpoints accept:

- `dataset=all` (default), `demo`, or `real`. Demo selects an explicit
  `metadata.is_fixture=true`; real selects an explicit false flag. Unlabeled rows
  appear only in `all` and retain their original metadata.
- `limit=100` (default), from 1 to 500.
- `offset=0` (default), from 0 to 100,000.

Examples:

```text
GET /api/records?dataset=real&limit=50
GET /api/projects?dataset=demo
GET /api/hazards/demo:hazard:pothole
```

Lists return an envelope, not a raw array. For example, a page containing only
an invalid legacy document can return:

```json
{
  "items": [],
  "count": 0,
  "invalid_count": 1,
  "scanned_count": 1,
  "offset": 0,
  "limit": 1,
  "next_offset": 1
}
```

Render `items`. To load the next page, use `next_offset` until it is null; do not
stop just because `items` is empty. Offsets count scanned database rows, including
invalid rows. `count` is the number of valid returned items, not the collection
total. Sort order is canonical ID then MongoDB ID. Offset pagination assumes a
mostly stable dataset; a live refresh can restart at offset zero.

If `invalid_count` is nonzero, show a notice that some stored rows could not be
displayed. GET requests do not repair or delete those rows. Valid items are
checked against `shared/schemas.py`; MongoDB `_id` is not exposed. GeoJSON remains
`[longitude, latitude]`; convert to Leaflet order only when rendering. Missing
dates remain null and fixture labels remain available to the UI.

Single-item requests return the canonical entity directly. Status codes:

- 404: ID was not found.
- 409: the stored item does not satisfy the shared schema.
- 422: invalid query parameters.
- 503: database unavailable or not configured. Connection details are not exposed.

These endpoints are read-only and have no authentication layer yet. They do not
perform image classification, calculate coordination matches, or generate risk
scores. The seeded `matches` and `risk_cells` are not exposed by this change.

Offline verification:

```powershell
.\.venv\Scripts\python.exe -m unittest backend.test_data_routes backend.test_backend backend.test_ai backend.ingestion.test_ingestion backend.ingestion.test_import_records -q
.\.venv\Scripts\python.exe -m shared.test_schemas
```

Use the explicit test modules above. The teammate's `test_projects.py` and
`test_connection.py` are standalone live-database scripts, not offline tests.
