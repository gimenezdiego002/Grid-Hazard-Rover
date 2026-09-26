"""Canonical shared contract. GeoJSON positions are always (longitude, latitude).

Use model_dump(mode="json") or model_dump_json() at serialization boundaries:
coordinate tuples become JSON arrays and enums become their string values.
These models validate structure, not spatial topology or risk calculations.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


Longitude = Annotated[float, Field(strict=True, ge=-180, le=180, allow_inf_nan=False)]
Latitude = Annotated[float, Field(strict=True, ge=-90, le=90, allow_inf_nan=False)]
LngLat: TypeAlias = tuple[Longitude, Latitude]
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]
NonEmptyString = Annotated[str, Field(min_length=1, pattern=r"\S")]
LineCoordinates = Annotated[list[LngLat], Field(min_length=2)]


def _closed_ring(points: list[LngLat]) -> list[LngLat]:
    if points[0] != points[-1]:
        raise ValueError("Polygon rings must end at their starting coordinate")
    if len(set(points[:-1])) < 3:
        raise ValueError("Polygon rings require at least three distinct vertices")
    return points


LinearRing = Annotated[
    list[LngLat], Field(min_length=4), AfterValidator(_closed_ring)
]
PolygonCoordinates = Annotated[list[LinearRing], Field(min_length=1)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PointGeometry(ContractModel):
    type: Literal["Point"] = "Point"
    coordinates: LngLat


class LineStringGeometry(ContractModel):
    type: Literal["LineString"] = "LineString"
    coordinates: LineCoordinates


class MultiLineStringGeometry(ContractModel):
    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: Annotated[list[LineCoordinates], Field(min_length=1)]


class PolygonGeometry(ContractModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: PolygonCoordinates


class MultiPolygonGeometry(ContractModel):
    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: Annotated[list[PolygonCoordinates], Field(min_length=1)]


Geometry: TypeAlias = Annotated[
    PointGeometry
    | LineStringGeometry
    | MultiLineStringGeometry
    | PolygonGeometry
    | MultiPolygonGeometry,
    Field(discriminator="type"),
]


class DatedEntity(ContractModel):
    """Common project/record fields; absent dates remain unknown."""

    id: NonEmptyString
    title: NonEmptyString
    description: str | None = None
    location: Geometry
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must not precede start_date")
        return self


class Project(DatedEntity):
    """Future utility construction, including linear and area geometries."""

    utility: NonEmptyString


class Record(DatedEntity):
    """External public infrastructure activity normalized by the pipeline."""

    source: NonEmptyString
    record_type: NonEmptyString


class Hazard(ContractModel):
    id: NonEmptyString
    hazard_type: NonEmptyString
    severity: Annotated[int, Field(strict=True, ge=1, le=5)]
    confidence: Annotated[FiniteNumber, Field(ge=0, le=1)]
    description: str | None = None
    location: PointGeometry
    timestamp: datetime
    image_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityKind(str, Enum):
    PROJECT = "project"
    RECORD = "record"
    HAZARD = "hazard"


class DistanceTier(str, Enum):
    CROSSING = "crossing"
    UNDER_1_6KM = "under_1_6km"
    UNDER_8KM = "under_8km"
    UNDER_40KM = "under_40km"


class Match(ContractModel):
    """Computed relationship; None timeline_overlap means insufficient dates.

    The matching engine supplies distance tiers and timeline results. This
    contract does not derive them or perform geometry calculations.
    """

    id: NonEmptyString
    left_id: NonEmptyString
    left_kind: EntityKind
    right_id: NonEmptyString
    right_kind: EntityKind
    distance_m: Annotated[FiniteNumber, Field(ge=0)]
    distance_tier: DistanceTier
    intersects: Annotated[bool, Field(strict=True)]
    timeline_overlap: Annotated[bool, Field(strict=True)] | None = None
    timeline_gap_days: Annotated[int, Field(strict=True, ge=0)] | None = None
    closest_points: tuple[LngLat, LngLat] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskCell(ContractModel):
    """Explainable geographic risk result; scoring belongs to a later engine."""

    id: NonEmptyString
    location: PolygonGeometry
    score: Annotated[FiniteNumber, Field(ge=0, le=100)]
    level: RiskLevel
    components: dict[str, FiniteNumber] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    record_ids: list[str] = Field(default_factory=list)
    hazard_ids: list[str] = Field(default_factory=list)
    match_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
