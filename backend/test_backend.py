"""Run from the repository root with python -m unittest backend.test_backend."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import config, database
from backend.app.main import create_app
from shared.schemas import Hazard, Match, Project, Record, RiskCell


class BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict("os.environ", {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.dotenv = patch("backend.app.config.load_dotenv")
        self.dotenv.start()
        self.addCleanup(self.dotenv.stop)
        config.get_settings.cache_clear()
        self.addCleanup(config.get_settings.cache_clear)
        database.close_mongo_client()
        self.addCleanup(database.close_mongo_client)

    def test_health_docs_and_shared_imports_without_mongo(self) -> None:
        with patch("backend.app.database.MongoClient") as mongo:
            with TestClient(create_app()) as client:
                self.assertEqual(client.app.title, "Grid Hazard Rover API")
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"status": "ok"})
                docs = client.get("/docs")
                self.assertEqual(docs.status_code, 200)
                self.assertIn("SwaggerUIBundle", docs.text)
                schema = client.get("/openapi.json")
                self.assertEqual(schema.status_code, 200)
                self.assertIn("/health", schema.json()["paths"])
            mongo.assert_not_called()
        for model in (Project, Record, Hazard, Match, RiskCell):
            self.assertEqual(model.__module__, "shared.schemas")

    def test_config_defaults_and_overrides(self) -> None:
        defaults = config.get_settings()
        self.assertIsNone(defaults.mongodb_uri)
        self.assertFalse(defaults.mongodb_uri_has_valid_scheme)
        self.assertIsNone(defaults.gemini_api_key)
        self.assertIsNone(defaults.gemini_model)
        self.assertEqual(defaults.mongodb_db, "grid_hazard_rover")
        self.assertEqual(defaults.cors_origins, ["http://localhost:5173"])
        with patch.dict("os.environ", {"MONGODB_DB": "test_db",
                                     "FRONTEND_URL": "https://frontend.example/"}):
            config.get_settings.cache_clear()
            settings = config.get_settings()
            self.assertEqual(settings.mongodb_db, "test_db")
            self.assertEqual(settings.frontend_url, "https://frontend.example")

    def test_mongo_uri_scheme_detection(self) -> None:
        self.assertFalse(config.Settings(mongodb_uri="not-a-mongodb-uri").mongodb_uri_has_valid_scheme)
        self.assertTrue(config.Settings(mongodb_uri="mongodb://localhost:27017").mongodb_uri_has_valid_scheme)
        self.assertTrue(config.Settings(mongodb_uri="mongodb+srv://example.invalid").mongodb_uri_has_valid_scheme)

    def test_missing_mongo_is_clear_error(self) -> None:
        for accessor in (database.get_mongo_client, database.get_database):
            with self.assertRaisesRegex(database.DatabaseConfigurationError, "MONGODB_URI"):
                accessor()
        database.close_mongo_client()

    def test_gemini_sdk_import(self) -> None:
        from google import genai

        self.assertTrue(callable(genai.Client))

    def test_gemini_settings_and_secret_representation(self) -> None:
        # Synthetic sentinel only; no real credentials or network calls.
        sentinel = "unit-test-only-secret"
        with patch.dict("os.environ", {"GEMINI_API_KEY": f" {sentinel} ",
                                     "GEMINI_MODEL": " test-model "}):
            settings = config.get_settings()
            self.assertEqual(settings.gemini_api_key, sentinel)
            self.assertEqual(settings.gemini_model, "test-model")
            self.assertNotIn(sentinel, repr(settings))
            self.assertNotIn(sentinel, str(settings))

    def test_blank_gemini_settings_remain_unset(self) -> None:
        with patch.dict("os.environ", {"GEMINI_API_KEY": "  ", "GEMINI_MODEL": ""}):
            settings = config.get_settings()
            self.assertIsNone(settings.gemini_api_key)
            self.assertIsNone(settings.gemini_model)
            with TestClient(create_app()) as client:
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"status": "ok"})

    def test_lazy_client_reuse_and_close(self) -> None:
        with patch("backend.app.database.get_settings", return_value=config.Settings(
            mongodb_uri="mongodb://localhost:27017", mongodb_db="test_db"
        )), patch("backend.app.database.MongoClient") as constructor:
            client = database.get_mongo_client()
            self.assertIs(database.get_mongo_client(), client)
            database.get_database()
            constructor.assert_called_once_with(
                "mongodb://localhost:27017", connect=False, serverSelectionTimeoutMS=5000
            )
            client.__getitem__.assert_called_once_with("test_db")
            database.close_mongo_client()
            client.close.assert_called_once()
            self.assertIsNone(database._client)

    def test_cors_allows_only_configured_origins(self) -> None:
        with patch.dict("os.environ", {"FRONTEND_URL": "https://frontend.example"}):
            with TestClient(create_app()) as client:
                for origin in ("http://localhost:5173", "https://frontend.example"):
                    response = client.options("/health", headers={
                        "Origin": origin, "Access-Control-Request-Method": "GET"
                    })
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["access-control-allow-origin"], origin)
                response = client.options("/health", headers={
                    "Origin": "https://untrusted.example",
                    "Access-Control-Request-Method": "GET",
                })
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("access-control-allow-origin", response.headers)

    def test_wildcard_frontend_rejected(self) -> None:
        with patch.dict("os.environ", {"FRONTEND_URL": "*"}):
            with self.assertRaisesRegex(ValueError, "FRONTEND_URL"):
                config.get_settings()


if __name__ == "__main__":
    unittest.main(verbosity=2)
