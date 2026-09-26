"""Closest-point geospatial relationships in a local metric projection."""

from __future__ import annotations

from dataclasses import dataclass

from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import nearest_points, transform

from shared.schemas import DistanceTier, Geometry, LngLat

MAX_MATCH_DISTANCE_M = 40_000.0


@dataclass(frozen=True)
class SpatialResult:
    distance_m: float
    distance_tier: DistanceTier | None
    intersects: bool
    closest_points: tuple[LngLat, LngLat]

    @property
    def qualifies(self) -> bool:
        return self.distance_tier is not None


def distance_tier(distance_m: float) -> DistanceTier | None:
    if distance_m < 0:
        raise ValueError("distance_m must be non-negative")
    if distance_m == 0:
        return DistanceTier.CROSSING
    if distance_m < 1_600:
        return DistanceTier.UNDER_1_6KM
    if distance_m < 8_000:
        return DistanceTier.UNDER_8KM
    if distance_m < MAX_MATCH_DISTANCE_M:
        return DistanceTier.UNDER_40KM
    return None


def _as_shape(geometry: Geometry):
    return shape(geometry.model_dump(mode="json"))


def _local_transformers(left, right) -> tuple[Transformer, Transformer]:
    min_x = min(left.bounds[0], right.bounds[0])
    min_y = min(left.bounds[1], right.bounds[1])
    max_x = max(left.bounds[2], right.bounds[2])
    max_y = max(left.bounds[3], right.bounds[3])
    lon_0 = (min_x + max_x) / 2
    lat_0 = (min_y + max_y) / 2
    local = CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat_0:.12f} +lon_0={lon_0:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    return (
        Transformer.from_crs("EPSG:4326", local, always_xy=True),
        Transformer.from_crs(local, "EPSG:4326", always_xy=True),
    )


def spatial_relationship(left_geometry: Geometry, right_geometry: Geometry) -> SpatialResult:
    """Calculate actual closest geometry distance; never centroid distance."""
    left_wgs84 = _as_shape(left_geometry)
    right_wgs84 = _as_shape(right_geometry)
    forward, inverse = _local_transformers(left_wgs84, right_wgs84)
    left_metric = transform(forward.transform, left_wgs84)
    right_metric = transform(forward.transform, right_wgs84)
    intersects = left_metric.intersects(right_metric)
    raw_distance = left_metric.distance(right_metric)
    distance_m = 0.0 if intersects or raw_distance < 1e-6 else float(raw_distance)
    left_point, right_point = nearest_points(left_metric, right_metric)
    left_lng, left_lat = inverse.transform(left_point.x, left_point.y)
    right_lng, right_lat = inverse.transform(right_point.x, right_point.y)
    return SpatialResult(
        distance_m=distance_m,
        distance_tier=distance_tier(distance_m),
        intersects=intersects,
        closest_points=((left_lng, left_lat), (right_lng, right_lat)),
    )
