# Local public-data pipeline

This package fetches the selected ArcGIS sources, normalizes them into
`shared.schemas.Project` or `Record`, and exports auditable JSON. The FDOT
import command can idempotently upsert accepted real records into the backend's
shared MongoDB collections. Matching and risk remain deterministic downstream
services and are never calculated by the ingestion pipeline.

## Setup and offline verification

Run from the repository root. Target Python is 3.11; the merged ingestion and
backend suites are verified together in the repository's Python 3.11 virtual
environment.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m shared.test_schemas
.\.venv\Scripts\python.exe -m unittest backend.ingestion.test_ingestion -v
.\.venv\Scripts\python.exe -m backend.ingestion normalize shared/fixtures/ingestion/imdc_power.snapshot.json --output tmp/fixture-run
```

The checked-in fixture is **synthetic**. Each accepted fixture entity retains
`metadata.is_fixture=true`. It demonstrates normalization, not real electric
utility coverage.

## Live commands

```powershell
.\.venv\Scripts\python.exe -m backend.ingestion probe imdc_power
.\.venv\Scripts\python.exe -m backend.ingestion probe fdot_work_program --as-of 2026-09-26
.\.venv\Scripts\python.exe -m backend.ingestion probe fdot_active
.\.venv\Scripts\python.exe -m backend.ingestion fetch fdot_active --limit 20 --output tmp/active.snapshot.json
.\.venv\Scripts\python.exe -m backend.ingestion normalize tmp/active.snapshot.json --output tmp/active-export
```

Use a new output filename/directory for each run: existing outputs are never
overwritten. `tmp/` is already ignored by Git. None of these sources needs an
API key for the public queries tested here.

- `imdc_power`: iMDC Power layer 9; accepts actual operator identity from AGCYNAME.
- `fdot_work_program`: Construction Phase layer 2; Miami-Dade county names and
  fiscal-year labels at least the reference calendar year (`--as-of`, default
  today). This deliberately broad planning filter is not an exact construction
  start-date or Florida fiscal-calendar calculation.
- `fdot_active`: Miami-Dade active construction, excluding warranty rows using
  `is820days='N'`. Actual source status and estimated end dates are preserved;
  an old estimated end date does not automatically prove the work is complete.

`fetch` defaults to the first 100 object IDs in ascending order. `--limit 0`
requests all matching rows, with a 10,000-row guard. Samples are explicitly
labeled; neither counts nor geometry rows should be read as distinct project
counts. A project can contain multiple road segments.

The fetcher inspects fields, obtains a count and object-ID list, then fetches
bounded batches. Every requested ID must appear exactly once. Missing batches,
count mismatches, network failures, and ArcGIS error responses fail the fetch
without publishing a snapshot. A successfully empty source is a distinct result.
These checks detect missing IDs; they cannot guarantee transactionally frozen
attributes while an upstream service is being updated.

## Export and MongoDB contract

Every normalization run writes:

| File | Contents |
|---|---|
| `projects.json` | Array of canonical Project objects |
| `records.json` | Array of canonical Record objects |
| `rejected.json` | Source object IDs, feature indexes, and validation reasons |
| `manifest.json` | Source/query/reference date, sample coverage, counts, snapshot hash, and limitations |

Pydantic validation runs before export; Shapely additionally rejects empty or
invalid geometry. Coordinates stay in WGS84 `[longitude, latitude]`. No source
geometry repairs or invented construction dates occur. Unknown dates remain
null; Work Program fiscal years stay in metadata. Active-construction end dates
are marked estimated. Numeric ArcGIS dates are read as UTC epoch milliseconds,
and source time-reference metadata is retained for audit.

Identical repeated entities are counted as duplicates. Conflicting duplicate
identities stop normalization rather than choosing an arbitrary version.
Accepted + rejected + duplicates equals the number of input features.

Exit codes: **0** successful, **1** failed, **2** exported with rejected rows.
Inspect `manifest.json` before import, including `selection`, `is_fixture`, and
`quality`. A shell runner may display any nonzero exit as a general failure.
Do not use a sample export to delete other database rows or replace a complete
dataset. An empty result is not authorization to clear collections.

Upsert canonical `id`; create a unique `id` index and a `2dsphere` index on
`location`. GlobalID is used where supplied; otherwise source-namespaced OBJECTID
preserves distinct source segments. OBJECTID may change on source republish, so
these identities are suitable for repeated imports of a snapshot but are not a
guarantee of identity across future dataset rebuilds. The shared lazy repository
and importer create the required collection indexes.

## Importing the accepted FDOT samples into MongoDB

The importer reuses `backend.app.database` and the root `.env`. Set
`MONGODB_URI` locally and allow this computer's current IP in the Atlas project's
database Network Access list. No key is printed by the importer.

Validate the two exports offline first:

```powershell
.\.venv\Scripts\python.exe -m backend.ingestion.import_records tmp/ingestion/fdot_active-export tmp/ingestion/fdot_work_program-current-export
```

To write the accepted records, append `--apply` to that command. It pings MongoDB,
ensures a unique `id` index and a `location` 2dsphere index on `records`, upserts
by canonical `id`, and verifies each record by reading it back. It never deletes
rows or imports the rejected rows. Fixture exports are refused. Imports are not
transactional: a failure during writes may leave some records imported; rerunning
is safe by ID. Existing incompatible indexes are reported rather than dropped.

Run importer tests with:
`python -m unittest backend.ingestion.test_import_records -v`.

## Live source verification on September 26, 2026

| Source selection | Matching feature count | Sample result |
|---|---:|---|
| iMDC Power | 0 | Successful empty snapshot; no real Project objects |
| FDOT Work Program, Miami, FISCALYR >= 2026 | 4,206 | 20 fetched; 14 accepted, 6 rejected |
| FDOT Active, Miami, non-warranty | 310 | 20 fetched; 20 accepted |

Counts can change. Full live snapshots and exports are local under
`tmp/ingestion/`; they are not committed. Rejected Work Program rows are retained
in the report instead of being assigned invented geometries. The unfiltered
Work Program probe also exposed older fiscal years, which motivated the
reference-year filter.

The live two-electric-utility source requirement is **not yet satisfied**. The
iMDC Power layer was empty, so the next source task is the challenge ZIP or
reviewed public future-plan extracts from two electric operators. Synthetic
fixtures support the integrated demo but are never represented as live source
coverage, and FDOT records remain enrichment rather than a second utility.

Source references:

- [iMDC Power](https://gisweb.miamidade.gov/arcgis/rest/services/Wasd/iMDCUtilityCoordination_2_v1/MapServer/9)
- [FDOT Work Program](https://gis.fdot.gov/arcgis/rest/services/Work_Program_Current/FeatureServer/2)
- [FDOT Active Construction](https://gis.fdot.gov/arcgis/rest/services/Active_Construction_Projects/FeatureServer/1)
- [ArcGIS query API](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/)
