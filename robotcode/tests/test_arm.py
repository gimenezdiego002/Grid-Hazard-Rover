"""Offline checks for station handoff and interruption semantics."""

from copy import deepcopy
import unittest

from robotcode.arm import ArmController
from robotcode.runtime import SimulatedIO


class FailingIO(SimulatedIO):
    """Raise before or after recording an operation, including ValueError."""

    def __init__(self, failure_action, *, after_record=False):
        super().__init__()
        self.failure_action = failure_action
        self.after_record = after_record

    def perform(self, action, **details):
        if action == self.failure_action and not self.after_record:
            raise ValueError("simulated IO failure")
        super().perform(action, **details)
        if action == self.failure_action:
            raise ValueError("simulated IO failure after recording")


class ArmControllerTests(unittest.TestCase):
    def setUp(self):
        self.arm = ArmController(station_id="station-1", inventory=["kit-1"])
        self.prepare = {
            "station_id": "station-1", "peer_id": "hexapod-1",
            "transfer_id": "transfer-1", "payload_id": "kit-1",
            "direction": "load", "peer_docked": True, "zone_clear": True,
        }

    def begin(self, **overrides):
        return self.arm.command("prepare-1", "prepare_transfer", **(self.prepare | overrides))

    def confirm(self, **overrides):
        params = {"transfer_id": "transfer-1", "payload_secured": True, "arm_clear": True}
        return self.arm.command("confirm-1", "confirm_transfer", **(params | overrides))

    def test_inventory_changes_only_on_confirmed_transfer(self):
        self.begin()
        self.assertEqual(self.arm.snapshot()["inventory"], ["kit-1"])
        self.assertTrue(self.arm.snapshot()["station_locked"])
        self.confirm()
        self.assertEqual(self.arm.state, "idle")
        self.assertEqual(self.arm.snapshot()["inventory"], [])
        self.assertFalse(self.arm.snapshot()["station_locked"])
        self.assertEqual(self.arm.last_transfer["outcome"], "confirmed")
        self.arm.command("unload-prepare", "prepare_transfer", **(self.prepare | {
            "transfer_id": "transfer-2", "direction": "unload",
        }))
        self.assertEqual(self.arm.snapshot()["inventory"], [])
        self.arm.command("unload-confirm", "confirm_transfer", transfer_id="transfer-2",
                         payload_secured=True, arm_clear=True)
        self.assertEqual(self.arm.snapshot()["inventory"], ["kit-1"])

    def test_docking_clearance_and_inventory_are_required(self):
        for override in (
            {"peer_docked": False}, {"zone_clear": False},
            {"peer_docked": "true"}, {"payload_id": "missing"},
            {"direction": "unload"}, {"timeout_s": float("nan")},
            {"timeout_s": True}, {"unexpected": "field"},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.arm.command(f"reject-{len(str(override))}", "prepare_transfer",
                                 **(self.prepare | override))
            self.assertEqual(self.arm.state, "idle")
            self.assertIsNone(self.arm.pending_transfer)

    def test_confirmation_requires_receiving_side_and_clear_arm(self):
        self.begin()
        for index, override in enumerate((
            {"transfer_id": "wrong"}, {"payload_secured": False},
            {"arm_clear": False}, {"arm_clear": "true"},
        )):
            params = {"transfer_id": "transfer-1", "payload_secured": True, "arm_clear": True} | override
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.arm.command(f"reject-confirm-{index}", "confirm_transfer", **params)
            self.assertEqual(self.arm.state, "transferring")
            self.assertTrue(self.arm.snapshot()["station_locked"])
            self.assertEqual(self.arm.snapshot()["inventory"], ["kit-1"])

    def test_duplicate_command_has_no_duplicate_transfer(self):
        first = self.begin()
        records = deepcopy(self.arm.io.records)
        self.assertEqual(self.begin(), first)
        self.assertEqual(self.arm.io.records, records)
        self.confirm()
        with self.assertRaises(ValueError):
            self.arm.command("new-prepare", "prepare_transfer", **self.prepare)

    def test_second_peer_cannot_replace_active_transfer(self):
        self.begin()
        with self.assertRaises(ValueError):
            self.arm.command("second-peer", "prepare_transfer", **(self.prepare | {
                "peer_id": "hexapod-2", "transfer_id": "transfer-2",
            }))
        self.assertEqual(self.arm.pending_transfer["peer_id"], "hexapod-1")

    def test_timeout_keeps_inventory_uncertain_and_prevents_reset(self):
        self.begin(timeout_s=2)
        self.arm.command("tick-1", "tick", elapsed_s=1)
        self.assertEqual(self.arm.state, "transferring")
        self.arm.command("tick-2", "tick", elapsed_s=1)
        self.assertEqual(self.arm.state, "stopped")
        self.assertTrue(self.arm.needs_reconciliation)
        self.assertTrue(self.arm.snapshot()["station_locked"])
        self.assertEqual(self.arm.snapshot()["inventory"], ["kit-1"])
        with self.assertRaises(ValueError):
            self.arm.command("reset-early", "reset")
        self.assertEqual(self.arm.state, "stopped")
        with self.assertRaises(ValueError):
            self.confirm()
        self.arm.command("reconcile", "reconcile_transfer", transfer_id="transfer-1",
                         payload_at_station=False, arm_clear=True, peer_released=True)
        self.assertEqual(self.arm.snapshot()["inventory"], [])
        self.assertEqual(self.arm.state, "stopped")
        self.assertFalse(self.arm.needs_reconciliation)
        self.arm.command("reset-ready", "reset")
        self.assertEqual(self.arm.state, "idle")

    def test_stop_and_lost_interlock_require_reconciliation(self):
        for action, params in (
            ("stop", {"reason": "operator_stop"}),
            ("check_interlock", {"peer_docked": False, "zone_clear": True}),
            ("check_interlock", {"peer_docked": True, "zone_clear": False}),
        ):
            with self.subTest(action=action, params=params):
                self.setUp()
                self.begin()
                self.arm.command("interrupt", action, **params)
                self.assertEqual(self.arm.state, "stopped")
                self.assertTrue(self.arm.needs_reconciliation)
                with self.assertRaises(ValueError):
                    self.arm.command("unsafe-reconcile", "reconcile_transfer", transfer_id="transfer-1",
                                     payload_at_station=True, arm_clear=False, peer_released=True)
                self.arm.command("safe-reconcile", "reconcile_transfer", transfer_id="transfer-1",
                                 payload_at_station=True, arm_clear=True, peer_released=True)
                self.assertEqual(self.arm.snapshot()["inventory"], ["kit-1"])

    def test_tick_replay_does_not_extend_elapsed_time(self):
        self.begin(timeout_s=2)
        self.arm.command("tick-1", "tick", elapsed_s=1)
        self.arm.command("tick-1", "tick", elapsed_s=1)
        self.assertEqual(self.arm.pending_transfer["elapsed_s"], 1)
        self.assertEqual(self.arm.state, "transferring")

    def test_snapshot_cannot_modify_live_transfer(self):
        self.begin()
        snapshot = self.arm.snapshot()
        snapshot["pending_transfer"]["peer_id"] = "changed"
        snapshot["inventory"].clear()
        self.assertEqual(self.arm.pending_transfer["peer_id"], "hexapod-1")
        self.assertEqual(self.arm.snapshot()["inventory"], ["kit-1"])

    def test_arm_only_accepts_its_configured_station(self):
        self.assertEqual(self.arm.snapshot()["station_id"], "station-1")
        with self.assertRaises(ValueError):
            self.begin(station_id="station-2")
        self.assertEqual(self.arm.state, "idle")
        self.assertEqual(self.arm.io.records, [])
        self.assertEqual(ArmController().snapshot()["station_id"], "station-a")

    def test_partial_confirmation_io_failure_keeps_recovery_latched(self):
        for failure_action in ("arm_transfer_confirmation_received", "arm_peer_release"):
            for after_record in (False, True):
                with self.subTest(failure_action=failure_action, after_record=after_record):
                    self.arm = ArmController(station_id="station-1", inventory=["kit-1"],
                                             io=FailingIO(failure_action, after_record=after_record))
                    self.begin()
                    with self.assertRaises(RuntimeError):
                        self.confirm()
                    snapshot = self.arm.snapshot()
                    self.assertEqual(snapshot["state"], "stopped")
                    self.assertTrue(snapshot["needs_reconciliation"])
                    self.assertTrue(snapshot["station_locked"])
                    self.assertEqual(snapshot["inventory"], ["kit-1"])
                    self.assertIsNone(snapshot["last_transfer"])
                    self.assertTrue(snapshot["pending_transfer"]["confirmation_received"])
                    with self.assertRaises(ValueError):
                        self.arm.command("reset-early", "reset")

    def test_reconciliation_io_failure_preserves_uncertainty(self):
        for after_record in (False, True):
            with self.subTest(after_record=after_record):
                adapter = FailingIO("arm_transfer_reconciled", after_record=after_record)
                self.arm = ArmController(station_id="station-1", inventory=["kit-1"], io=adapter)
                self.begin()
                self.arm.command("stop-transfer", "stop")
                params = {"transfer_id": "transfer-1", "payload_at_station": False,
                          "arm_clear": True, "peer_released": True}
                with self.assertRaises(RuntimeError):
                    self.arm.command("reconcile", "reconcile_transfer", **params)
                self.assertTrue(self.arm.needs_reconciliation)
                self.assertTrue(self.arm.snapshot()["station_locked"])
                self.assertEqual(self.arm.snapshot()["inventory"], ["kit-1"])
                self.assertIsNone(self.arm.last_transfer)
                with self.assertRaises(ValueError):
                    self.arm.command("reset-early", "reset")
                adapter.failure_action = None
                self.arm.command("reconcile", "reconcile_transfer", **params)
                self.assertFalse(self.arm.needs_reconciliation)
                self.assertEqual(self.arm.snapshot()["inventory"], [])
                self.assertEqual(self.arm.state, "stopped")


if __name__ == "__main__":
    unittest.main()
