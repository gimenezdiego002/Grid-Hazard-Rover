# Grid Hazard Rover: current data-pipeline plan

Updated September 26, 2026 to reflect the owner's latest scope.

## Current scope and ownership

Focus on the data pipeline first, then connect its validated output to MongoDB
with the teammate implementing that integration. Decide subsequent work after
that handoff. The hardware teammate owns the rover and showcase video; we will
help with those later.

This sequencing supersedes the previous broad implementation roadmap. Current
work must run locally without MongoDB, FastAPI, a dashboard, or rover hardware.
Preserve the existing shared schema contract and any teammate implementation.

The full pipeline is more than a two-hour work package. Implement it as bounded
source-discovery, adapter, validation, and export tasks. This document defines
the plan; it does not claim those tasks have been implemented.

## Pipeline boundary

Public source -> fetch or extract -> normalize -> validate -> deduplicate
-> local JSON export and quality report -> teammate's MongoDB integration.

The pipeline must preserve the information needed for later project matching,
hazard analysis, and route warnings. Computing matches, risk scores, routes, or
inspection missions is downstream work, not a prerequisite for database handoff.

## Data we need

| Input | Shared model | Minimum useful content |
|---|---|---|
| Future plans from two electric utilities | Project | Utility identity, project title, source-backed geometry, known dates/status, provenance |
| Local public construction context from iMDC/FDOT | Record | Source/type, title, geometry, known schedule/status, provenance |
| Mock rover observations for interface validation | Hazard | Observation ID, hazard type, severity, confidence, point location, timestamp |

Keep the dataset small and current/future-focused. Historical utility work,
crash archives, flood layers, and broad asset catalogs are outside this phase.

Two electric utilities remain necessary for Sperry. Power plus water/sewer or
FDOT roadwork is useful context but does not satisfy that requirement. Do not
force the electric projects and a later Miami rover demo into one geography.

Real image capture and Gemini classification are a later input integration.
For this handoff, validate clearly labeled mock Hazard objects so the MongoDB
teammate knows the expected format. Do not present those as observed hazards.

## Implementation order

### 1. Inspect and select a small source set

Check the repository and teammate files before creating adapters. Review
shared/schemas.py and run the existing contract verification.

Locate the challenge's actual resource ZIP if supplied; the challenge description
mentions it, but the attachment provided so far contains only text. Public utility
planning documents are an alternative. Inspect enough source material to confirm
two electric operators have usable future project records.

Inspect iMDC/FDOT candidate metadata, record counts, sample geometries, date
coverage, and statuses before choosing the smallest useful local context source.
Do not assume that a published layer has usable features.

Deliverable: a short source manifest recording URLs/files, operator or source,
geographic coverage, selected fields, date/location precision, retrieval time,
and any access or data-quality limitation.

Done when: every selected source has sample data and a documented mapping.
If a source is unavailable, report it and continue with explicitly labeled
fixtures; live-data acceptance remains incomplete.

### 2. Build small fetch/extract adapters

Place pipeline code under backend/ingestion/, reusing any teammate work found
there. No database imports in fetching or normalization.

For ArcGIS, request GeoJSON in WGS84, use stable pagination, honor transfer-limit
indicators, verify completeness, and implement bounded retries/timeouts. Preserve
a small local source snapshot for repeatable development. Distinguish a genuinely
empty result from a failed or incomplete fetch.

For utility documents, prefer structured tables or a small manually reviewed
extract when adequate. Use Gemini only if messy source material needs it, with
source/page evidence and validated structured output. Do not build a general
document-processing platform or use an LLM to transform already-clean GeoJSON.

Done when: selected inputs can be reproduced from saved samples, and live fetches
either produce complete results or explicit failures.

### 3. Normalize into the existing contract

Import canonical models from shared/schemas.py. Do not define replacements.

- Map upstream geometry to location, with [longitude, latitude] coordinates.
- Map project/operator fields to title and utility; never infer operator identity
  solely from a layer name such as Power.
- Use source-namespaced stable IDs; preserve distinct segments rather than
  overwriting them with an insufficiently unique project key.
- Preserve provenance in source_url and documented metadata keys: source name,
  source ID, retrieval timestamp, document page where applicable, date precision,
  geometry precision, and whether the record is a fixture.
- Preserve missing dates as null. Fiscal years, expected completion quarters,
  and administrative request dates belong in metadata when they do not establish
  construction start/end dates.
- Do not invent coordinates. Retain unresolved source rows separately with the
  reason they could not become valid geospatial entities.

Done when: Project, Record, and mock Hazard payloads validate and serialize using
model_dump(mode="json"), with no database-specific fields.

### 4. Validate and deduplicate

Check required fields, date ordering, finite coordinate values, coordinate
bounds, geometry topology, source/operator identity, stable IDs, and duplicate
rows. Canonical geometry schemas validate structure; topology needs a separate
check. Record transformations explicitly and quarantine unsupported geometry.

Keep accepted, duplicate, and rejected counts reconcilable with fetched input.
Every rejected row needs a source reference and actionable reason.

Repeating normalization on the same snapshot must preserve entity IDs and content.
Do not silently merge unrelated road segments or utility projects. Do not mark
unknown schedules as confirmed future construction.

Done when: focused fixture tests cover valid data, missing dates, invalid
geometry, duplicates, source failures, and a repeated run.

### 5. Export a database-ready handoff

Write UTF-8 JSON arrays of canonical objects:

- projects.json
- records.json
- hazards.mock.json (separate to prevent accidental production import)
- manifest.json with source/snapshot details and counts
- rejected.json with source references and validation reasons

These are planned artifacts, not files already generated. Keep snapshots bounded
and out of version control when inappropriate; commit only small public fixtures
needed for reproducible tests.

Document one local command to reproduce exports and one to validate them. The
teammate can import canonical id values using idempotent upserts and add
2dsphere indexes on location. MongoDB credentials, connection code, and collection
setup remain with that teammate.

Done when: exported arrays round-trip through the shared Pydantic models, counts
match the quality report, and the teammate has an exact example of each payload.

### 6. Connect with the MongoDB teammate

Only after the local pipeline passes, connect its output to the teammate's
existing database code. Agree on import handling and failures using actual
validated sample files. Do not create a competing MongoDB abstraction.

Done when: the same export can be imported twice without duplicating entities,
stored geometry remains GeoJSON in longitude/latitude order, and retrieved
records still validate against the shared contract.

Then reassess the next step with the owner.

## Verification and constraints

The existing command is python -m shared.test_schemas. It passed during the
earlier planning inspection; confirm the interpreter/environment again when
implementation starts. Pipeline-specific tests should be offline and use
small public or explicitly synthetic fixtures. Live-source checks are separate.

Never store secrets in exports, commit .env files, or ingest CEII. Preserve source
attribution and check actual source access conditions before ingestion.

Do not add a dashboard, hardware controls, video production, routing, voice,
deployment, utility history, or a new scoring engine during this phase.
The later product still supports inspection, collaboration, and mobility; those
consumers will use the validated data produced here.

## Pipeline acceptance

This phase is complete when a repeatable local run exports validated, traceable
future projects from two electric utilities and the selected local public
context, reports rejected/incomplete data honestly, and provides a separately
labeled mock rover payload for the MongoDB handoff. Source-backed data must be
distinguishable from fixtures and approximate locations/dates.

## Implementation progress

The first ArcGIS ingestion slice is implemented on branch matias. It includes
source probes, bounded fetching, canonical normalization, validation/rejection
reports, local exports, and offline tests. See backend/ingestion/README.md for
commands and live verification results. MongoDB remains untouched.

Live checks found the iMDC Power layer empty. FDOT samples produce usable public
context, with invalid geometries explicitly rejected. The next source task is
obtaining public future plans for two electric operators through the challenge
resources or reviewed public documents; the current fixtures do not satisfy it.
