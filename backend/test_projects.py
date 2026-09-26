"""Opt-in canonical Project round-trip against live MongoDB."""

from __future__ import annotations

from datetime import date
import os
import unittest

from backend.app.database import close_mongo_client, get_database
from backend.app.repository import MongoRepository
from shared.schemas import LineStringGeometry, Project


@unittest.skipUnless(
    os.getenv("RUN_LIVE_MONGO_TESTS") == "1" and os.getenv("MONGODB_URI"),
    "Set RUN_LIVE_MONGO_TESTS=1 and MONGODB_URI for live Mongo tests",
)
class MongoProjectSmokeTest(unittest.TestCase):
    project_id = "smoke-test:project:canonical"

    def setUp(self) -> None:
        self.saved = False

    def tearDown(self) -> None:
        if self.saved:
            get_database()["projects"].delete_one({"id": self.project_id})
        close_mongo_client()

    def test_canonical_project_round_trip(self) -> None:
        project = Project(
            id=self.project_id,
            utility="Smoke Test Utility",
            title="Temporary integration test project",
            location=LineStringGeometry(
                coordinates=[(-80.36, 25.76), (-80.35, 25.77)]
            ),
            start_date=date(2027, 1, 1),
            end_date=date(2027, 2, 1),
            metadata={"smoke_test": True},
        )
        repository = MongoRepository()
        repository.save_project(project)
        self.saved = True
        stored = get_database()["projects"].find_one({"id": self.project_id}, {"_id": False})
        self.assertEqual(Project.model_validate(stored), project)


if __name__ == "__main__":
    unittest.main(verbosity=2)
