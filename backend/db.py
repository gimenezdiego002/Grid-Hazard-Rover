import os
from typing import Any
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, GEOSPHERE
from pymongo.database import Database

# 1. Load secret connection string from backend/.env
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB", "grid_hazard_rover")

if not MONGODB_URI:
    raise ValueError("Missing MONGODB_URI in environment variables.")

# 2. Create the MongoDB client connection
client = MongoClient(MONGODB_URI)

# 3. Access our database
db: Database = client[DB_NAME]

# 4. Access each collection
projects_collection = db["projects"]
records_collection = db["records"]          # FDOT / Miami-Dade public infrastructure records
hazards_collection = db["hazards"]          # Rover hazards
risk_signals_collection = hazards_collection # Alias for teammate convenience
risk_zones_collection = db["risk_zones"]     # Risk areas / cells
missions_collection = db["missions"]        # Rover inspection missions


def _to_dict(item: Any) -> dict:
    """Helper: converts Pydantic schema objects or dicts into a plain dictionary."""
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return dict(item)


def setup_indexes():
    """Sets up database rules (indexes) so queries are fast and duplicates are prevented."""
    print("⚙️  Setting up MongoDB collections and indexes...")

    # Projects: prevent duplicates by (source + sourceId) or id, and add 2dsphere
    projects_collection.create_index(
        [("source", ASCENDING), ("sourceId", ASCENDING)],
        unique=True,
        sparse=True
    )
    projects_collection.create_index("id", unique=True, sparse=True)
    projects_collection.create_index([("location", GEOSPHERE)])
    print("  ✓ Indexes created for 'projects'")

    # Records: (FDOT / Miami-Dade) prevent duplicates and add 2dsphere
    records_collection.create_index("id", unique=True, sparse=True)
    records_collection.create_index([("location", GEOSPHERE)])
    print("  ✓ Indexes created for 'records'")

    # Hazards / Risk Signals: 2dsphere on location
    hazards_collection.create_index("id", unique=True, sparse=True)
    hazards_collection.create_index([("location", GEOSPHERE)])
    print("  ✓ Indexes created for 'hazards' / 'risk_signals'")

    # Risk Zones & Missions
    risk_zones_collection.create_index("id", unique=True, sparse=True)
    risk_zones_collection.create_index([("location", GEOSPHERE)])
    missions_collection.create_index("id", unique=True, sparse=True)
    print("  ✓ Indexes created for 'risk_zones' and 'missions'")

    print("🎉 All collections and indexes are fully configured!")


# ---------------------------------------------------------
# INGESTION HELPERS: Projects
# ---------------------------------------------------------

def save_project(project_data: Any) -> dict:
    """
    Saves a project to MongoDB using an 'upsert' (update if exists, insert if new).
    Prevents duplicates by checking source + sourceId (or id).
    Accepts either a Python dict or a Pydantic Project object.
    """
    doc = _to_dict(project_data)
    source = doc.get("source")
    source_id = doc.get("sourceId")

    if source and source_id:
        filter_query = {"source": source, "sourceId": source_id}
    elif "id" in doc:
        filter_query = {"id": doc["id"]}
    else:
        result = projects_collection.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc

    projects_collection.update_one(filter_query, {"$set": doc}, upsert=True)
    return doc


def save_projects_batch(projects_list: list[Any]) -> int:
    """Saves a batch/list of projects. Returns the number of projects saved."""
    count = 0
    for p in projects_list:
        save_project(p)
        count += 1
    return count


def get_all_projects() -> list[dict]:
    """Retrieves all stored projects (excluding internal MongoDB '_id' for clean JSON)."""
    return list(projects_collection.find({}, {"_id": 0}))


def find_projects_near(longitude: float, latitude: float, max_distance_meters: float = 1000) -> list[dict]:
    """
    Finds all projects within max_distance_meters of a [longitude, latitude] coordinate.
    Default search radius is 1000 meters (1 kilometer).
    """
    query = {
        "location": {
            "$near": {
                "$geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude]
                },
                "$maxDistance": max_distance_meters
            }
        }
    }
    return list(projects_collection.find(query, {"_id": 0}))


# ---------------------------------------------------------
# INGESTION HELPERS: Records, Hazards, Zones, Missions
# ---------------------------------------------------------

def save_record(record_data: Any) -> dict:
    """Saves an external public record (FDOT, Miami-Dade, etc.) without duplicates."""
    doc = _to_dict(record_data)
    filter_query = {"id": doc["id"]} if "id" in doc else {"source": doc.get("source"), "sourceId": doc.get("sourceId")}
    records_collection.update_one(filter_query, {"$set": doc}, upsert=True)
    return doc


def save_records_batch(records_list: list[Any]) -> int:
    """Saves a batch of records. Returns the count saved."""
    count = 0
    for r in records_list:
        save_record(r)
        count += 1
    return count


def save_hazard(hazard_data: Any) -> dict:
    """Saves a rover hazard observation or risk signal."""
    doc = _to_dict(hazard_data)
    if "id" in doc:
        hazards_collection.update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)
    else:
        hazards_collection.insert_one(doc)
    return doc

# Alias: save_risk_signal works identically to save_hazard
save_risk_signal = save_hazard


def save_risk_zone(zone_data: Any) -> dict:
    """Saves a calculated risk zone or cell."""
    doc = _to_dict(zone_data)
    if "id" in doc:
        risk_zones_collection.update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)
    else:
        risk_zones_collection.insert_one(doc)
    return doc


def save_mission(mission_data: Any) -> dict:
    """Saves a rover inspection mission."""
    doc = _to_dict(mission_data)
    if "id" in doc:
        missions_collection.update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)
    else:
        missions_collection.insert_one(doc)
    return doc


if __name__ == "__main__":
    setup_indexes()
