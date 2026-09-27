"""Payload handoff state machine for the unconfirmed LeArm generation.

All input confirmations and IO events in this module are simulation data.
No servo angles, serial ports, hardware libraries, or physical actuation exist.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
import math
from typing import Any

from robotcode.runtime import RobotBase, SimulatedIO


class ArmController(RobotBase):
    """Reserve one station handoff and release it only after confirmation.

    ``load`` transfers station -> hexapod; ``unload`` transfers hexapod ->
    station. Inventory records change only on an explicit successful receipt
    or after an operator-style reconciliation of an interrupted transfer.
    """

    def __init__(
        self,
        robot_id: str = "arm-1",
        io: SimulatedIO | None = None,
        *,
        station_id: str = "station-a",
        inventory: Iterable[str] = (),
    ) -> None:
        super().__init__(robot_id, io)
        self.station_id = self._identifier(station_id, "station_id")
        self._require(not isinstance(inventory, (str, bytes)), "inventory must be an iterable of payload IDs")
        items = list(inventory)
        for item in items:
            self._identifier(item, "payload_id")
        self._require(len(items) == len(set(items)), "inventory must contain unique payload IDs")
        self.inventory = set(items)
        self.pending_transfer: dict[str, Any] | None = None
        self.last_transfer: dict[str, Any] | None = None
        self.needs_reconciliation = False
        self._used_transfer_ids: set[str] = set()

    def snapshot(self) -> dict[str, Any]:
        return {
            **super().snapshot(),
            "station_id": self.station_id,
            "inventory": sorted(self.inventory),
            "pending_transfer": deepcopy(self.pending_transfer),
            "last_transfer": deepcopy(self.last_transfer),
            "needs_reconciliation": self.needs_reconciliation,
            "station_locked": self.pending_transfer is not None,
        }

    def _handle(self, action: str, params: dict[str, Any]) -> None:
        handlers = {
            "prepare_transfer": self._prepare_transfer,
            "confirm_transfer": self._confirm_transfer,
            "check_interlock": self._check_interlock,
            "tick": self._tick,
            "reconcile_transfer": self._reconcile_transfer,
        }
        self._require(action in handlers, f"unsupported arm action: {action}")
        handlers[action](params)

    @staticmethod
    def _boolean(value: Any, name: str) -> bool:
        if type(value) is not bool:
            raise ValueError(f"{name} must be a boolean")
        return value

    @staticmethod
    def _seconds(value: Any, name: str, *, positive: bool = False) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number of seconds")
        number = float(value)
        if not math.isfinite(number) or number < 0 or (positive and number == 0):
            raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'} and finite")
        return number

    def _prepare_transfer(self, params: dict[str, Any]) -> None:
        self._params(
            params,
            {"station_id", "peer_id", "transfer_id", "payload_id", "direction", "peer_docked", "zone_clear"},
            {"timeout_s"},
        )
        self._require(self.state == "idle", "arm must be idle before a transfer")
        self._require(not self.needs_reconciliation, "interrupted transfer needs reconciliation")
        self._require(self.pending_transfer is None, "station already has a transfer")
        for key in ("station_id", "peer_id", "transfer_id", "payload_id"):
            self._identifier(params[key], key)
        self._require(params["station_id"] == self.station_id, "transfer station does not match this arm")
        self._require(params["peer_id"] != self.robot_id, "transfer peer must be a different robot")
        self._require(params["direction"] in ("load", "unload"), "direction must be load or unload")
        self._require(self._boolean(params["peer_docked"], "peer_docked"), "hexapod must confirm docking")
        self._require(self._boolean(params["zone_clear"], "zone_clear"), "arm zone must be clear")
        self._require(params["transfer_id"] not in self._used_transfer_ids, "transfer_id has already been used")
        payload_id = params["payload_id"]
        if params["direction"] == "load":
            self._require(payload_id in self.inventory, "payload is not in station inventory")
        else:
            self._require(payload_id not in self.inventory, "payload is already in station inventory")
        timeout_s = self._seconds(params.get("timeout_s", 30.0), "timeout_s", positive=True)
        self.pending_transfer = {
            key: params[key]
            for key in ("station_id", "peer_id", "transfer_id", "payload_id", "direction")
        }
        self.pending_transfer.update({"elapsed_s": 0.0, "timeout_s": timeout_s})
        self._used_transfer_ids.add(params["transfer_id"])
        self.state = "transferring"
        self.io.perform("arm_transfer_requested", **self.pending_transfer)

    def _confirm_transfer(self, params: dict[str, Any]) -> None:
        self._params(params, {"transfer_id", "payload_secured", "arm_clear"})
        self._require(self.state == "transferring", "arm must be transferring before confirmation")
        transfer = self._matching_transfer(params["transfer_id"])
        self._require(self._boolean(params["payload_secured"], "payload_secured"), "receiving side must confirm payload secured")
        self._require(self._boolean(params["arm_clear"], "arm_clear"), "arm must be clear before releasing the hexapod")
        # Preserve the reservation until every IO operation has returned. Even
        # an IO error raised after recording release leaves recovery ambiguous.
        transfer["confirmation_received"] = True
        self.io.perform("arm_transfer_confirmation_received", **transfer)
        self.io.perform("arm_peer_release", peer_id=transfer["peer_id"], transfer_id=transfer["transfer_id"])
        payload_id = transfer["payload_id"]
        if transfer["direction"] == "load":
            self.inventory.remove(payload_id)
        else:
            self.inventory.add(payload_id)
        self.last_transfer = {**transfer, "outcome": "confirmed", "simulated": True}
        self.pending_transfer = None
        self.state = "idle"

    def _check_interlock(self, params: dict[str, Any]) -> None:
        self._params(params, {"peer_docked", "zone_clear"})
        self._require(self.state == "transferring", "interlock checks require an active transfer")
        peer_docked = self._boolean(params["peer_docked"], "peer_docked")
        zone_clear = self._boolean(params["zone_clear"], "zone_clear")
        if not peer_docked or not zone_clear:
            self._interrupt("transfer interlock lost")

    def _tick(self, params: dict[str, Any]) -> None:
        self._params(params, {"elapsed_s"})
        self._require(self.state == "transferring", "watchdog ticks require an active transfer")
        elapsed_s = self._seconds(params["elapsed_s"], "elapsed_s")
        assert self.pending_transfer is not None
        self.pending_transfer["elapsed_s"] += elapsed_s
        if self.pending_transfer["elapsed_s"] >= self.pending_transfer["timeout_s"]:
            self._interrupt("transfer confirmation timed out")

    def _matching_transfer(self, transfer_id: Any) -> dict[str, Any]:
        self._identifier(transfer_id, "transfer_id")
        self._require(self.pending_transfer is not None, "no pending transfer")
        assert self.pending_transfer is not None
        self._require(self.pending_transfer["transfer_id"] == transfer_id, "transfer_id does not match pending transfer")
        return self.pending_transfer

    def _interrupt(self, reason: str) -> None:
        self._stop(reason)

    def _on_stop(self) -> None:
        if self.pending_transfer is not None:
            self.needs_reconciliation = True

    def _reconcile_transfer(self, params: dict[str, Any]) -> None:
        self._params(params, {"transfer_id", "payload_at_station", "arm_clear", "peer_released"})
        self._require(self.state == "stopped", "reconciliation requires a stopped arm")
        self._require(self.needs_reconciliation, "no interrupted transfer needs reconciliation")
        transfer = self._matching_transfer(params["transfer_id"])
        payload_at_station = self._boolean(params["payload_at_station"], "payload_at_station")
        self._require(self._boolean(params["arm_clear"], "arm_clear"), "arm must be clear before reconciliation")
        self._require(self._boolean(params["peer_released"], "peer_released"), "peer release must be explicitly confirmed")
        reconciled = {
            **transfer,
            "outcome": "reconciled",
            "payload_at_station": payload_at_station,
            "simulated": True,
        }
        self.io.perform("arm_transfer_reconciled", **reconciled)
        if payload_at_station:
            self.inventory.add(transfer["payload_id"])
        else:
            self.inventory.discard(transfer["payload_id"])
        self.last_transfer = reconciled
        self.pending_transfer = None
        self.needs_reconciliation = False
        # Reconciliation records the resolved inventory; explicit reset is
        # still needed to make the arm accept another transfer.

    def _on_reset(self) -> None:
        self._require(not self.needs_reconciliation, "reconcile interrupted transfer before reset")
        self._require(self.pending_transfer is None, "cannot reset with a pending transfer")
