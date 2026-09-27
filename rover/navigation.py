"""Small deterministic collision-avoidance policy independent of Gemini."""

from __future__ import annotations

from datetime import datetime, timezone

from rover.controller import RobotController
from rover.models import DistanceReading, NavigationAction, NavigationDecision


class NavigationPolicy:
    def __init__(self, obstacle_distance_cm: float = 30.0, sensor_max_age_seconds: float = 2.0) -> None:
        if not 5 <= obstacle_distance_cm <= 300:
            raise ValueError("obstacle threshold must be between 5 and 300 cm")
        if not 0.1 <= sensor_max_age_seconds <= 60:
            raise ValueError("sensor age limit must be between 0.1 and 60 seconds")
        self.obstacle_distance_cm = obstacle_distance_cm
        self.sensor_max_age_seconds = sensor_max_age_seconds
        self._blocked_count = 0
        self._turn_left_next = True

    def decide(self, reading: DistanceReading, *, now: datetime | None = None) -> NavigationDecision:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("navigation clock must include a UTC offset")
        age = (current - reading.measured_at.astimezone(timezone.utc)).total_seconds()
        if age < 0 or age > self.sensor_max_age_seconds:
            self._blocked_count = 0
            return NavigationDecision(action=NavigationAction.STOP, reason="stale_sensor", simulated=reading.simulated)
        if reading.distance_cm <= self.obstacle_distance_cm:
            self._blocked_count += 1
            if self._blocked_count == 1:
                return NavigationDecision(action=NavigationAction.STOP, reason="obstacle_detected", simulated=reading.simulated)
            action = NavigationAction.TURN_LEFT if self._turn_left_next else NavigationAction.TURN_RIGHT
            self._turn_left_next = not self._turn_left_next
            return NavigationDecision(action=action, reason="obstacle_persisted", simulated=reading.simulated)
        self._blocked_count = 0
        return NavigationDecision(action=NavigationAction.FORWARD, reason="path_clear", simulated=reading.simulated)


class NavigationRunner:
    def __init__(self, controller: RobotController, policy: NavigationPolicy) -> None:
        self.controller = controller
        self.policy = policy

    def step(self) -> NavigationDecision:
        try:
            decision = self.policy.decide(self.controller.get_distance())
            getattr(self.controller, decision.action.value)()
            return decision
        except Exception:
            self.controller.stop()
            raise

    def shutdown(self) -> None:
        self.controller.stop()
