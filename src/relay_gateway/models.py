"""Small, integer-based event contract suitable for Pollard identities."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MissionBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_requests: int = Field(default=3, ge=0, le=100)
    max_tokens: int = Field(default=6000, ge=0, le=200_000)
    max_usd: Decimal = Field(default=Decimal("0.10"), ge=0, le=15)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=128)
    robot_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(default="water", min_length=1, max_length=40)
    value_milli: int | None = None
    unit: str | None = Field(default=None, max_length=40)
    evidence_uri: str | None = Field(default=None, max_length=1024)
    simulated: bool = True
    timestamp_seconds: int = Field(default=0, ge=0)
    ground_truth_hazard: bool | None = None

    def evidence(self) -> dict:
        # Evaluation labels must never be visible to the inference provider.
        return self.model_dump(exclude={"ground_truth_hazard"})


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(min_length=1, max_length=128)
    station_id: str = Field(min_length=1, max_length=128)
    observations: list[Observation] = Field(min_length=1, max_length=100)
    budget: MissionBudget = Field(default_factory=MissionBudget)
    scenario_id: str | None = None
    version: str | int = 1
    simulated: bool = True
    duration_seconds: int | None = Field(default=None, ge=0)
    evaluation: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def distinct_events(self):
        event_ids = [event.event_id for event in self.observations]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event_id must be unique within a scenario")
        times = [event.timestamp_seconds for event in self.observations]
        if times != sorted(times):
            raise ValueError("observations must be in timestamp order")
        return self


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["suspected_hazard", "clear", "needs_review"]
    hazard_type: str | None = Field(default=None, max_length=80)
    confidence_milli: int = Field(ge=0, le=1000)
    summary: str = Field(max_length=500)
    recommended_action: str = Field(max_length=300)
    cited_reference_ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=5)


class ReferenceDocument(BaseModel):
    """Bounded retrieved data. These fields never become system instructions."""
    model_config = ConfigDict(extra="forbid")
    reference_id: str = Field(min_length=1, max_length=128)
    hazard_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    source_url: str = Field(max_length=2048)
    is_simulated: bool


def normalize_reference_context(documents: list[dict | ReferenceDocument] | None) -> list[dict]:
    if documents is None:
        return []
    if not isinstance(documents, list) or len(documents) > 5:
        raise ValueError("reference_context must contain at most five documents")
    validated = [ReferenceDocument.model_validate(document).model_dump() for document in documents]
    ids = [document["reference_id"] for document in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("reference_id must be unique within reference_context")
    return validated


class MissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Scenario
    strategy: Literal["economy", "baseline"] = "economy"


def default_scenario() -> Scenario:
    return Scenario(
        mission_id="leak-demo", station_id="station-a",
        observations=[
            Observation(event_id="dry-1", robot_id="station-a", value_milli=0,
                        unit="wetness", ground_truth_hazard=False),
            Observation(event_id="water-1", robot_id="station-a", value_milli=1000,
                        unit="wetness", timestamp_seconds=10, ground_truth_hazard=True),
            Observation(event_id="water-2", robot_id="station-a", value_milli=1000,
                        unit="wetness", timestamp_seconds=20, ground_truth_hazard=True),
        ],
    )
