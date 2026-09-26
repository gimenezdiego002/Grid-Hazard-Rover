"""Validate FDOT exports, then optionally upsert only their records into MongoDB."""

import argparse
import json
from pathlib import Path

from pymongo.errors import PyMongoError
from shapely.geometry import shape

from backend.app.database import close_mongo_client, get_database
from shared.schemas import Record


def load_records(directories: list[Path]) -> list[dict]:
    """Validate every input before making a database connection or writing."""
    unique = {}
    for directory in directories:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        records = json.loads((directory / "records.json").read_text(encoding="utf-8"))
        projects = json.loads((directory / "projects.json").read_text(encoding="utf-8"))
        rejected = json.loads((directory / "rejected.json").read_text(encoding="utf-8"))
        source = manifest.get("source")
        if source not in ("fdot_active", "fdot_work_program"):
            raise ValueError("This importer accepts only FDOT record exports")
        if manifest.get("is_fixture") is not False:
            raise ValueError("Fixture or unlabeled exports cannot be imported")
        if manifest.get("complete_for_selection") is not True:
            raise ValueError("Incomplete source snapshot")
        if not isinstance(records, list) or projects != [] or not isinstance(rejected, list):
            raise ValueError("Expected record-only export arrays")
        if manifest.get("accepted") != len(records) or manifest.get("rejected") != len(rejected):
            raise ValueError("Manifest counts do not match exported arrays")
        duplicates = manifest.get("duplicates")
        if type(duplicates) is not int or duplicates < 0:
            raise ValueError("Invalid duplicate count")
        if len(records) + len(rejected) + duplicates != manifest.get("selected_count"):
            raise ValueError("Manifest input counts do not reconcile")
        for payload in records:
            record = Record.model_validate(payload)
            if record.metadata.get("is_fixture") is not False or record.metadata.get("source") != source:
                raise ValueError("Record source/fixture metadata disagrees with manifest")
            if not record.id.startswith(source + ":") or record.source != "FDOT":
                raise ValueError("Record does not have the expected FDOT identity")
            geometry = shape(record.location.model_dump(mode="json"))
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError("Record geometry is empty or invalid")
            doc = record.model_dump(mode="json")
            if doc["id"] in unique and unique[doc["id"]] != doc:
                raise ValueError("Conflicting records have the same ID")
            unique[doc["id"]] = doc
    return [unique[key] for key in sorted(unique)]


def import_records(database, records: list[dict]) -> dict:
    """No deletes or collection replacement. A failed run can be retried by ID."""
    database.command("ping")
    collection = database["records"]
    if not records:
        return {"requested": 0, "inserted": 0, "matched": 0, "modified": 0, "verified": 0}
    if "records" in database.list_collection_names():
        indexes = list(collection.list_indexes())
    else:
        indexes = []
    id_indexes = [i for i in indexes if list(i["key"].items()) == [("id", 1)]]
    if id_indexes and not any(i.get("unique") for i in id_indexes):
        raise ValueError("Existing records.id index is not unique; resolve it before import")
    if not id_indexes:
        collection.create_index("id", unique=True, sparse=True)
    if not any(list(i["key"].items()) == [("location", "2dsphere")] for i in indexes):
        collection.create_index([("location", "2dsphere")])
    stats = {"requested": len(records), "inserted": 0, "matched": 0, "modified": 0, "verified": 0}
    for doc in records:
        result = collection.update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)
        stats["inserted"] += int(result.upserted_id is not None)
        stats["matched"] += result.matched_count
        stats["modified"] += result.modified_count
    for expected in records:
        actual = collection.find_one({"id": expected["id"]}, {"_id": 0})
        # Preserve unrelated existing fields, but verify every canonical field.
        canonical = {key: actual[key] for key in expected if actual and key in actual}
        if Record.model_validate(canonical).model_dump(mode="json") != expected:
            raise ValueError("Database readback differs from the export; import may be partial")
        stats["verified"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write accepted real records; default validates offline only")
    args = parser.parse_args()
    try:
        records = load_records(args.exports)
        if not args.apply:
            print(f"Validated {len(records)} unique real FDOT records. No database connection or writes.")
            return 0
        print(json.dumps(import_records(get_database(), records), indent=2))
        return 0
    except (PyMongoError, OSError, ValueError, RuntimeError) as exc:
        # Driver exceptions may contain URIs/hosts. Never print their raw text.
        print(f"Import failed ({type(exc).__name__}). No rows are deleted; a write-stage failure may leave a partial import. Retry by ID after fixing the cause.")
        return 1
    finally:
        close_mongo_client()


if __name__ == "__main__":
    raise SystemExit(main())
