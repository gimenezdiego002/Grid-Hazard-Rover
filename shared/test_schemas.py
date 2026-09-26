"""Run from the repository root: python -m shared.test_schemas."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import ValidationError

from shared.schemas import (
    ContractModel,
    DistanceTier,
    EntityKind,
    Hazard,
    LineStringGeometry,
    Match,
    MultiLineStringGeometry,
    MultiPolygonGeometry,
    PointGeometry,
    PolygonGeometry,
    Project,
    Record,
    RiskCell,
    RiskLevel,
)


def expect_invalid(model: type[ContractModel], data: dict, field: str) -> None:
    """An expected failure must refer to the field under test."""
    try:
        model.model_validate(data)
    except ValidationError as error:
        assert any(field in item["loc"] for item in error.errors()), error
    else:
        raise AssertionError(f"{model.__name__}.{field} accepted invalid input")


def main() -> None:
    project = Project(
        id="utility-a-001",
        utility="Utility A",
        title="Distribution Line Upgrade",
        location=LineStringGeometry(
            coordinates=[(-80.36, 25.76), (-80.35, 25.77)]
        ),
    )
    record = Record(
        id="fdot-001",
        source="FDOT",
        record_type="construction",
        title="Mock corridor roadwork",
        location=PointGeometry(coordinates=(-80.355, 25.765)),
    )
    hazard = Hazard(
        id="hazard-001",
        hazard_type="vegetation",
        severity=4,
        confidence=0.94,
        description="Vegetation close to infrastructure",
        location=PointGeometry(coordinates=(-80.355, 25.765)),
        timestamp=datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc),
    )
    match = Match(
        id="match-001",
        left_id=project.id,
        left_kind=EntityKind.PROJECT,
        right_id=hazard.id,
        right_kind=EntityKind.HAZARD,
        distance_m=850.0,  # Mock result; this test performs no spatial math.
        distance_tier=DistanceTier.UNDER_1_6KM,
        intersects=False,
        closest_points=((-80.356, 25.764), (-80.355, 25.765)),
    )
    polygon = PolygonGeometry(
        coordinates=[[
            (-80.36, 25.76), (-80.35, 25.76), (-80.35, 25.77),
            (-80.36, 25.77), (-80.36, 25.76),
        ]]
    )
    risk_cell = RiskCell(
        id="risk-cell-001",
        location=polygon,
        score=91,
        level=RiskLevel.CRITICAL,
        components={"distance": 40, "timeline": 25, "hazard": 16,
                    "public_infrastructure": 10},
        reasons=["Illustrative mock risk result; scoring is not implemented."],
        project_ids=[project.id],
        record_ids=[record.id],
        hazard_ids=[hazard.id],
        match_ids=[match.id],
    )

    # Exercise all five discriminated geometry variants using JSON input.
    geometries = [
        hazard.location, project.location, polygon,
        MultiLineStringGeometry(coordinates=[project.location.coordinates]),
        MultiPolygonGeometry(coordinates=[polygon.coordinates]),
    ]
    for geometry in geometries:
        payload = project.model_dump(mode="json")
        payload["location"] = geometry.model_dump(mode="json")
        parsed = Project.model_validate(payload)
        assert type(parsed.location) is type(geometry)

    # Round trips prove enums, dates, coordinate arrays and nesting serialize.
    for entity in (project, record, hazard, match, risk_cell):
        assert type(entity).model_validate_json(entity.model_dump_json()) == entity
    assert json.loads(project.model_dump_json())["location"]["coordinates"] == [
        [-80.36, 25.76], [-80.35, 25.77]
    ]
    assert match.model_dump(mode="json")["distance_tier"] == "under_1_6km"
    assert risk_cell.model_dump(mode="json")["level"] == "CRITICAL"
    assert project.start_date is project.end_date is None
    assert record.start_date is record.end_date is None
    assert match.timeline_overlap is match.timeline_gap_days is None
    assert match.model_dump(mode="json")["timeline_overlap"] is None
    for kind in EntityKind:
        payload = match.model_dump()
        payload["right_kind"] = kind
        assert Match.model_validate(payload).right_kind is kind

    hazard_data = hazard.model_dump()
    expect_invalid(Hazard, {**hazard_data, "severity": 6}, "severity")
    for severity in (0, True, 2.5):
        expect_invalid(Hazard, {**hazard_data, "severity": severity}, "severity")
    for confidence in (-0.1, 1.1, float("nan")):
        expect_invalid(Hazard, {**hazard_data, "confidence": confidence}, "confidence")
    for score in (-1, 101, float("inf")):
        expect_invalid(RiskCell, {**risk_cell.model_dump(), "score": score}, "score")
    expect_invalid(Match, {**match.model_dump(), "distance_m": -1}, "distance_m")
    for coordinates in ((181, 25), (-80, 91), (-80,), (-80, 25, 0)):
        expect_invalid(PointGeometry, {"coordinates": coordinates}, "coordinates")
    expect_invalid(LineStringGeometry, {"coordinates": [(-80, 25)]}, "coordinates")
    expect_invalid(PolygonGeometry, {"coordinates": [polygon.coordinates[0][:-1]]},
                   "coordinates")
    expect_invalid(Hazard, {**hazard_data, "location": project.location.model_dump()},
                   "location")
    expect_invalid(Project, {**project.model_dump(), "unexpected": 1}, "unexpected")
    try:
        Project.model_validate({**project.model_dump(), "start_date": "2026-10-01",
                                "end_date": "2026-09-01"})
    except ValidationError:
        pass
    else:
        raise AssertionError("Reversed dates were accepted")

    # Mutable defaults must be independent for separate instances.
    other = RiskCell(id="empty-a", location=polygon, score=0, level=RiskLevel.LOW)
    another = RiskCell(id="empty-b", location=polygon, score=0, level=RiskLevel.LOW)
    other.metadata["test"] = True
    other.reasons.append("test")
    assert another.metadata == {} and another.reasons == []

    print("SCHEMA CONTRACT OK")
    print("models validated: Project, Record, Hazard, Match, RiskCell")
    print("geometry variants validated: Point, LineString, MultiLineString, Polygon, MultiPolygon")
    print("project coordinates:", project.location.coordinates)
    print("hazard severity:", hazard.severity)
    print("match tier:", match.model_dump(mode="json")["distance_tier"])
    print("risk score:", risk_cell.score)
    print("risk level:", risk_cell.model_dump(mode="json")["level"])
    print("unknown timeline:", match.timeline_overlap)
    print("severity 6 rejected: OK")
    print("bounds, geometry, extra fields, dates, JSON round trips, defaults: OK")


if __name__ == "__main__":
    main()
