"""Offline data repository checks; no live MongoDB is required."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.demo_data import demo_hazards
from backend.app.repository import MemoryRepository, MongoRepository
from backend.app.demo_data import demo_projects


class RepositoryTests(unittest.TestCase):
    def test_memory_repository_replaces_same_hazard_id(self) -> None:
        hazard = demo_hazards()[0]
        repository = MemoryRepository(projects=[], records=[], hazards=[])
        repository.save_hazard(hazard)
        repository.save_hazard(hazard)
        self.assertEqual(repository.list_hazards(), [hazard])

    def test_mongo_indexes_and_upsert_are_lazy_and_mocked(self) -> None:
        database = MagicMock()
        collections = {
            name: MagicMock(name=name)
            for name in ("projects", "records", "hazards", "matches", "risk_cells")
        }
        database.__getitem__.side_effect = collections.__getitem__
        repository = MongoRepository()
        hazard = demo_hazards()[0]
        with patch("backend.app.repository.get_database", return_value=database):
            repository.save_hazard(hazard)
            repository.ensure_indexes()
        for name in ("projects", "records", "hazards", "matches", "risk_cells"):
            expected = 1 if name == "matches" else 2
            self.assertEqual(collections[name].create_index.call_count, expected)
        collections["hazards"].replace_one.assert_called_once()
        args, kwargs = collections["hazards"].replace_one.call_args
        self.assertEqual(args[0], {"id": hazard.id})
        self.assertEqual(args[1]["location"]["coordinates"], [-80.3521, 25.7652])
        self.assertTrue(kwargs["upsert"])

    def test_mongo_lists_only_canonical_rows(self) -> None:
        database = MagicMock()
        collection = MagicMock()
        database.__getitem__.return_value = collection
        cursor = MagicMock()
        collection.find.return_value = cursor
        valid = demo_projects()[0].model_dump(mode="json")
        cursor.sort.return_value = [{"sourceId": "legacy", "name": "old"}, valid]
        repository = MongoRepository()
        with patch.object(repository, "ensure_indexes"), patch(
            "backend.app.repository.get_database", return_value=database
        ):
            projects = repository.list_projects()
        self.assertEqual(projects, [demo_projects()[0]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
