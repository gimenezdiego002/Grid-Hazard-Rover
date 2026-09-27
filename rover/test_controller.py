from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from rover.actuation import RobotActuationGateway, stop_on_shutdown
from rover.controller import (
    FreenoveFNK0052Controller,
    MockHexapodController,
    PhysicalActuationDisabled,
    RobotControllerError,
)
from rover.models import MovementState, RobotCommandName


class MockControllerTests(unittest.TestCase):
    def test_all_semantic_commands_and_truthful_status(self) -> None:
        controller = MockHexapodController(distances_cm=(75.0,))
        controller.initialize()
        for operation, expected in (
            (controller.stand, MovementState.STANDING),
            (controller.forward, MovementState.FORWARD),
            (controller.backward, MovementState.BACKWARD),
            (controller.turn_left, MovementState.TURNING_LEFT),
            (controller.turn_right, MovementState.TURNING_RIGHT),
            (controller.sit, MovementState.SITTING),
            (controller.stop, MovementState.STOPPED),
        ):
            operation()
            self.assertEqual(controller.health_check().movement_state, expected)
        status = controller.health_check()
        self.assertTrue(status.simulated)
        self.assertFalse(status.physical_actuation_enabled)
        self.assertEqual(controller.get_distance().distance_cm, 75.0)
        frame = controller.capture_frame()
        self.assertTrue(frame.startswith(b"\xff\xd8"))
        self.assertTrue(frame.endswith(b"\xff\xd9"))

    def test_controlled_failure_and_shutdown_end_stopped(self) -> None:
        controller = MockHexapodController(fail_on={"forward"})
        controller.initialize()
        with self.assertRaises(RobotControllerError):
            controller.forward()
        self.assertEqual(controller.health_check().movement_state, MovementState.STOPPED)
        self.assertIsNotNone(controller.health_check().error)
        stop_on_shutdown(controller)
        status = controller.health_check()
        self.assertFalse(status.initialized)
        self.assertEqual(status.movement_state, MovementState.STOPPED)

    def test_physical_controller_is_gated_before_vendor_import(self) -> None:
        controller = FreenoveFNK0052Controller("fnk0052-01", None)
        with self.assertRaises(PhysicalActuationDisabled):
            controller.initialize()
        status = controller.health_check()
        self.assertFalse(status.initialized)
        self.assertFalse(status.physical_actuation_enabled)

    def test_camera_failure_stops(self) -> None:
        controller = MockHexapodController(fail_on={"camera"})
        controller.initialize()
        controller.forward()
        with self.assertRaises(RobotControllerError):
            controller.capture_frame()
        self.assertEqual(controller.health_check().movement_state, MovementState.STOPPED)


class ActuationGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = MockHexapodController()
        self.controller.initialize()

    def test_disabled_boundary_blocks_motion_but_allows_stop(self) -> None:
        gateway = RobotActuationGateway(self.controller, enabled=False)
        with self.assertRaises(PhysicalActuationDisabled):
            gateway.execute(RobotCommandName.FORWARD, issued_at=datetime.now(timezone.utc))
        self.assertEqual(self.controller.health_check().movement_state, MovementState.STOPPED)
        gateway.execute(RobotCommandName.STOP, issued_at=datetime.now(timezone.utc))

    def test_stale_command_fails_safe(self) -> None:
        gateway = RobotActuationGateway(self.controller, enabled=True, max_command_age_seconds=1)
        stale = datetime.now(timezone.utc) - timedelta(seconds=5)
        with self.assertRaises(RobotControllerError):
            gateway.execute(RobotCommandName.FORWARD, issued_at=stale)
        self.assertEqual(self.controller.health_check().movement_state, MovementState.STOPPED)

    def test_malformed_command_fails_safe(self) -> None:
        gateway = RobotActuationGateway(self.controller, enabled=True)
        with self.assertRaises(RobotControllerError):
            gateway.execute("dance", issued_at=datetime.now(timezone.utc))  # type: ignore[arg-type]
        self.assertEqual(self.controller.health_check().movement_state, MovementState.STOPPED)


if __name__ == "__main__":
    unittest.main()
