"""Transparent Coordination Risk Index and geographic risk-cell generation."""

from __future__ import annotations

from math import cos, radians

from shared.schemas import (
    DistanceTier,
    EntityKind,
    Hazard,
    Match,
    PolygonGeometry,
    Record,
    RiskCell,
    RiskLevel,
)

DISTANCE_SCORES = {
    DistanceTier.CROSSING: 40.0,
    DistanceTier.UNDER_1_6KM: 35.0,
    DistanceTier.UNDER_8KM: 25.0,
    DistanceTier.UNDER_40KM: 10.0,
}


def risk_level(score: float) -> RiskLevel:
    if score >= 80:
        return RiskLevel.CRITICAL
    if score >= 60:
        return RiskLevel.HIGH
    if score >= 30:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def _timeline_score(match: Match) -> tuple[float, str]:
    relationship = match.metadata.get("timeline_relationship")
    gap = match.timeline_gap_days
    if relationship == "overlap":
        return 25.0, "The utility project schedules overlap."
    if relationship == "within_180_days" and gap is not None:
        if gap <= 30:
            score = 20.0
        elif gap <= 90:
            score = 15.0
        else:
            score = 10.0
        return score, f"The project schedules are {gap} days apart (within 180 days)."
    if relationship == "unknown":
        return 0.0, "Timeline risk is unknown because date information is incomplete."
    return 0.0, "The project schedules are outside the 180-day coordination window."


def _related(match: Match, project_ids: set[str], kind: EntityKind) -> bool:
    return (
        match.left_kind is EntityKind.PROJECT
        and match.left_id in project_ids
        and match.right_kind is kind
    ) or (
        match.right_kind is EntityKind.PROJECT
        and match.right_id in project_ids
        and match.left_kind is kind
    )


def _cell_polygon(match: Match) -> PolygonGeometry:
    assert match.closest_points is not None
    lng = (match.closest_points[0][0] + match.closest_points[1][0]) / 2
    lat = (match.closest_points[0][1] + match.closest_points[1][1]) / 2
    half_height = 250 / 111_320
    half_width = 250 / (111_320 * max(cos(radians(lat)), 0.2))
    return PolygonGeometry(coordinates=[[
        (lng - half_width, lat - half_height),
        (lng + half_width, lat - half_height),
        (lng + half_width, lat + half_height),
        (lng - half_width, lat + half_height),
        (lng - half_width, lat - half_height),
    ]])


def build_risk_cell(
    core_match: Match,
    all_matches: list[Match],
    records: list[Record],
    hazards: list[Hazard],
) -> RiskCell:
    if not (
        core_match.left_kind is EntityKind.PROJECT
        and core_match.right_kind is EntityKind.PROJECT
    ):
        raise ValueError("Risk cells require a utility project-to-project core match")
    project_ids = {core_match.left_id, core_match.right_id}
    record_by_id = {item.id: item for item in records}
    hazard_by_id = {item.id: item for item in hazards}
    nearby_tiers = {
        DistanceTier.CROSSING,
        DistanceTier.UNDER_1_6KM,
        DistanceTier.UNDER_8KM,
    }
    record_matches = [
        item for item in all_matches
        if _related(item, project_ids, EntityKind.RECORD)
        and item.distance_tier in nearby_tiers
    ]
    hazard_matches = [
        item for item in all_matches
        if _related(item, project_ids, EntityKind.HAZARD)
        and item.distance_tier in nearby_tiers
    ]

    distance = DISTANCE_SCORES[core_match.distance_tier]
    reasons = [
        f"Utility projects are {core_match.distance_m:.0f} m apart "
        f"({core_match.distance_tier.value})."
    ]
    timeline, timeline_reason = _timeline_score(core_match)
    reasons.append(timeline_reason)

    related_hazard_ids = sorted({
        item.right_id if item.right_kind is EntityKind.HAZARD else item.left_id
        for item in hazard_matches
    })
    related_hazards = [hazard_by_id[item] for item in related_hazard_ids if item in hazard_by_id]
    strongest = max(related_hazards, key=lambda item: item.severity, default=None)
    hazard_score = float(strongest.severity * 4) if strongest else 0.0
    if strongest:
        reasons.append(
            f"Nearby rover hazard '{strongest.hazard_type}' has severity {strongest.severity}/5."
        )

    related_record_ids = sorted({
        item.right_id if item.right_kind is EntityKind.RECORD else item.left_id
        for item in record_matches
    })
    public_score = 0.0
    if record_matches:
        nearest = min(record_matches, key=lambda item: item.distance_m)
        public_score = {
            DistanceTier.CROSSING: 15.0,
            DistanceTier.UNDER_1_6KM: 15.0,
            DistanceTier.UNDER_8KM: 10.0,
            DistanceTier.UNDER_40KM: 5.0,
        }[nearest.distance_tier]
        sources = sorted({record_by_id[item].source for item in related_record_ids if item in record_by_id})
        reasons.append(f"Nearby public infrastructure context: {', '.join(sources) or 'public record'}.")

    components = {
        "distance": distance,
        "timeline": timeline,
        "hazard": hazard_score,
        "public_infrastructure": public_score,
    }
    score = min(100.0, max(0.0, sum(components.values())))
    return RiskCell(
        id=f"risk-{core_match.id.removeprefix('match-')}",
        location=_cell_polygon(core_match),
        score=score,
        level=risk_level(score),
        components=components,
        reasons=reasons,
        project_ids=sorted(project_ids),
        record_ids=related_record_ids,
        hazard_ids=related_hazard_ids,
        match_ids=sorted({core_match.id, *(item.id for item in record_matches + hazard_matches)}),
        metadata={"formula_version": "coordination-risk-v1"},
    )


def generate_risk_grid(
    matches: list[Match], records: list[Record], hazards: list[Hazard]
) -> list[RiskCell]:
    core = [
        item for item in matches
        if item.left_kind is EntityKind.PROJECT and item.right_kind is EntityKind.PROJECT
    ]
    return sorted(
        (build_risk_cell(item, matches, records, hazards) for item in core),
        key=lambda item: (-item.score, item.id),
    )
