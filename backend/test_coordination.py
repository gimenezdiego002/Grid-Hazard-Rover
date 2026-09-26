"""Deterministic spatial, timeline, match, and risk-engine tests."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import unittest

from backend.app.demo_data import demo_hazards, demo_projects, demo_records
from backend.app.matching import generate_matches
from backend.app.risk import generate_risk_grid, risk_level
from backend.app.spatial import distance_tier, spatial_relationship
from backend.app.timeline import TimelineRelationship, compare_timelines
from backend.ingestion.normalize import normalize_snapshot
from shared.schemas import (
    DistanceTier,
    LineStringGeometry,
    MultiLineStringGeometry,
    MultiPolygonGeometry,
    PointGeometry,
    PolygonGeometry,
    Project,
    RiskLevel,
)


class SpatialTests(unittest.TestCase):
    def test_intersection_is_crossing_zero(self) -> None:
        horizontal = LineStringGeometry(coordinates=[(-80.36, 25.76), (-80.34, 25.76)])
        vertical = LineStringGeometry(coordinates=[(-80.35, 25.75), (-80.35, 25.77)])
        result = spatial_relationship(horizontal, vertical)
        self.assertTrue(result.intersects)
        self.assertEqual(result.distance_m, 0)
        self.assertEqual(result.distance_tier, DistanceTier.CROSSING)

    def test_distance_tiers_and_exclusion(self) -> None:
        origin = PointGeometry(coordinates=(-80.36, 25.76))
        cases = [
            (-80.355, DistanceTier.UNDER_1_6KM),
            (-80.33, DistanceTier.UNDER_8KM),
            (-80.20, DistanceTier.UNDER_40KM),
            (-79.80, None),
        ]
        for longitude, expected in cases:
            with self.subTest(longitude=longitude):
                result = spatial_relationship(origin, PointGeometry(coordinates=(longitude, 25.76)))
                self.assertEqual(result.distance_tier, expected)
        self.assertEqual(distance_tier(0), DistanceTier.CROSSING)
        self.assertIsNone(distance_tier(40_000))

    def test_point_line_and_all_geometry_variants(self) -> None:
        line = LineStringGeometry(coordinates=[(-80.36, 25.76), (-80.35, 25.77)])
        polygon = PolygonGeometry(coordinates=[[(-80.36, 25.76), (-80.35, 25.76),
            (-80.35, 25.77), (-80.36, 25.77), (-80.36, 25.76)]])
        variants = [
            PointGeometry(coordinates=(-80.355, 25.765)),
            line,
            MultiLineStringGeometry(coordinates=[line.coordinates]),
            polygon,
            MultiPolygonGeometry(coordinates=[polygon.coordinates]),
        ]
        for geometry in variants:
            with self.subTest(type=geometry.type):
                result = spatial_relationship(geometry, PointGeometry(coordinates=(-80.355, 25.765)))
                self.assertGreaterEqual(result.distance_m, 0)
                self.assertLess(result.distance_m, 40_000)
                self.assertAlmostEqual(result.closest_points[0][0], -80.355, places=2)


class TimelineTests(unittest.TestCase):
    def test_overlap_window_outside_and_unknown(self) -> None:
        overlap = compare_timelines(date(2026, 1, 1), date(2026, 3, 1),
                                    date(2026, 2, 1), date(2026, 4, 1))
        self.assertEqual(overlap.relationship, TimelineRelationship.OVERLAP)
        self.assertTrue(overlap.overlap)
        self.assertEqual(overlap.gap_days, 0)
        within = compare_timelines(date(2026, 1, 1), date(2026, 1, 31),
                                   date(2026, 7, 30), date(2026, 8, 1))
        self.assertEqual(within.relationship, TimelineRelationship.WITHIN_WINDOW)
        self.assertEqual(within.gap_days, 180)
        outside = compare_timelines(date(2026, 1, 1), date(2026, 1, 31),
                                    date(2026, 8, 1), date(2026, 8, 2))
        self.assertEqual(outside.relationship, TimelineRelationship.OUTSIDE_WINDOW)
        unknown = compare_timelines(None, None, date(2026, 1, 1), None)
        self.assertEqual(unknown.relationship, TimelineRelationship.UNKNOWN)
        self.assertIsNone(unknown.overlap)
        self.assertIsNone(unknown.gap_days)

    def test_partial_date_is_preserved_as_known_point(self) -> None:
        result = compare_timelines(date(2026, 1, 1), None, date(2026, 1, 2), None)
        self.assertEqual(result.relationship, TimelineRelationship.WITHIN_WINDOW)
        self.assertEqual(result.gap_days, 1)


class CoordinationTests(unittest.TestCase):
    def test_ingestion_fixture_flows_into_matching_and_risk(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parents[1]
            / "shared" / "fixtures" / "ingestion" / "imdc_power.snapshot.json"
        )
        normalized = normalize_snapshot(json.loads(fixture_path.read_text(encoding="utf-8")))
        projects = [Project.model_validate(item) for item in normalized["projects"]]
        matches = generate_matches(projects, [], [])
        cells = generate_risk_grid(matches, [], [])
        self.assertEqual({item.utility for item in projects}, {"Demo Electric A", "Demo Electric B"})
        self.assertTrue(any(item.distance_tier is DistanceTier.CROSSING for item in matches))
        self.assertEqual(cells[0].score, 65)
        self.assertEqual(cells[0].level, RiskLevel.HIGH)

    def test_demo_matches_and_explainable_risk_grid(self) -> None:
        projects, records, hazards = demo_projects(), demo_records(), demo_hazards()
        matches = generate_matches(projects, records, hazards)
        core = [item for item in matches if item.left_kind.value == "project"
                and item.right_kind.value == "project"]
        self.assertGreaterEqual(len(core), 2)
        self.assertTrue(any(item.distance_tier is DistanceTier.CROSSING for item in core))
        self.assertTrue(any(item.right_kind.value == "record" for item in matches))
        self.assertTrue(any(item.right_kind.value == "hazard" for item in matches))
        cells = generate_risk_grid(matches, records, hazards)
        self.assertEqual(cells[0].score, 96)
        self.assertEqual(cells[0].level, RiskLevel.CRITICAL)
        self.assertEqual(cells[0].components, {
            "distance": 40.0, "timeline": 25.0,
            "hazard": 16.0, "public_infrastructure": 15.0,
        })
        self.assertTrue(cells[0].reasons)
        self.assertTrue(any(item.level is RiskLevel.LOW for item in cells))
        coordinates = cells[0].model_dump(mode="json")["location"]["coordinates"]
        self.assertLess(coordinates[0][0][0], -80)
        self.assertGreater(coordinates[0][0][1], 25)

    def test_level_boundaries(self) -> None:
        for score, expected in ((0, RiskLevel.LOW), (29, RiskLevel.LOW),
                                (30, RiskLevel.MODERATE), (59, RiskLevel.MODERATE),
                                (60, RiskLevel.HIGH), (79, RiskLevel.HIGH),
                                (80, RiskLevel.CRITICAL), (100, RiskLevel.CRITICAL)):
            self.assertEqual(risk_level(score), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
