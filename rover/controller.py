"""Semantic controller boundary for mock and official Freenove FNK0052 code."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
import importlib
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from typing import Iterable, Iterator

from PIL import Image

from rover.models import DistanceReading, MovementState, RobotCommandName, RobotStatus


class RobotControllerError(RuntimeError):
    pass


class PhysicalActuationDisabled(RobotControllerError):
    pass


class HardwareUnavailable(RobotControllerError):
    pass


class RobotController(ABC):
    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def health_check(self) -> RobotStatus: ...

    @abstractmethod
    def stand(self) -> None: ...

    @abstractmethod
    def sit(self) -> None: ...

    @abstractmethod
    def forward(self) -> None: ...

    @abstractmethod
    def backward(self) -> None: ...

    @abstractmethod
    def turn_left(self) -> None: ...

    @abstractmethod
    def turn_right(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def get_distance(self) -> DistanceReading: ...

    @abstractmethod
    def capture_frame(self) -> bytes: ...

    @abstractmethod
    def close(self) -> None: ...


class MockHexapodController(RobotController):
    """Deterministic hardware-free FNK0052 emulator; every state is simulated."""

    def __init__(
        self,
        robot_id: str = "freenove-fnk0052-01",
        *,
        distances_cm: Iterable[float] = (100.0,),
        fail_on: Iterable[str] = (),
    ) -> None:
        self.robot_id = robot_id
        self._distances = deque(float(value) for value in distances_cm)
        self._last_distance = self._distances[-1] if self._distances else 100.0
        self._fail_on = set(fail_on)
        self._initialized = False
        self._movement = MovementState.UNINITIALIZED
        self._last_command: RobotCommandName | None = None
        self._last_sensor_timestamp: datetime | None = None
        self._error: str | None = None

    def _require_ready(self, operation: str) -> None:
        if not self._initialized:
            raise RobotControllerError("mock controller is not initialized")
        if operation in self._fail_on:
            self._movement = MovementState.ERROR
            self._error = f"simulated {operation} failure"
            raise RobotControllerError(self._error)

    def _move(self, command: RobotCommandName, state: MovementState) -> None:
        try:
            self._require_ready(command.value)
        except Exception:
            self.stop()
            raise
        self._last_command = command
        self._movement = state

    def initialize(self) -> None:
        if "initialize" in self._fail_on:
            self._error = "simulated initialize failure"
            self._movement = MovementState.STOPPED
            raise RobotControllerError(self._error)
        self._initialized = True
        self._movement = MovementState.STOPPED

    def health_check(self) -> RobotStatus:
        return RobotStatus(
            robot_id=self.robot_id,
            mode="mock",
            initialized=self._initialized,
            movement_state=self._movement,
            physical_actuation_enabled=False,
            camera_available="camera" not in self._fail_on,
            distance_sensor_available="distance" not in self._fail_on,
            simulated=True,
            last_command=self._last_command,
            last_sensor_timestamp=self._last_sensor_timestamp,
            error=self._error,
        )

    def stand(self) -> None:
        self._move(RobotCommandName.STAND, MovementState.STANDING)

    def sit(self) -> None:
        self._move(RobotCommandName.SIT, MovementState.SITTING)

    def forward(self) -> None:
        self._move(RobotCommandName.FORWARD, MovementState.FORWARD)

    def backward(self) -> None:
        self._move(RobotCommandName.BACKWARD, MovementState.BACKWARD)

    def turn_left(self) -> None:
        self._move(RobotCommandName.TURN_LEFT, MovementState.TURNING_LEFT)

    def turn_right(self) -> None:
        self._move(RobotCommandName.TURN_RIGHT, MovementState.TURNING_RIGHT)

    def stop(self) -> None:
        if not self._initialized:
            self._movement = MovementState.STOPPED
            return
        self._last_command = RobotCommandName.STOP
        self._movement = MovementState.STOPPED

    def get_distance(self) -> DistanceReading:
        try:
            self._require_ready("distance")
        except Exception:
            self.stop()
            raise
        if self._distances:
            self._last_distance = self._distances.popleft()
        measured = datetime.now(timezone.utc)
        self._last_sensor_timestamp = measured
        return DistanceReading(
            distance_cm=self._last_distance,
            measured_at=measured,
            simulated=True,
        )

    def capture_frame(self) -> bytes:
        try:
            self._require_ready("camera")
        except Exception:
            self.stop()
            raise
        output = BytesIO()
        Image.new("RGB", (64, 48), color=(80, 80, 80)).save(output, format="JPEG")
        return output.getvalue()

    def close(self) -> None:
        self.stop()
        self._initialized = False


class FreenoveFNK0052Controller(RobotController):
    """Thin gated adapter over Freenove's official Server modules.

    No GPIO module is imported and no controller object is created until both
    the explicit physical gate and `initialize()` are used on the Raspberry Pi.
    Freenove owns inverse kinematics, calibration, and the 18-servo gait.
    """

    REQUIRED_FILES = ("control.py", "ultrasonic.py", "camera.py", "point.txt")

    def __init__(self, robot_id: str, server_path: Path | None, *, allow_physical_actuation: bool = False) -> None:
        self.robot_id = robot_id
        self.server_path = server_path.resolve() if server_path else None
        self.allow_physical_actuation = allow_physical_actuation
        self._control = None
        self._ultrasonic = None
        self._camera = None
        self._initialized = False
        self._movement = MovementState.UNINITIALIZED
        self._last_command: RobotCommandName | None = None
        self._last_sensor_timestamp: datetime | None = None
        self._error: str | None = None

    @contextmanager
    def _vendor_directory(self) -> Iterator[None]:
        if self.server_path is None:
            raise HardwareUnavailable("ROBOT_FREENOVE_SERVER_PATH is not configured")
        previous = Path.cwd()
        os.chdir(self.server_path)
        try:
            yield
        finally:
            os.chdir(previous)

    def _validate_vendor_tree(self) -> None:
        if self.server_path is None or not self.server_path.is_dir():
            raise HardwareUnavailable("official Freenove Server directory is unavailable")
        missing = [name for name in self.REQUIRED_FILES if not (self.server_path / name).is_file()]
        if missing:
            raise HardwareUnavailable(f"official Freenove Server directory is missing: {', '.join(missing)}")

    def initialize(self) -> None:
        if not self.allow_physical_actuation:
            raise PhysicalActuationDisabled("physical actuation is disabled; set the explicit gate only during supervised bring-up")
        self._validate_vendor_tree()
        assert self.server_path is not None
        server_text = str(self.server_path)
        if server_text not in sys.path:
            sys.path.insert(0, server_text)
        try:
            with self._vendor_directory():
                control_module = importlib.import_module("control")
                ultrasonic_module = importlib.import_module("ultrasonic")
                camera_module = importlib.import_module("camera")
                for module, filename in (
                    (control_module, "control.py"),
                    (ultrasonic_module, "ultrasonic.py"),
                    (camera_module, "camera.py"),
                ):
                    module_path = Path(getattr(module, "__file__", "")).resolve()
                    if module_path != (self.server_path / filename).resolve():
                        raise HardwareUnavailable(
                            f"refusing conflicting {module.__name__} module outside official Server directory"
                        )
                self._control = control_module.Control()
                self._ultrasonic = ultrasonic_module.Ultrasonic()
                self._camera = camera_module.Camera()
            self._initialized = True
            self._movement = MovementState.STOPPED
        except Exception as error:
            self._error = f"FNK0052 initialization failed: {type(error).__name__}"
            self._best_effort_stop()
            self._movement = MovementState.STOPPED
            raise HardwareUnavailable(self._error) from None

    def health_check(self) -> RobotStatus:
        return RobotStatus(
            robot_id=self.robot_id,
            mode="freenove",
            initialized=self._initialized,
            movement_state=self._movement,
            physical_actuation_enabled=self.allow_physical_actuation,
            camera_available=self._camera is not None,
            distance_sensor_available=self._ultrasonic is not None,
            simulated=False,
            last_command=self._last_command,
            last_sensor_timestamp=self._last_sensor_timestamp,
            error=self._error,
        )

    def _require_ready(self) -> None:
        if not self.allow_physical_actuation:
            raise PhysicalActuationDisabled("physical actuation is disabled")
        if not self._initialized or self._control is None:
            raise HardwareUnavailable("FNK0052 controller is not initialized")

    def _gait(self, command: RobotCommandName, state: MovementState, data: list[str]) -> None:
        self._require_ready()
        try:
            with self._vendor_directory():
                self._control.run_gait(data)
            self._last_command = command
            self._movement = state
        except Exception as error:
            self._error = f"FNK0052 command failed: {type(error).__name__}"
            self._best_effort_stop()
            self._movement = MovementState.STOPPED
            raise RobotControllerError(self._error) from None

    def stand(self) -> None:
        self._require_ready()
        try:
            self._control.relax(False)
            self._last_command = RobotCommandName.STAND
            self._movement = MovementState.STANDING
        except Exception as error:
            self._best_effort_stop()
            self._movement = MovementState.STOPPED
            raise RobotControllerError(f"FNK0052 stand failed: {type(error).__name__}") from None

    def sit(self) -> None:
        self.stop()
        raise HardwareUnavailable("official FNK0052 code has no verified sit primitive; robot remains stopped")

    def forward(self) -> None:
        self._gait(RobotCommandName.FORWARD, MovementState.FORWARD, ["CMD_MOVE", "1", "0", "25", "6", "0"])

    def backward(self) -> None:
        self._gait(RobotCommandName.BACKWARD, MovementState.BACKWARD, ["CMD_MOVE", "1", "0", "-25", "6", "0"])

    def turn_left(self) -> None:
        self._gait(RobotCommandName.TURN_LEFT, MovementState.TURNING_LEFT, ["CMD_MOVE", "1", "0", "0", "6", "-10"])

    def turn_right(self) -> None:
        self._gait(RobotCommandName.TURN_RIGHT, MovementState.TURNING_RIGHT, ["CMD_MOVE", "1", "0", "0", "6", "10"])

    def _best_effort_stop(self) -> None:
        if self._control is not None:
            try:
                with self._vendor_directory():
                    self._control.run_gait(["CMD_MOVE", "1", "0", "0", "6", "0"])
            except Exception:
                pass

    def stop(self) -> None:
        self._best_effort_stop()
        self._last_command = RobotCommandName.STOP
        self._movement = MovementState.STOPPED

    def get_distance(self) -> DistanceReading:
        self._require_ready()
        if self._ultrasonic is None:
            raise HardwareUnavailable("FNK0052 ultrasonic sensor is unavailable")
        try:
            value = self._ultrasonic.get_distance()
            if value is None:
                raise ValueError
            measured = datetime.now(timezone.utc)
            reading = DistanceReading(distance_cm=float(value), measured_at=measured, simulated=False)
            self._last_sensor_timestamp = measured
            return reading
        except Exception:
            self.stop()
            raise HardwareUnavailable("FNK0052 ultrasonic reading failed; robot stopped") from None

    def capture_frame(self) -> bytes:
        self._require_ready()
        if self._camera is None:
            raise HardwareUnavailable("FNK0052 camera is unavailable")
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=".jpg", delete=False) as temporary:
                temporary_path = Path(temporary.name)
            camera_device = getattr(self._camera, "camera", None)
            if camera_device is None:
                raise HardwareUnavailable("Picamera2 did not expose a camera device")
            camera_device.start()
            metadata = self._camera.save_image(str(temporary_path))
            camera_device.stop()
            if metadata is None or not temporary_path.is_file():
                raise HardwareUnavailable("camera capture did not produce a JPEG")
            payload = temporary_path.read_bytes()
            if not payload.startswith(b"\xff\xd8"):
                raise HardwareUnavailable("camera output is not JPEG")
            return payload
        except Exception as error:
            self.stop()
            if isinstance(error, HardwareUnavailable):
                raise
            raise HardwareUnavailable(f"FNK0052 camera capture failed: {type(error).__name__}") from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def close(self) -> None:
        self.stop()
        for device in (self._camera, self._ultrasonic):
            close = getattr(device, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._initialized = False
