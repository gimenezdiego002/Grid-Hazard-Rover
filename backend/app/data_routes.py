"""Read-only dashboard endpoints using the canonical shared entity models."""

from typing import Annotated, Any, Generic, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError
from pymongo.errors import PyMongoError

from backend.app.database import DatabaseConfigurationError, get_database
from shared.schemas import Hazard, Project, Record


router = APIRouter(prefix="/api/storage", tags=["Mongo storage inspection"])
Entity = TypeVar("Entity", bound=BaseModel)


class Page(BaseModel, Generic[Entity]):
    """Pagination counts scanned database rows, including invalid legacy rows."""

    items: list[Entity]
    count: int
    invalid_count: int
    scanned_count: int
    offset: int
    limit: int
    next_offset: int | None


class ReadOptions(BaseModel):
    limit: int
    offset: int
    dataset: Literal["all", "demo", "real"]


def read_options(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    dataset: Literal["all", "demo", "real"] = "all",
) -> ReadOptions:
    return ReadOptions(limit=limit, offset=offset, dataset=dataset)


def read_database():
    try:
        return get_database()
    except (DatabaseConfigurationError, PyMongoError):
        raise HTTPException(status_code=503, detail="Database unavailable") from None


Database = Annotated[Any, Depends(read_database)]
Options = Annotated[ReadOptions, Depends(read_options)]


def read_page(database, collection: str, model: type[Entity], options: ReadOptions) -> dict:
    query = {}
    if options.dataset != "all":
        # 'real' requires an explicit false flag; unlabeled legacy data is not
        # automatically trusted as sourced data.
        query["metadata.is_fixture"] = options.dataset == "demo"
    try:
        rows = list(
            database[collection].find(query, {"_id": 0})
            .sort([("id", 1), ("_id", 1)])
            .skip(options.offset).limit(options.limit + 1)
        )
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    has_more = len(rows) > options.limit
    scanned = rows[:options.limit]
    items = []
    invalid = 0
    for row in scanned:
        try:
            items.append(model.model_validate(row))
        except ValidationError:
            # Keep a legacy row from breaking the whole map, while exposing
            # that the page is incomplete. Never repair data on a GET request.
            invalid += 1
    return {
        "items": items, "count": len(items), "invalid_count": invalid,
        "scanned_count": len(scanned), "offset": options.offset, "limit": options.limit,
        "next_offset": options.offset + len(scanned) if has_more else None,
    }


def read_item(database, collection: str, model: type[Entity], entity_id: str) -> Entity:
    try:
        row = database[collection].find_one({"id": entity_id}, {"_id": 0})
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    if row is None:
        raise HTTPException(status_code=404, detail="Item not found")
    try:
        return model.model_validate(row)
    except ValidationError:
        raise HTTPException(status_code=409, detail="Stored item does not match the shared schema") from None


@router.get("/projects", response_model=Page[Project])
def projects(database: Database, options: Options):
    return read_page(database, "projects", Project, options)


@router.get("/records", response_model=Page[Record])
def records(database: Database, options: Options):
    return read_page(database, "records", Record, options)


@router.get("/hazards", response_model=Page[Hazard])
def hazards(database: Database, options: Options):
    return read_page(database, "hazards", Hazard, options)


@router.get("/projects/{entity_id}", response_model=Project)
def project(entity_id: str, database: Database):
    return read_item(database, "projects", Project, entity_id)


@router.get("/records/{entity_id}", response_model=Record)
def record(entity_id: str, database: Database):
    return read_item(database, "records", Record, entity_id)


@router.get("/hazards/{entity_id}", response_model=Hazard)
def hazard(entity_id: str, database: Database):
    return read_item(database, "hazards", Hazard, entity_id)
