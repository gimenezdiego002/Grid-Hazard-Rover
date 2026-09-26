"""Backward-compatible lazy database helpers.

New code should use :mod:`backend.app.repository`. This module deliberately
creates no client or collection at import time so FastAPI and tests work without
MongoDB configuration.
"""

from __future__ import annotations

from typing import Any

from backend.app.database import get_database
from backend.app.repository import MongoRepository
from shared.schemas import Hazard, PointGeometry, Project, Record, RiskCell


def setup_indexes() -> None:
    MongoRepository().ensure_indexes()


def save_project(project_data: Any) -> dict:
    project = Project.model_validate(project_data)
    MongoRepository().save_project(project)
    return project.model_dump(mode="json")


def save_projects_batch(projects_list: list[Any]) -> int:
    repository = MongoRepository()
    for payload in projects_list:
        repository.save_project(Project.model_validate(payload))
    return len(projects_list)


def get_all_projects() -> list[dict]:
    return [item.model_dump(mode="json") for item in MongoRepository().list_projects()]


def find_projects_near(
    longitude: float, latitude: float, max_distance_meters: float = 1000
) -> list[dict]:
    point = PointGeometry(coordinates=(longitude, latitude))
    query = {"location": {"$near": {
        "$geometry": point.model_dump(mode="json"),
        "$maxDistance": max_distance_meters,
    }}}
    return list(get_database()["projects"].find(query, {"_id": False}))


def save_record(record_data: Any) -> dict:
    record = Record.model_validate(record_data)
    MongoRepository().save_record(record)
    return record.model_dump(mode="json")


def save_records_batch(records_list: list[Any]) -> int:
    repository = MongoRepository()
    for payload in records_list:
        repository.save_record(Record.model_validate(payload))
    return len(records_list)


def save_hazard(hazard_data: Any) -> dict:
    hazard = Hazard.model_validate(hazard_data)
    MongoRepository().save_hazard(hazard)
    return hazard.model_dump(mode="json")


save_risk_signal = save_hazard


def save_risk_zone(zone_data: Any) -> dict:
    cell = RiskCell.model_validate(zone_data)
    repository = MongoRepository()
    repository.ensure_indexes()
    get_database()["risk_cells"].replace_one(
        {"id": cell.id}, cell.model_dump(mode="json"), upsert=True
    )
    return cell.model_dump(mode="json")


def save_mission(mission_data: Any) -> dict:
    """Preserve the teammate's untyped mission hook without eager globals."""
    document = dict(mission_data)
    if "id" not in document:
        raise ValueError("Mission requires an id")
    collection = get_database()["missions"]
    collection.create_index("id", unique=True)
    collection.replace_one({"id": document["id"]}, document, upsert=True)
    return document
