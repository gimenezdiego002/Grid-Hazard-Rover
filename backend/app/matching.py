"""Canonical spatial/timeline match generation."""

from __future__ import annotations

from datetime import date
import hashlib
from itertools import combinations

from backend.app.spatial import spatial_relationship
from backend.app.timeline import compare_timelines
from shared.schemas import EntityKind, Hazard, Match, Project, Record

CanonicalEntity = Project | Record | Hazard


def _dates(entity: CanonicalEntity) -> tuple[date | None, date | None]:
    if isinstance(entity, Hazard):
        observed = entity.timestamp.date()
        return observed, observed
    return entity.start_date, entity.end_date


def _match_id(left: CanonicalEntity, right: CanonicalEntity) -> str:
    digest = hashlib.sha256(f"{left.id}|{right.id}".encode()).hexdigest()[:16]
    return f"match-{digest}"


def build_match(
    left: CanonicalEntity,
    left_kind: EntityKind,
    right: CanonicalEntity,
    right_kind: EntityKind,
) -> Match | None:
    spatial = spatial_relationship(left.location, right.location)
    if not spatial.qualifies:
        return None
    timeline = compare_timelines(*_dates(left), *_dates(right))
    assert spatial.distance_tier is not None
    return Match(
        id=_match_id(left, right),
        left_id=left.id,
        left_kind=left_kind,
        right_id=right.id,
        right_kind=right_kind,
        distance_m=round(spatial.distance_m, 2),
        distance_tier=spatial.distance_tier,
        intersects=spatial.intersects,
        timeline_overlap=timeline.overlap,
        timeline_gap_days=timeline.gap_days,
        closest_points=spatial.closest_points,
        metadata={"timeline_relationship": timeline.relationship.value},
    )


def generate_matches(
    projects: list[Project], records: list[Record], hazards: list[Hazard]
) -> list[Match]:
    """Utility-to-utility is core; records and hazards are enrichment."""
    matches: list[Match] = []
    for left, right in combinations(projects, 2):
        if left.utility == right.utility:
            continue
        match = build_match(left, EntityKind.PROJECT, right, EntityKind.PROJECT)
        if match is not None:
            matches.append(match)
    for project in projects:
        for record in records:
            match = build_match(project, EntityKind.PROJECT, record, EntityKind.RECORD)
            if match is not None:
                matches.append(match)
        for hazard in hazards:
            match = build_match(project, EntityKind.PROJECT, hazard, EntityKind.HAZARD)
            if match is not None:
                matches.append(match)
    return sorted(matches, key=lambda item: (item.distance_m, item.id))
