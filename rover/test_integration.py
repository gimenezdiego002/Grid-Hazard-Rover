from __future__ import annotations

import unittest
from unittest.mock import patch

from pydantic import ValidationError

from relay_gateway.fleet_gateway import FleetConfig, TelemetryCache
from rover.backend_adapter import PhotoObservation
from rover.controller import MockHexapodController
from rover.config import RobotConfig
from rover.demo import run_mock_demo
from rover.location import FixedLocationProvider
from rover.telemetry import inspection_envelope, status_envelope
from rover.telemetry import RelayTelemetryClient


class RoverIntegrationTests(unittest.TestCase):
    def test_environment_defaults_are_safe_and_fixed_location_is_validated(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            defaults = RobotConfig.from_env()
        self.assertEqual(defaults.mode, "mock")
        self.assertFalse(defaults.allow_physical_actuation)
        self.assertFalse(defaults.navigation_enabled)
        self.assertEqual(defaults.location_mode, "none")

        with patch.dict("os.environ", {"ROBOT_LOCATION_MODE": "fixed"}, clear=True):
            with self.assertRaises(ValueError):
                RobotConfig.from_env()

    def test_location_is_explicit_longitude_first(self) -> None:
        fix = FixedLocationProvider(
            -80.36, 25.76, source="operator_test", simulated=True
        ).get_location()
        self.assertEqual(fix.location.coordinates, (-80.36, 25.76))
        with self.assertRaises(ValidationError):
            FixedLocationProvider(-80.36, 125.76, source="bad", simulated=True)

    def test_photo_adapter_uses_trusted_fix_and_complete_jpeg(self) -> None:
        controller = MockHexapodController()
        controller.initialize()
        fix = FixedLocationProvider(-80.36, 25.76, source="mission", simulated=True).get_location()
        photo = PhotoObservation(controller.capture_frame(), fix, controller.robot_id)
        files, data = photo.multipart()
        self.assertEqual(data["longitude"], "-80.36")
        self.assertEqual(data["latitude"], "25.76")
        self.assertTrue(data["source"].startswith("simulated:"))
        self.assertEqual(files["image"][2], "image/jpeg")

    def test_relay_telemetry_duplicate_and_sequence_handling(self) -> None:
        controller = MockHexapodController()
        controller.initialize()
        cache = TelemetryCache(FleetConfig())
        status = controller.health_check()
        events = [
            status_envelope(status, mission_id="mission-1", station_id="site-1", timestamp_seconds=1),
            inspection_envelope(
                status, mission_id="mission-1", station_id="site-1",
                timestamp_seconds=2, evidence_ref="mock-frame-1",
            ),
        ]
        self.assertTrue(cache.accept(events[0])["accepted"])
        accepted = cache.accept(events[1])
        duplicate = cache.accept(events[1])
        self.assertEqual(accepted["sequence"], 2)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(cache.read()["latest_sequence"], 2)

    def test_relay_network_client_validates_ack_without_retry(self) -> None:
        controller = MockHexapodController()
        controller.initialize()
        event = status_envelope(
            controller.health_check(), mission_id="mission-1", station_id="site-1",
            timestamp_seconds=1,
        )
        calls = []

        def transport(url, headers, body, timeout):
            calls.append((url, headers, body, timeout))
            return 202, (
                b'{"accepted":true,"duplicate":false,"event_id":"'
                + event.event_id.encode()
                + b'","sequence":1}'
            )

        client = RelayTelemetryClient("http://127.0.0.1:8000/relay/fleet", transport=transport)
        self.assertTrue(client.send(event)["accepted"])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Authorization", calls[0][1])
        with self.assertRaises(ValueError):
            RelayTelemetryClient("http://remote.example/relay/fleet")

    def test_end_to_end_mock_demo_reaches_canonical_risk_and_stops(self) -> None:
        result = run_mock_demo()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["simulated"])
        self.assertFalse(result["physical_hardware_tested"])
        self.assertEqual(result["paid_api_calls"], 0)
        stages = {item["stage"]: item for item in result["stages"]}
        self.assertTrue(stages["relay_telemetry"]["duplicate_rejected"])
        self.assertGreater(stages["grid_hazard_pipeline"]["matches"], 0)
        self.assertGreater(stages["grid_hazard_pipeline"]["risk_cells"], 0)
        self.assertEqual(stages["failsafe_stop"]["movement_state"], "stopped")


if __name__ == "__main__":
    unittest.main()
