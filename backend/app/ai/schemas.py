"""Small Gemini response contract, not a stored Hazard or risk score.

Coordinates, timestamps, IDs and image references come from the caller later.
No-detection results must not be turned into canonical Hazard entities.
Cross-field consistency is enforced locally after parsing model output.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


HazardType: TypeAlias = Literal[
    "vegetation_encroachment",
    "fallen_branch",
    "debris_obstruction",
    "damaged_pole",
    "leaning_pole",
    "damaged_utility_equipment",
    "exposed_or_damaged_infrastructure",
    "blocked_access",
    "flooding_standing_water",
    "construction_obstruction",
    "other_visible_hazard",
]


class HazardClassification(BaseModel):
    """One visible hazard or no visible hazard; never a guarantee of safety.

    Confidence is the model's self-reported confidence in its classification,
    including no detection. It is not a calibrated probability. Severity is
    an image-based assessment and is unrelated to the Coordination Risk Index.
    """

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    hazard_detected: bool = Field(
        description="Whether the image provides visible evidence of a hazard."
    )
    hazard_type: HazardType | None = Field(
        description="Visible hazard category, or null when no hazard is detected."
    )
    severity: Annotated[int, Field(ge=1, le=5)] | None = Field(
        description="Severity from 1 (minor) to 5 (critical); null for no detection."
    )
    confidence: Annotated[float, Field(ge=0, le=1)] = Field(
        description="Self-reported confidence in the classification, from 0 to 1."
    )
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ] = Field(
        description="Short visible evidence or explanation of no detection; no speculation."
    )

    @model_validator(mode="after")
    def validate_detection(self) -> Self:
        if self.hazard_detected:
            if self.hazard_type is None or self.severity is None:
                raise ValueError("Detected hazards require hazard_type and severity")
        elif self.hazard_type is not None or self.severity is not None:
            raise ValueError("No-hazard results require null hazard_type and severity")
        return self
