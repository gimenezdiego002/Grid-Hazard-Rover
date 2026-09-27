"""State transitions and station custody invariants; no hardware or cloud calls."""

import unittest

from robotcode.hexapod import HexapodController


class HexapodTests(unittest.TestCase):
    def setUp(self):
        self.robot = HexapodController()
        self.sequence = 0

    def command(self, action, **params):
        self.sequence += 1
        return self.robot.command(f"hex-test-{self.sequence}", action, **params)

    def at_station(self):
        self.command("dispatch", target="station-1")
        self.command("arrive", target="station-1")
        self.command("dock", station_id="station-1")

    def prepare_load(self):
        self.at_station()
        self.command("prepare_transfer", station_id="station-1", transfer_id="load-1", payload_id="sensor-1")

    def complete_load(self):
        self.prepare_load()
        self.command("confirm_transfer", transfer_id="load-1", payload_secured=True, arm_clear=True)

    def test_navigation_requires_matching_arrival_and_inspection_evidence(self):
        self.command("dispatch", target="leak-1")
        self.assertEqual(self.robot.state, "travelling")
        with self.assertRaises(ValueError):
            self.command("arrive", target="elsewhere")
        with self.assertRaises(ValueError):
            self.command("inspect", evidence_ref="simulated:too-early")
        self.command("arrive", target="leak-1")
        with self.assertRaises(ValueError):
            self.command("inspect", evidence_ref=" ")
        self.command("inspect", evidence_ref="simulated:leak-1")
        self.assertEqual(self.robot.state, "idle")
        self.assertEqual(self.robot.location, "leak-1")
        self.assertTrue(self.robot.snapshot()["simulated"])

    def test_wrong_station_and_departure_during_docking_rejected(self):
        self.command("dispatch", target="station-1")
        with self.assertRaises(ValueError):
            self.command("dock", station_id="station-1")
        self.command("arrive", target="station-1")
        with self.assertRaises(ValueError):
            self.command("dock", station_id="station-2")
        self.command("dock", station_id="station-1")
        with self.assertRaises(ValueError):
            self.command("dispatch", target="leak-1")

    def test_load_requires_custody_confirmation_and_arm_clearance(self):
        self.prepare_load()
        self.assertIsNone(self.robot.payload_id)
        for params in [
            {"transfer_id": "wrong", "payload_secured": True, "arm_clear": True},
            {"transfer_id": "load-1", "payload_secured": False, "arm_clear": True},
            {"transfer_id": "load-1", "payload_secured": True, "arm_clear": False},
            {"transfer_id": "load-1", "payload_secured": 1, "arm_clear": True},
        ]:
            with self.assertRaises(ValueError):
                self.command("confirm_transfer", **params)
            self.assertEqual(self.robot.state, "transferring")
            self.assertIsNone(self.robot.payload_id)
        with self.assertRaises(ValueError):
            self.command("undock", arm_clear=True)
        self.command("confirm_transfer", transfer_id="load-1", payload_secured=True, arm_clear=True)
        self.assertEqual(self.robot.payload_id, "sensor-1")
        with self.assertRaises(ValueError):
            self.command("undock", arm_clear=False)
        self.command("undock", arm_clear=True)
        self.command("dispatch", target="leak-1")
        self.assertEqual(self.robot.state, "travelling")

    def test_load_then_unload_preserves_custody_until_confirmation(self):
        self.complete_load()
        with self.assertRaises(ValueError):
            self.command("prepare_transfer", station_id="station-1", transfer_id="load-2", payload_id="sensor-2")
        with self.assertRaises(ValueError):
            self.command("prepare_transfer", station_id="station-1", transfer_id="unload-wrong", payload_id="wrong", direction="unload")
        self.command("prepare_transfer", station_id="station-1", transfer_id="unload-1", payload_id="sensor-1", direction="unload")
        self.assertEqual(self.robot.payload_id, "sensor-1")
        self.command("confirm_transfer", transfer_id="unload-1", payload_secured=True, arm_clear=True)
        self.assertIsNone(self.robot.payload_id)

    def test_transfer_ids_cannot_be_reused(self):
        self.complete_load()
        with self.assertRaises(ValueError):
            self.command("prepare_transfer", station_id="station-1", transfer_id="load-1", payload_id="sensor-1", direction="unload")

    def test_stop_during_transfer_requires_explicit_reconciliation(self):
        self.prepare_load()
        self.command("stop", reason="simulated_emergency")
        self.assertTrue(self.robot.transfer_reconciliation_required)
        with self.assertRaises(ValueError):
            self.command("reset")
        self.assertEqual(self.robot.state, "stopped")
        with self.assertRaises(ValueError):
            self.command("reconcile_transfer", payload_id="sensor-1", arm_clear=False, evidence_ref="simulated:check")
        with self.assertRaises(ValueError):
            self.command("confirm_transfer", transfer_id="load-1", payload_secured=True, arm_clear=True)
        self.command("reconcile_transfer", payload_id=None, arm_clear=True, evidence_ref="simulated:carrier-empty")
        self.assertEqual(self.robot.state, "stopped")
        self.command("reset")
        self.assertEqual(self.robot.state, "idle")
        self.assertIsNone(self.robot.payload_id)
        self.assertIsNone(self.robot.transfer)

    def test_docked_stop_cannot_bypass_clearance(self):
        self.complete_load()
        self.command("stop", reason="simulated_station_stop")
        with self.assertRaises(ValueError):
            self.command("reset")
        self.command("reconcile_transfer", payload_id="sensor-1", arm_clear=True, evidence_ref="simulated:secured")
        self.command("reset")
        self.assertEqual(self.robot.payload_id, "sensor-1")

    def test_navigation_timeout_stops_without_fabricated_arrival(self):
        self.command("dispatch", target="leak-1")
        self.command("tick", elapsed_s=119)
        self.assertEqual(self.robot.state, "travelling")
        self.command("tick", elapsed_s=1)
        self.assertEqual(self.robot.state, "stopped")
        self.assertIsNone(self.robot.location)
        self.assertIsNotNone(self.robot.fault)
        self.command("reset")
        self.assertEqual(self.robot.state, "idle")

    def test_transfer_timeout_requires_reconciliation(self):
        self.prepare_load()
        self.command("tick", elapsed_s=30)
        self.assertEqual(self.robot.state, "stopped")
        self.assertTrue(self.robot.transfer_reconciliation_required)
        with self.assertRaises(ValueError):
            self.command("reset")

    def test_replayed_dispatch_does_not_repeat_io(self):
        receipt = self.robot.command("same", "dispatch", target="leak-1")
        count = len(self.robot.io.records)
        self.assertEqual(self.robot.command("same", "dispatch", target="leak-1"), receipt)
        self.assertEqual(len(self.robot.io.records), count)
        with self.assertRaises(ValueError):
            self.robot.command("same", "dispatch", target="different")

    def test_unknown_parameters_and_invalid_ticks_rejected(self):
        with self.assertRaises(ValueError):
            self.command("dispatch", target="leak-1", speed=100)
        self.assertEqual(self.robot.state, "idle")
        for elapsed_s in [True, 0, -1, 3601, float("nan"), float("inf"), "1"]:
            with self.assertRaises(ValueError):
                self.command("tick", elapsed_s=elapsed_s)

    def test_station_visit_can_skip_transfer(self):
        self.at_station()
        self.command("undock", arm_clear=True)
        self.command("dispatch", target="leak-1")
        self.assertIsNone(self.robot.payload_id)
        self.assertEqual(self.robot.state, "travelling")


if __name__ == "__main__":
    unittest.main()
