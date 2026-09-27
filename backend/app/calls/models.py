"""Validated, privacy-conscious records derived from completed voice calls."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


NonEmpty = Annotated[str, Field(min_length=1, max_length=2_000, pattern=r"\S")]


class CallModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallUrgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EMERGENCY = "emergency"


class ReviewStatus(str, Enum):
    NEW = "new"
    IN_REVIEW = "in_review"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class RecordingStatus(str, Enum):
    NOT_AVAILABLE = "not_available"
    PROVIDER_RETAINED = "provider_retained"
    LOCAL_SAVED = "local_saved"


class TranscriptTurn(CallModel):
    role: Literal["agent", "user", "unknown"]
    message: Annotated[str, Field(max_length=20_000)]
    time_in_call_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


class CallAnalysis(CallModel):
    summary: Annotated[str, Field(max_length=10_000)] = ""
    category: Annotated[str, Field(max_length=100)] = "general_feedback"
    sentiment: Annotated[str, Field(max_length=100)] = "unknown"
    urgency: CallUrgency = CallUrgency.MEDIUM
    call_successful: bool | None = None
    location_text: Annotated[str, Field(max_length=500)] | None = None
    action_items: list[Annotated[str, Field(max_length=1_000)]] = Field(
        default_factory=list, max_length=20
    )


class CallReport(CallModel):
    conversation_id: NonEmpty
    agent_id: NonEmpty
    agent_name: Annotated[str, Field(max_length=200)] | None = None
    company_id: Annotated[str, Field(max_length=200)] | None = None
    company_name: Annotated[str, Field(max_length=200)] | None = None
    ended_at: datetime
    duration_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list, max_length=1_000)
    analysis: CallAnalysis
    has_audio: bool = False
    recording_status: RecordingStatus = RecordingStatus.NOT_AVAILABLE
    audio_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    consent_to_record: bool | None = None
    review_status: ReviewStatus = ReviewStatus.NEW
    reviewer_note: Annotated[str, Field(max_length=2_000)] | None = None
    source: Literal["elevenlabs"] = "elevenlabs"


class CallReportSummary(CallModel):
    """Company dashboard shape intentionally omits the full transcript."""

    conversation_id: str
    company_id: str | None
    company_name: str | None
    ended_at: datetime
    duration_seconds: float | None
    analysis: CallAnalysis
    recording_status: RecordingStatus
    consent_to_record: bool | None
    review_status: ReviewStatus


class ReviewUpdate(CallModel):
    status: ReviewStatus
    note: Annotated[str, Field(max_length=2_000)] | None = None

