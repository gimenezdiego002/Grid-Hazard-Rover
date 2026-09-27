"""Explicit safety boundary between mission decisions and robot movement."""

from __future__ import annotations

from datetime import datetime, timezone

from rover.controller import PhysicalActuationDisabled, RobotController, RobotControllerError
from rover.models import RobotCommandName


class RobotActuationGateway:
    def __init__(self, controller: RobotController, *, enabled: bool, max_command_age_seconds: float = 2.0) -> None:
        self.controller = controller
        self.enabled = enabled
        self.max_command_age_seconds = max_command_age_seconds

    def execute(self, command: RobotCommandName, *, issued_at: datetime) -> None:
        if not isinstance(command, RobotCommandName):
            self.controller.stop()
            raise RobotControllerError("malformed robot command rejected; robot stopped")
        if issued_at.tzinfo is None or issued_at.utcoffset() is None:
            self.controller.stop()
            raise RobotControllerError("command timestamp must include a UTC offset")
        age = (datetime.now(timezone.utc) - issued_at.astimezone(timezone.utc)).total_seconds()
        if age < 0 or age > self.max_command_age_seconds:
            self.controller.stop()
            raise RobotControllerError("stale or future robot command rejected; robot stopped")
        if command is not RobotCommandName.STOP and not self.enabled:
            self.controller.stop()
            raise PhysicalActuationDisabled("physical command boundary is disabled")
        operation = getattr(self.controller, command.value, None)
        if not callable(operation):
            self.controller.stop()
            raise RobotControllerError("malformed robot command rejected; robot stopped")
        try:
            operation()
        except Exception:
            self.controller.stop()
            raise


def stop_on_shutdown(controller: RobotController) -> None:
    """Idempotent shutdown hook used by CLI and future service handlers."""

    try:
        controller.stop()
    finally:
        controller.close()
