"""Trusted location-provider boundary; FNK0052 does not invent GPS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from rover.controller import HardwareUnavailable
from rover.config import RobotConfig
from shared.schemas import PointGeometry


class LocationFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: PointGeometry
    captured_at: datetime
    source: str = Field(min_length=1, max_length=100)
    simulated: Annotated[bool, Field(strict=True)]


class LocationProvider(ABC):
    @abstractmethod
    def get_location(self) -> LocationFix: ...


class FixedLocationProvider(LocationProvider):
    """Operator/mission supplied coordinate; nothing is inferred from imagery."""

    def __init__(self, longitude: float, latitude: float, *, source: str, simulated: bool) -> None:
        self.location = PointGeometry(coordinates=(longitude, latitude))
        self.source = source
        self.simulated = simulated

    def get_location(self) -> LocationFix:
        return LocationFix(
            location=self.location,
            captured_at=datetime.now(timezone.utc),
            source=self.source,
            simulated=self.simulated,
        )


class GPSLocationProvider(LocationProvider):
    """Extension point for a future attached GPS module."""

    def get_location(self) -> LocationFix:
        raise HardwareUnavailable("no FNK0052 GPS adapter has been configured or hardware-tested")


def provider_from_config(config: RobotConfig) -> LocationProvider:
    if config.location_mode == "fixed":
        assert config.fixed_longitude is not None and config.fixed_latitude is not None
        return FixedLocationProvider(
            config.fixed_longitude,
            config.fixed_latitude,
            source="operator_fixed_coordinate",
            simulated=config.mode == "mock",
        )
    raise HardwareUnavailable(
        "no trusted location is configured; select fixed mode or implement a tested GPS provider"
    )
