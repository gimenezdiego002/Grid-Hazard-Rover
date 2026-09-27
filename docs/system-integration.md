# Team integration architecture

This document records how Diego's Grid backend, Matias's ingestion pipeline,
and Monty's Relay subsystem cooperate without erasing their distinct contracts.

## Runtime boundary

`backend.app.main:app` is the obvious combined demo startup. It exposes the
canonical Grid API and mounts the existing Relay applications under namespaces:

- `/relay/` — Relay mission simulator, replay API, and dashboard
- `/relay/fleet/` — Relay's bounded telemetry gateway

The original `relay_gateway.api:app` and `relay_gateway.fleet_gateway:app`
entry points remain valid for isolated deployment and testing. Relay mission
state, telemetry retention, and spending state remain separate from canonical
Grid collections.

## Contract boundary

`shared/schemas.py` remains the sole definition of `Project`, `Record`,
`Hazard`, `Match`, and `RiskCell`. Relay's `Observation`, `Scenario`, `Finding`,
`ReferenceDocument`, and `MissionBudget` retain their original meanings.

A Relay `Finding` is provisional and cannot become a `Hazard` alone. The
reviewed bridge at `POST /api/integrations/relay/hazards` requires:

- an explicit reviewed flag;
- trusted longitude-first GeoJSON coordinates;
- an offset-aware wall-clock timestamp;
- a trusted severity from 1 through 5;
- stable mission, robot, and event identities; and
- a Relay finding whose status is `suspected_hazard` and has a hazard type.

The adapter carries Relay confidence, summary, references, evidence identity,
and simulation status into canonical metadata. It derives only a stable ID from
the three trusted Relay identities. It never invents location, time, severity,
distance, timeline overlap, or risk.

Once persisted through the standard repository, the hazard is returned by
`GET /api/hazards` and automatically participates in the existing matching and
deterministic risk pipeline. No duplicate risk or public-data pipeline exists.

## Contributor responsibilities preserved

- Diego: image ingestion, Gemini visual classification, canonical persistence,
  closest-point spatial matching, timelines, risk, and Grid APIs.
- Matias: bounded ArcGIS/public-record ingestion and normalization into the
  same canonical `Record` collection consumed by matching and risk.
- Monty: missions, telemetry intake/consumption, duplicate and sequence safety,
  mock/live boundaries, provider controls, integrations, and Relay UI.

## Python and persistence decisions

Static compilation and the complete Relay test package show no Python 3.12-only
language feature. Relay metadata therefore supports Python 3.11, matching the
Grid backend; Python 3.12 remains supported. The MongoDB optional dependency is
bounded to compatible PyMongo 4.x rather than an older exact patch so the two
subsystems can share one environment.

Canonical Grid data uses `projects`, `records`, `hazards`, `matches`, and
`risk_cells`; spatial collections keep `2dsphere` indexes. Relay-specific
mission and governance storage remains under its existing names and files.

## FNK0052 source path

On `Diego-Crawler-Plan`, the robot package adds a mock-first producer for this
architecture. Semantic robot commands go through a controller and explicit
actuation gate; Freenove's official implementation retains gait/servo control.
Robot heartbeat and inspection evidence use Relay's existing envelopes and
deduplication. JPEG plus trusted operator/mission location and timestamp uses
Grid's existing `/ingest/photo`; the resulting canonical hazard therefore joins
Matias's normalized records and Diego's matching/risk pipeline without a second
schema or database.
