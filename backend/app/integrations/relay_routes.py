"""HTTP boundary for reviewed Relay-to-Grid conversions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from starlette.concurrency import run_in_threadpool

from backend.app.integrations.relay_adapter import (
    RelayHazardCandidate,
    relay_candidate_to_hazard,
)
from backend.app.repository import Repository, get_repository
from shared.schemas import Hazard


router = APIRouter(prefix="/api/integrations/relay", tags=["relay-integration"])


@router.post("/hazards", response_model=Hazard, status_code=status.HTTP_201_CREATED)
async def accept_reviewed_relay_hazard(
    candidate: RelayHazardCandidate,
    repository: Annotated[Repository, Depends(get_repository)],
) -> Hazard:
    """Persist an explicitly reviewed finding using trusted field metadata."""

    hazard = relay_candidate_to_hazard(candidate)
    await run_in_threadpool(repository.save_hazard, hazard)
    return hazard
