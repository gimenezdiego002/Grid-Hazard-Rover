"""Photo ingestion and frontend API contract tests with mocked Gemini."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import config
from backend.app.ai.hazards import classification_to_hazard
from backend.app.ai.schemas import HazardClassification
from backend.app.main import create_app
from backend.app.repository import MemoryRepository, get_repository


class IngestTests(unittest.TestCase):
    def setUp(self) -> None:
        with BytesIO() as output:
            Image.new("RGB", (20, 20), "gray").save(output, format="JPEG")
            self.jpeg = output.getvalue()
        self.repository = MemoryRepository(projects=[], records=[], hazards=[])
        self.app = create_app()
        self.app.dependency_overrides[get_repository] = lambda: self.repository
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.detected = HazardClassification(
            hazard_detected=True, hazard_type="pothole", severity=4,
            confidence=0.92, description="A pothole is visible in the road surface.",
        )

    def _post(self, **fields):
        data = {
            "longitude": "-80.3521",
            "latitude": "25.7652",
            "timestamp": "2026-09-26T16:00:00Z",
            "source": "mock-rover-1",
            **fields,
        }
        return self.client.post(
            "/ingest/photo", data=data,
            files={"image": ("hazard.jpg", self.jpeg, "image/jpeg")},
        )

    def test_detected_hazard_is_canonical_and_persisted(self) -> None:
        with patch("backend.app.api.classify_hazard", return_value=self.detected):
            response = self._post()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["hazard_detected"])
        self.assertTrue(payload["persisted"])
        self.assertEqual(payload["hazard"]["hazard_type"], "pothole")
        self.assertEqual(payload["hazard"]["location"]["coordinates"], [-80.3521, 25.7652])
        self.assertEqual(payload["hazard"]["metadata"]["source"], "mock-rover-1")
        self.assertEqual(len(self.repository.list_hazards()), 1)

    def test_no_hazard_does_not_create_entity(self) -> None:
        clear = HazardClassification(
            hazard_detected=False, hazard_type=None, severity=None, confidence=0.8,
            description="No visible infrastructure hazard.",
        )
        with patch("backend.app.api.classify_hazard", return_value=clear):
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["hazard_detected"])
        self.assertIsNone(response.json()["hazard"])
        self.assertFalse(response.json()["persisted"])
        self.assertEqual(self.repository.list_hazards(), [])

    def test_validation_blocks_bad_coordinates_timestamp_and_media(self) -> None:
        with patch("backend.app.api.classify_hazard") as classifier:
            self.assertEqual(self._post(longitude="181").status_code, 422)
            self.assertEqual(self._post(latitude="-91").status_code, 422)
            self.assertEqual(self._post(timestamp="not-a-date").status_code, 422)
            self.assertEqual(self._post(timestamp="2026-09-26T16:00:00").status_code, 422)
            png = self.client.post("/ingest/photo", data={
                "longitude": "-80.35", "latitude": "25.76",
                "timestamp": "2026-09-26T16:00:00Z",
            }, files={"image": ("bad.png", b"png", "image/png")})
            self.assertEqual(png.status_code, 415)
        classifier.assert_not_called()

    def test_all_frontend_endpoints_return_json(self) -> None:
        app = create_app()
        repository = MemoryRepository()
        app.dependency_overrides[get_repository] = lambda: repository
        with TestClient(app) as client:
            for endpoint in ("/api/projects", "/api/records", "/api/hazards",
                             "/api/matches", "/api/risk-grid", "/api/demo-summary"):
                response = client.get(endpoint)
                self.assertEqual(response.status_code, 200, endpoint)
            projects = client.get("/api/projects").json()
            self.assertEqual(projects[0]["location"]["coordinates"][0], [-80.357, 25.765])

    def test_direct_conversion_never_gets_ai_coordinates(self) -> None:
        hazard = classification_to_hazard(
            self.detected, longitude=-80.36, latitude=25.76,
            timestamp=datetime(2026, 9, 26, tzinfo=timezone.utc), hazard_id="known-id",
        )
        self.assertIsNotNone(hazard)
        assert hazard is not None
        self.assertEqual(hazard.location.coordinates, (-80.36, 25.76))
        self.assertEqual(hazard.id, "known-id")


if __name__ == "__main__":
    unittest.main(verbosity=2)
