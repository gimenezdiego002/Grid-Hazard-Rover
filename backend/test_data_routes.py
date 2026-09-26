"""Offline API tests: no Atlas credentials, network calls, or database writes."""

from copy import deepcopy
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from backend.app.config import Settings
from backend.app.data_routes import read_database
from backend.app.database import DatabaseConfigurationError
from backend.app.main import create_app


PROJECT = {
    "id": "demo:project:1", "title": "Demo line upgrade", "utility": "Demo Electric",
    "location": {"type": "LineString", "coordinates": [[-80.36, 25.76], [-80.35, 25.77]]},
    "start_date": None, "end_date": None, "metadata": {"is_fixture": True},
}
RECORD = {
    "id": "fdot_active:1", "title": "Public roadwork", "source": "FDOT",
    "record_type": "active_road_construction", "location": PROJECT["location"],
    "metadata": {"is_fixture": False},
}
HAZARD = {
    "id": "demo:hazard:1", "hazard_type": "debris_or_obstruction", "severity": 3,
    "confidence": 0.8, "location": {"type": "Point", "coordinates": [-80.35, 25.77]},
    "timestamp": "2026-09-26T12:00:00Z", "metadata": {"is_fixture": True},
}


class DataRouteTests(unittest.TestCase):
    def setUp(self):
        with patch("backend.app.main.get_settings", return_value=Settings()):
            self.app = create_app()
        self.database = MagicMock()
        self.collection = self.database.__getitem__.return_value
        self.cursor = self.collection.find.return_value
        self.cursor.sort.return_value = self.cursor
        self.cursor.skip.return_value = self.cursor
        self.cursor.limit.return_value = self.cursor
        self.app.dependency_overrides[read_database] = lambda: self.database
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def rows(self, values):
        self.cursor.__iter__.side_effect = lambda: iter(deepcopy(values))

    def test_all_collections_and_coordinate_serialization(self):
        for name, payload in (("projects", PROJECT), ("records", RECORD), ("hazards", HAZARD)):
            with self.subTest(name=name):
                self.rows([payload])
                response = self.client.get(f"/api/storage/{name}")
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["count"], 1)
                self.assertEqual(body["invalid_count"], 0)
                self.assertEqual(body["items"][0]["location"], payload["location"])
                self.assertNotIn("_id", body["items"][0])
                self.assertIsNone(body["next_offset"])
                self.database.__getitem__.assert_called_with(name)
                self.collection.find.assert_called_with({}, {"_id": 0})

    def test_unknown_dates_are_not_filled(self):
        self.rows([PROJECT])
        row = self.client.get("/api/storage/projects").json()["items"][0]
        self.assertIsNone(row["start_date"])
        self.assertIsNone(row["end_date"])

    def test_fixture_filter_does_not_assume_unlabeled_is_real(self):
        self.rows([])
        for option, expected in (("demo", True), ("real", False)):
            response = self.client.get(f"/api/storage/records?dataset={option}")
            self.assertEqual(response.status_code, 200)
            self.collection.find.assert_called_with({"metadata.is_fixture": expected}, {"_id": 0})

    def test_invalid_row_is_reported_and_page_can_advance(self):
        self.rows([{"name": "legacy project"}, PROJECT, PROJECT])
        response = self.client.get("/api/storage/projects?limit=2&offset=4")
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["invalid_count"], 1)
        self.assertEqual(body["scanned_count"], 2)
        self.assertEqual(body["next_offset"], 6)
        self.cursor.skip.assert_called_with(4)
        self.cursor.limit.assert_called_with(3)

    def test_empty_collection(self):
        self.rows([])
        body = self.client.get("/api/storage/hazards").json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["scanned_count"], 0)
        self.assertIsNone(body["next_offset"])

    def test_query_validation_before_database_access(self):
        for query in ("limit=0", "limit=501", "offset=-1", "offset=100001", "dataset=unknown"):
            with self.subTest(query=query):
                response = self.client.get("/api/storage/projects?" + query)
                self.assertEqual(response.status_code, 422)
        self.collection.find.assert_not_called()

    def test_individual_items(self):
        for name, payload in (("projects", PROJECT), ("records", RECORD), ("hazards", HAZARD)):
            self.collection.find_one.return_value = deepcopy(payload)
            response = self.client.get(f"/api/storage/{name}/{payload['id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["id"], payload["id"])
            self.collection.find_one.assert_called_with({"id": payload["id"]}, {"_id": 0})

    def test_missing_and_invalid_item(self):
        self.collection.find_one.return_value = None
        self.assertEqual(self.client.get("/api/storage/projects/missing").status_code, 404)
        self.collection.find_one.return_value = {"id": "legacy"}
        self.assertEqual(self.client.get("/api/storage/projects/legacy").status_code, 409)

    def test_database_failures_are_sanitized(self):
        secret = "mongodb://private-user:private-password@example.invalid"
        self.collection.find.side_effect = ServerSelectionTimeoutError(secret)
        response = self.client.get("/api/storage/records")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(secret, response.text)
        self.collection.find_one.side_effect = ServerSelectionTimeoutError(secret)
        self.assertEqual(self.client.get("/api/storage/records/1").json(), {"detail": "Database unavailable"})

    def test_missing_config_is_503_and_health_still_works(self):
        self.app.dependency_overrides.clear()
        with patch("backend.app.data_routes.get_database", side_effect=DatabaseConfigurationError("secret")):
            self.assertEqual(self.client.get("/api/storage/records").status_code, 503)
            self.assertEqual(self.client.get("/health").status_code, 200)

    def test_cursor_failure_is_503(self):
        self.cursor.__iter__.side_effect = ServerSelectionTimeoutError("private host")
        response = self.client.get("/api/storage/projects")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private host", response.text)

    def test_openapi_has_canonical_models(self):
        schema = self.client.get("/openapi.json").json()
        for name in ("Project", "Record", "Hazard"):
            self.assertIn(name, schema["components"]["schemas"])
        for path in ("/api/storage/projects", "/api/storage/records", "/api/storage/hazards"):
            self.assertIn(path, schema["paths"])


if __name__ == "__main__":
    unittest.main()
