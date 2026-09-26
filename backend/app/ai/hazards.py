"""Deterministic conversion from an AI observation to a canonical Hazard."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.app.ai.schemas import HazardClassification
from shared.schemas import Hazard, PointGeometry


def classification_to_hazard(
    classification: HazardClassification,
    *,
    longitude: float,
    latitude: float,
    timestamp: datetime,
    source: str | None = None,
    image_url: str | None = None,
    hazard_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Hazard | None:
    """Attach trusted request metadata; a no-detection result stays ``None``."""
    if not classification.hazard_detected:
        return None
    assert classification.hazard_type is not None
    assert classification.severity is not None
    details = dict(metadata or {})
    if source:
        details["source"] = source
    details["classification_provider"] = "gemini"
    return Hazard(
        id=hazard_id or f"hazard-{uuid4().hex}",
        hazard_type=classification.hazard_type,
        severity=classification.severity,
        confidence=classification.confidence,
        description=classification.description,
        location=PointGeometry(coordinates=(longitude, latitude)),
        timestamp=timestamp,
        image_url=image_url,
        metadata=details,
    )
