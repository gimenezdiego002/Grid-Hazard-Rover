"""Data access boundary with an offline demo store and optional lazy MongoDB."""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol, TypeVar

from pymongo import ASCENDING, GEOSPHERE

from backend.app.config import get_settings
from backend.app.database import get_database
from backend.app.demo_data import demo_hazards, demo_projects, demo_records
from shared.schemas import Hazard, Match, Project, Record, RiskCell

ModelT = TypeVar("ModelT", Project, Record, Hazard, Match, RiskCell)


class Repository(Protocol):
    def list_projects(self) -> list[Project]: ...
    def list_records(self) -> list[Record]: ...
    def list_hazards(self) -> list[Hazard]: ...
    def save_project(self, project: Project) -> None: ...
    def save_record(self, record: Record) -> None: ...
    def save_hazard(self, hazard: Hazard) -> None: ...
    def save_analysis(self, matches: list[Match], risk_cells: list[RiskCell]) -> None: ...


class MemoryRepository:
    """Process-local demo store used whenever MongoDB is not configured."""

    def __init__(
        self,
        projects: list[Project] | None = None,
        records: list[Record] | None = None,
        hazards: list[Hazard] | None = None,
    ) -> None:
        self._projects = list(projects if projects is not None else demo_projects())
        self._records = list(records if records is not None else demo_records())
        self._hazards = list(hazards if hazards is not None else demo_hazards())

    def list_projects(self) -> list[Project]:
        return list(self._projects)

    def list_records(self) -> list[Record]:
        return list(self._records)

    def list_hazards(self) -> list[Hazard]:
        return list(self._hazards)

    def save_hazard(self, hazard: Hazard) -> None:
        self._hazards = [item for item in self._hazards if item.id != hazard.id]
        self._hazards.append(hazard)

    def save_project(self, project: Project) -> None:
        self._projects = [item for item in self._projects if item.id != project.id]
        self._projects.append(project)

    def save_record(self, record: Record) -> None:
        self._records = [item for item in self._records if item.id != record.id]
        self._records.append(record)

    def save_analysis(self, matches: list[Match], risk_cells: list[RiskCell]) -> None:
        # Analysis is derived on demand in memory; validate that callers supplied
        # canonical objects without maintaining a second source of truth.
        for item in matches:
            Match.model_validate(item)
        for item in risk_cells:
            RiskCell.model_validate(item)


class MongoRepository:
    """Canonical-model repository; connections and indexes are created lazily."""

    model_collections = {
        "projects": Project,
        "records": Record,
        "hazards": Hazard,
        "matches": Match,
        "risk_cells": RiskCell,
    }

    def __init__(self) -> None:
        self._indexed = False

    def ensure_indexes(self) -> None:
        if self._indexed:
            return
        database = get_database()
        for name in self.model_collections:
            database[name].create_index([("id", ASCENDING)], unique=True, name="id_unique")
        for name in ("projects", "records", "hazards", "risk_cells"):
            database[name].create_index([("location", GEOSPHERE)], name="location_2dsphere")
        self._indexed = True

    def _list(self, name: str, model: type[ModelT]) -> list[ModelT]:
        self.ensure_indexes()
        documents = get_database()[name].find({}, {"_id": False}).sort("id", ASCENDING)
        return [model.model_validate(document) for document in documents]

    def list_projects(self) -> list[Project]:
        return self._list("projects", Project)

    def list_records(self) -> list[Record]:
        return self._list("records", Record)

    def list_hazards(self) -> list[Hazard]:
        return self._list("hazards", Hazard)

    def save_hazard(self, hazard: Hazard) -> None:
        self._save("hazards", hazard)

    def save_project(self, project: Project) -> None:
        self._save("projects", project)

    def save_record(self, record: Record) -> None:
        self._save("records", record)

    def _save(self, collection: str, model: ModelT) -> None:
        self.ensure_indexes()
        get_database()[collection].replace_one(
            {"id": model.id}, model.model_dump(mode="json"), upsert=True
        )

    def save_analysis(self, matches: list[Match], risk_cells: list[RiskCell]) -> None:
        self.ensure_indexes()
        for name, models in (("matches", matches), ("risk_cells", risk_cells)):
            collection = get_database()[name]
            for model in models:
                collection.replace_one(
                    {"id": model.id}, model.model_dump(mode="json"), upsert=True
                )


@lru_cache(maxsize=1)
def get_repository() -> Repository:
    settings = get_settings()
    return MongoRepository() if settings.mongodb_uri_has_valid_scheme else MemoryRepository()


def clear_repository_cache() -> None:
    get_repository.cache_clear()
