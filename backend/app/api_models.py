"""Backend-only request/response envelopes; canonical entities stay in shared."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.app.ai.schemas import HazardClassification
from shared.schemas import Hazard, Match, Project, Record, RiskCell


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhotoIngestResponse(ApiModel):
    hazard_detected: bool
    classification: HazardClassification
    hazard: Hazard | None
    persisted: bool


class DemoSummary(ApiModel):
    projects: list[Project]
    records: list[Record]
    hazards: list[Hazard]
    matches: list[Match]
    risk_cells: list[RiskCell]
