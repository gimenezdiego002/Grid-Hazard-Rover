from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from rover.controller import MockHexapodController, RobotControllerError
from rover.models import DistanceReading, MovementState, NavigationAction
from rover.navigation import NavigationPolicy, NavigationRunner


class NavigationTests(unittest.TestCase):
    def test_clear_stop_then_turn_policy(self) -> None:
        controller = MockHexapodController(distances_cm=(100.0, 20.0, 20.0))
        controller.initialize()
        runner = NavigationRunner(controller, NavigationPolicy(obstacle_distance_cm=30))
        self.assertEqual(runner.step().action, NavigationAction.FORWARD)
        self.assertEqual(runner.step().action, NavigationAction.STOP)
        self.assertEqual(runner.step().action, NavigationAction.TURN_LEFT)
        self.assertEqual(controller.health_check().movement_state, MovementState.TURNING_LEFT)

    def test_stale_sensor_stops(self) -> None:
        policy = NavigationPolicy(sensor_max_age_seconds=1)
        reading = DistanceReading(
            distance_cm=100.0,
            measured_at=datetime.now(timezone.utc) - timedelta(seconds=2),
            simulated=True,
        )
        self.assertEqual(policy.decide(reading).action, NavigationAction.STOP)
        self.assertEqual(policy.decide(reading).reason, "stale_sensor")

    def test_sensor_exception_stops(self) -> None:
        controller = MockHexapodController(fail_on={"distance"})
        controller.initialize()
        runner = NavigationRunner(controller, NavigationPolicy())
        with self.assertRaises(RobotControllerError):
            runner.step()
        self.assertEqual(controller.health_check().movement_state, MovementState.STOPPED)


if __name__ == "__main__":
    unittest.main()
