"""Truthful robot-side state and command models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class MovementState(str, Enum):
    UNINITIALIZED = "uninitialized"
    STOPPED = "stopped"
    STANDING = "standing"
    SITTING = "sitting"
    FORWARD = "forward"
    BACKWARD = "backward"
    TURNING_LEFT = "turning_left"
    TURNING_RIGHT = "turning_right"
    ERROR = "error"


class RobotCommandName(str, Enum):
    STAND = "stand"
    SIT = "sit"
    FORWARD = "forward"
    BACKWARD = "backward"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    STOP = "stop"


class RobotStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    model: Literal["FNK0052"] = "FNK0052"
    mode: Literal["mock", "freenove"]
    initialized: bool
    movement_state: MovementState
    physical_actuation_enabled: bool
    camera_available: bool
    distance_sensor_available: bool
    simulated: bool
    last_command: RobotCommandName | None = None
    last_sensor_timestamp: datetime | None = None
    error: str | None = None


class DistanceReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance_cm: Annotated[float, Field(strict=True, gt=0, le=1000, allow_inf_nan=False)]
    measured_at: datetime
    simulated: bool


class NavigationAction(str, Enum):
    FORWARD = "forward"
    STOP = "stop"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"


class NavigationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: NavigationAction
    reason: str
    simulated: bool
