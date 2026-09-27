"""Environment-backed FNK0052 configuration without secret values."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal

from shared.schemas import PointGeometry


def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class RobotConfig:
    mode: Literal["mock", "freenove"] = "mock"
    robot_id: str = "freenove-fnk0052-01"
    allow_physical_actuation: bool = False
    freenove_server_path: Path | None = None
    backend_url: str = "http://127.0.0.1:8000"
    relay_url: str = "http://127.0.0.1:8000/relay/fleet"
    location_mode: Literal["none", "fixed"] = "none"
    fixed_longitude: float | None = None
    fixed_latitude: float | None = None
    navigation_enabled: bool = False
    obstacle_distance_cm: float = 30.0
    sensor_max_age_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "RobotConfig":
        mode = os.getenv("ROBOT_MODE", "mock").strip().lower()
        if mode not in {"mock", "freenove"}:
            raise ValueError("ROBOT_MODE must be mock or freenove")
        vendor = os.getenv("ROBOT_FREENOVE_SERVER_PATH", "").strip()
        obstacle = float(os.getenv("ROBOT_OBSTACLE_DISTANCE_CM", "30"))
        max_age = float(os.getenv("ROBOT_SENSOR_MAX_AGE_SECONDS", "2"))
        location_mode = os.getenv("ROBOT_LOCATION_MODE", "none").strip().lower()
        if location_mode not in {"none", "fixed"}:
            raise ValueError("ROBOT_LOCATION_MODE must be none or fixed")
        raw_longitude = os.getenv("ROBOT_FIXED_LONGITUDE", "").strip()
        raw_latitude = os.getenv("ROBOT_FIXED_LATITUDE", "").strip()
        longitude = float(raw_longitude) if raw_longitude else None
        latitude = float(raw_latitude) if raw_latitude else None
        if location_mode == "fixed":
            if longitude is None or latitude is None:
                raise ValueError("fixed location mode requires both ROBOT_FIXED_LONGITUDE and ROBOT_FIXED_LATITUDE")
            PointGeometry(coordinates=(longitude, latitude))
        if not 5 <= obstacle <= 300:
            raise ValueError("ROBOT_OBSTACLE_DISTANCE_CM must be between 5 and 300")
        if not 0.1 <= max_age <= 60:
            raise ValueError("ROBOT_SENSOR_MAX_AGE_SECONDS must be between 0.1 and 60")
        return cls(
            mode=mode,
            robot_id=os.getenv("ROBOT_ID", "freenove-fnk0052-01").strip(),
            allow_physical_actuation=_boolean("ROBOT_ALLOW_PHYSICAL_ACTUATION"),
            freenove_server_path=Path(vendor).expanduser() if vendor else None,
            backend_url=os.getenv("ROBOT_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/"),
            relay_url=os.getenv("ROBOT_RELAY_URL", "http://127.0.0.1:8000/relay/fleet").rstrip("/"),
            location_mode=location_mode,
            fixed_longitude=longitude,
            fixed_latitude=latitude,
            navigation_enabled=_boolean("ROBOT_NAVIGATION_ENABLED"),
            obstacle_distance_cm=obstacle,
            sensor_max_age_seconds=max_age,
        )
