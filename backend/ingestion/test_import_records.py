"""Offline import tests; no database credentials or remote calls."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from .import_records import import_records, load_records
from .normalize import normalize_snapshot
from .test_ingestion import fdot_snapshot


class ImportTests(unittest.TestCase):
    def export(self, path, *, fixture=False):
        snapshot = fdot_snapshot()
        snapshot["is_fixture"] = fixture
        result = normalize_snapshot(snapshot)
        for name, value in result.items():
            (path / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
        return result

    def test_valid_export_deduplicates_before_connecting(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.export(path)
            rows = load_records([path, path])
            self.assertEqual(len(rows), 1)

    def test_fixture_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.export(path, fixture=True)
            with self.assertRaisesRegex(ValueError, "Fixture"):
                load_records([path])

    def test_tampered_counts_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.export(path)
            (path / "records.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "counts"):
                load_records([path])

    def test_upsert_then_repeat_without_duplicates(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.export(path)
            rows = load_records([path])
        database = MagicMock()
        collection = database.__getitem__.return_value
        database.list_collection_names.return_value = []
        collection.find_one.return_value = rows[0]
        collection.update_one.side_effect = [
            SimpleNamespace(upserted_id="new", matched_count=0, modified_count=0),
            SimpleNamespace(upserted_id=None, matched_count=1, modified_count=0),
        ]
        first = import_records(database, rows)
        second = import_records(database, rows)
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["verified"], 1)
        collection.update_one.assert_called_with({"id": rows[0]["id"]}, {"$set": rows[0]}, upsert=True)
        collection.delete_many.assert_not_called()

    def test_incompatible_index_prevents_writes(self):
        database = MagicMock()
        database.list_collection_names.return_value = ["records"]
        collection = database.__getitem__.return_value
        collection.list_indexes.return_value = [{"key": {"id": 1}, "unique": False}]
        with self.assertRaisesRegex(ValueError, "not unique"):
            import_records(database, [{"id": "test"}])
        collection.update_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
