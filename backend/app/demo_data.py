"""Public, synthetic Miami-area fixtures for offline backend demonstrations."""

from __future__ import annotations

from datetime import date, datetime, timezone

from shared.schemas import Hazard, LineStringGeometry, PointGeometry, Project, Record


def demo_projects() -> list[Project]:
    return [
        Project(
            id="utility-a-downtown-duct",
            utility="Utility A",
            title="Downtown communications duct renewal",
            description="Synthetic future utility project for the public demo.",
            location=LineStringGeometry(coordinates=[(-80.357, 25.765), (-80.347, 25.765)]),
            start_date=date(2026, 11, 1), end_date=date(2027, 3, 15), status="planned",
            metadata={"demo": True},
        ),
        Project(
            id="utility-b-downtown-water",
            utility="Utility B",
            title="Downtown water-main renewal",
            description="Synthetic crossing project for coordination demonstration.",
            location=LineStringGeometry(coordinates=[(-80.352, 25.760), (-80.352, 25.770)]),
            start_date=date(2027, 1, 10), end_date=date(2027, 5, 1), status="planned",
            metadata={"demo": True},
        ),
        Project(
            id="utility-a-west-demo",
            utility="Utility A",
            title="West service reliability work",
            location=LineStringGeometry(coordinates=[(-80.18, 25.76), (-80.175, 25.765)]),
            start_date=date(2028, 1, 1), end_date=date(2028, 2, 1), status="concept",
            metadata={"demo": True},
        ),
        Project(
            id="utility-b-west-demo",
            utility="Utility B",
            title="West conduit inspection",
            location=LineStringGeometry(coordinates=[(-80.13, 25.76), (-80.125, 25.765)]),
            start_date=date(2029, 1, 1), end_date=date(2029, 2, 1), status="concept",
            metadata={"demo": True},
        ),
    ]


def demo_records() -> list[Record]:
    return [Record(
        id="miami-dade-demo-roadwork",
        source="Miami-Dade County",
        record_type="public_roadwork",
        title="Demo-safe downtown resurfacing context",
        description="Synthetic public record; not operational infrastructure data.",
        location=PointGeometry(coordinates=(-80.3522, 25.7651)),
        start_date=date(2027, 1, 15), end_date=date(2027, 4, 15), status="planned",
        metadata={"demo": True},
    )]


def demo_hazards() -> list[Hazard]:
    return [Hazard(
        id="demo-rover-pothole",
        hazard_type="pothole",
        severity=4,
        confidence=0.93,
        description="Synthetic rover observation of a visible pothole.",
        location=PointGeometry(coordinates=(-80.3521, 25.7652)),
        timestamp=datetime(2026, 9, 26, 16, 0, tzinfo=timezone.utc),
        metadata={"demo": True, "source": "mock-rover"},
    )]
