"""HTTP contracts for photo ingestion and frontend-readable canonical data."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from backend.app.ai.classifier import (
    MAX_IMAGE_BYTES,
    ClassificationResponseError,
    GeminiConfigurationError,
    GeminiRequestError,
    GeminiTimeoutError,
    ImageInputError,
    classify_hazard,
)
from backend.app.ai.hazards import classification_to_hazard
from backend.app.api_models import DemoSummary, PhotoIngestResponse
from backend.app.matching import generate_matches
from backend.app.repository import Repository, get_repository
from backend.app.risk import generate_risk_grid
from shared.schemas import Hazard, Match, Project, Record, RiskCell

router = APIRouter()


def _snapshot(repository: Repository) -> DemoSummary:
    projects = repository.list_projects()
    records = repository.list_records()
    hazards = repository.list_hazards()
    matches = generate_matches(projects, records, hazards)
    risk_cells = generate_risk_grid(matches, records, hazards)
    return DemoSummary(
        projects=projects, records=records, hazards=hazards,
        matches=matches, risk_cells=risk_cells,
    )


@router.get("/api/projects", response_model=list[Project], tags=["coordination"])
def list_projects(repository: Annotated[Repository, Depends(get_repository)]) -> list[Project]:
    return repository.list_projects()


@router.get("/api/records", response_model=list[Record], tags=["coordination"])
def list_records(repository: Annotated[Repository, Depends(get_repository)]) -> list[Record]:
    return repository.list_records()


@router.get("/api/hazards", response_model=list[Hazard], tags=["hazards"])
def list_hazards(repository: Annotated[Repository, Depends(get_repository)]) -> list[Hazard]:
    return repository.list_hazards()


@router.get("/api/matches", response_model=list[Match], tags=["coordination"])
def list_matches(repository: Annotated[Repository, Depends(get_repository)]) -> list[Match]:
    snapshot = _snapshot(repository)
    return snapshot.matches


@router.get("/api/risk-grid", response_model=list[RiskCell], tags=["coordination"])
def list_risk_grid(repository: Annotated[Repository, Depends(get_repository)]) -> list[RiskCell]:
    snapshot = _snapshot(repository)
    return snapshot.risk_cells


@router.get("/api/demo-summary", response_model=DemoSummary, tags=["coordination"])
def demo_summary(repository: Annotated[Repository, Depends(get_repository)]) -> DemoSummary:
    return _snapshot(repository)


@router.post(
    "/ingest/photo",
    response_model=PhotoIngestResponse,
    status_code=status.HTTP_200_OK,
    tags=["hazards"],
)
async def ingest_photo(
    image: Annotated[UploadFile, File(description="A JPEG rover or mock-rover photo")],
    longitude: Annotated[float, Form(ge=-180, le=180)],
    latitude: Annotated[float, Form(ge=-90, le=90)],
    timestamp: Annotated[datetime, Form()],
    repository: Annotated[Repository, Depends(get_repository)],
    source: Annotated[str | None, Form(max_length=100)] = None,
) -> PhotoIngestResponse:
    if image.content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(status_code=415, detail="Only JPEG uploads are supported.")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise HTTPException(status_code=422, detail="timestamp must include a UTC offset")
    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    try:
        classification = await run_in_threadpool(classify_hazard, image_bytes)
    except ImageInputError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except GeminiConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except GeminiTimeoutError as error:
        raise HTTPException(status_code=504, detail=str(error)) from None
    except (GeminiRequestError, ClassificationResponseError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from None

    hazard = classification_to_hazard(
        classification,
        longitude=longitude,
        latitude=latitude,
        timestamp=timestamp,
        source=source,
    )
    if hazard is not None:
        await run_in_threadpool(repository.save_hazard, hazard)
    return PhotoIngestResponse(
        hazard_detected=classification.hazard_detected,
        classification=classification,
        hazard=hazard,
        persisted=hazard is not None,
    )
