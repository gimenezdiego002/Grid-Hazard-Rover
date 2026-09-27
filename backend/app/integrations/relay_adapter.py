"""Reviewed conversion from Relay findings to canonical Grid hazards.

Relay findings are provisional model output. They intentionally do not contain
trusted geography, wall-clock time, or Grid severity. This adapter requires
those values from the caller instead of fabricating them.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from relay_gateway.models import Finding
from shared.schemas import Hazard, PointGeometry


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"\S")]


class RelayHazardCandidate(BaseModel):
    """A reviewed Relay finding plus the trusted facts Relay does not infer."""

    model_config = ConfigDict(extra="forbid")

    finding: Finding
    event_id: Identifier
    mission_id: Identifier
    robot_id: Identifier
    location: PointGeometry
    timestamp: datetime
    severity: Annotated[int, Field(strict=True, ge=1, le=5)]
    reviewed: Literal[True]
    simulated: Annotated[bool, Field(strict=True)]
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    image_url: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_conversion_preconditions(self) -> "RelayHazardCandidate":
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        if self.finding.status != "suspected_hazard":
            raise ValueError("only a suspected_hazard finding can become a Hazard")
        if not self.finding.hazard_type or not self.finding.hazard_type.strip():
            raise ValueError("suspected hazard finding must include hazard_type")
        return self


def relay_candidate_to_hazard(candidate: RelayHazardCandidate) -> Hazard:
    """Create one stable canonical Hazard without deriving trusted facts."""

    identity = "\x1f".join(
        (candidate.mission_id, candidate.robot_id, candidate.event_id)
    ).encode("utf-8")
    hazard_id = f"relay-{sha256(identity).hexdigest()[:32]}"
    metadata: dict[str, object] = {
        "source": "relay",
        "relay_event_id": candidate.event_id,
        "relay_mission_id": candidate.mission_id,
        "relay_robot_id": candidate.robot_id,
        "relay_finding_status": candidate.finding.status,
        "relay_recommended_action": candidate.finding.recommended_action,
        "relay_reference_ids": list(candidate.finding.cited_reference_ids),
        "reviewed": True,
        "simulated": candidate.simulated,
    }
    if candidate.evidence_ref is not None:
        metadata["relay_evidence_ref"] = candidate.evidence_ref

    return Hazard(
        id=hazard_id,
        hazard_type=candidate.finding.hazard_type,
        severity=candidate.severity,
        confidence=candidate.finding.confidence_milli / 1000,
        description=candidate.finding.summary or None,
        location=candidate.location,
        timestamp=candidate.timestamp,
        image_url=candidate.image_url,
        metadata=metadata,
    )
