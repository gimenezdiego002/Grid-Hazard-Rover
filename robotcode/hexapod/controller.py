"""Offline hexapod mission logic; no GPIO, sockets, vendor imports or motion.

Arrival, docking, payload transfer and inspection are separate acknowledgements.
These inputs are simulated observations, never evidence that real hardware moved.
"""

from robotcode.runtime import RobotBase


class HexapodController(RobotBase):
    """Carry optional payloads through explicitly acknowledged mission steps."""

    NAVIGATION_TIMEOUT_S = 120.0
    TRANSFER_TIMEOUT_S = 30.0

    def __init__(self, robot_id: str = "hexapod-1", io=None):
        super().__init__(robot_id, io)
        self.target: str | None = None
        self.location: str | None = None
        self.station_id: str | None = None
        self.payload_id: str | None = None
        self.transfer: dict | None = None
        self.transfer_reconciliation_required = False
        self.last_evidence_ref: str | None = None
        self.elapsed_s = 0.0
        self._used_transfer_ids: set[str] = set()

    def _handle(self, action: str, params: dict):
        handlers = {
            "dispatch": self._dispatch,
            "arrive": self._arrive,
            "dock": self._dock,
            "prepare_transfer": self._prepare_transfer,
            "confirm_transfer": self._confirm_transfer,
            "undock": self._undock,
            "inspect": self._inspect,
            "reconcile_transfer": self._reconcile_transfer,
            "tick": self._tick,
        }
        self._require(action in handlers, f"Unknown hexapod action: {action}")
        handlers[action](params)

    def _dispatch(self, params: dict):
        self._params(params, {"target"})
        target = self._identifier(params["target"], "target")
        self._require(self.state in {"idle", "at_target"}, "Dispatch requires idle or at_target")
        self._require(not self.transfer_reconciliation_required, "Payload reconciliation required")
        self.io.perform("navigate", target=target, payload_id=self.payload_id)
        self.target = target
        self.elapsed_s = 0.0
        self.state = "travelling"

    def _arrive(self, params: dict):
        self._params(params, {"target"})
        target = self._identifier(params["target"], "target")
        self._require(self.state == "travelling", "Arrival requires travelling")
        self._require(target == self.target, "Arrival does not match the dispatched target")
        self.io.perform("arrival_acknowledged", target=target)
        self.location = target
        self.elapsed_s = 0.0
        self.state = "at_target"

    def _dock(self, params: dict):
        self._params(params, {"station_id"})
        station_id = self._identifier(params["station_id"], "station_id")
        self._require(self.state == "at_target", "Docking requires arrival acknowledgement")
        self._require(station_id == self.location, "Arrive at this station before docking")
        self.io.perform("dock_acknowledged", station_id=station_id)
        self.station_id = station_id
        self.state = "docked"

    def _prepare_transfer(self, params: dict):
        self._params(params, {"station_id", "transfer_id", "payload_id"}, {"direction"})
        station_id = self._identifier(params["station_id"], "station_id")
        transfer_id = self._identifier(params["transfer_id"], "transfer_id")
        payload_id = self._identifier(params["payload_id"], "payload_id")
        direction = params.get("direction", "load")
        self._require(self.state == "docked", "Transfer requires docking acknowledgement")
        self._require(station_id == self.station_id, "Transfer station does not match docking")
        self._require(direction in ("load", "unload"), "Direction must be load or unload")
        self._require(transfer_id not in self._used_transfer_ids, "Transfer ID already used")
        if direction == "load":
            self._require(self.payload_id is None, "Cannot load an occupied payload carrier")
        else:
            self._require(self.payload_id == payload_id, "Unload payload does not match carrier")
        transfer = {
            "station_id": station_id,
            "transfer_id": transfer_id,
            "payload_id": payload_id,
            "direction": direction,
        }
        self.io.perform("prepare_transfer", **transfer)
        self.transfer = transfer
        self._used_transfer_ids.add(transfer_id)
        self.elapsed_s = 0.0
        self.state = "transferring"

    def _confirm_transfer(self, params: dict):
        self._params(params, {"transfer_id", "payload_secured", "arm_clear"})
        transfer_id = self._identifier(params["transfer_id"], "transfer_id")
        self._require(self.state == "transferring" and self.transfer is not None, "No transfer active")
        self._require(transfer_id == self.transfer["transfer_id"], "Transfer acknowledgement mismatch")
        self._require(params["payload_secured"] is True, "Payload must be secured at its destination")
        self._require(params["arm_clear"] is True, "Arm must acknowledge clearance")
        self.io.perform("transfer_acknowledged", **self.transfer)
        self.payload_id = self.transfer["payload_id"] if self.transfer["direction"] == "load" else None
        self.transfer = None
        self.elapsed_s = 0.0
        self.state = "docked"

    def _undock(self, params: dict):
        self._params(params, {"arm_clear"})
        self._require(self.state == "docked", "Undocking requires completed docking or transfer")
        self._require(params["arm_clear"] is True, "Arm must acknowledge clearance before undocking")
        self.io.perform("undock", station_id=self.station_id, payload_id=self.payload_id)
        self.station_id = None
        self.state = "at_target"

    def _inspect(self, params: dict):
        self._params(params, {"evidence_ref"})
        evidence_ref = self._evidence(params["evidence_ref"])
        self._require(self.state == "at_target", "Inspection requires arrival acknowledgement")
        self.io.perform("inspection_acknowledged", target=self.location, evidence_ref=evidence_ref)
        self.last_evidence_ref = evidence_ref
        self.target = None
        self.state = "idle"

    def _reconcile_transfer(self, params: dict):
        self._params(params, {"payload_id", "arm_clear", "evidence_ref"})
        payload_id = params["payload_id"]
        if payload_id is not None:
            payload_id = self._identifier(payload_id, "payload_id")
        evidence_ref = self._evidence(params["evidence_ref"])
        self._require(self.state == "stopped", "Reconciliation requires stopped state")
        self._require(self.transfer_reconciliation_required, "No station interruption to reconcile")
        self._require(params["arm_clear"] is True, "Arm must acknowledge clearance before reconciliation")
        self.io.perform("payload_reconciled", payload_id=payload_id, evidence_ref=evidence_ref)
        self.payload_id = payload_id
        self.transfer = None
        self.last_evidence_ref = evidence_ref
        self.transfer_reconciliation_required = False

    def _tick(self, params: dict):
        self._params(params, {"elapsed_s"})
        elapsed_s = self._seconds(params["elapsed_s"])
        self._require(self.state != "stopped", "Reset is required before ticking a stopped controller")
        if self.state not in {"travelling", "transferring"}:
            return
        self.elapsed_s += elapsed_s
        limit = self.NAVIGATION_TIMEOUT_S if self.state == "travelling" else self.TRANSFER_TIMEOUT_S
        if self.elapsed_s >= limit:
            reason = f"{self.state} acknowledgement timed out"
            self._stop(reason)

    def _on_stop(self):
        # A stop cannot prove custody or arm clearance at a station.
        if self.station_id is not None or self.transfer is not None:
            self.transfer_reconciliation_required = True

    def _on_reset(self):
        self._require(not self.transfer_reconciliation_required, "Reconcile station payload before reset")
        self.target = None
        self.station_id = None
        self.transfer = None
        self.elapsed_s = 0.0

    def _evidence(self, value) -> str:
        self._require(
            isinstance(value, str) and bool(value.strip()) and len(value) <= 2048,
            "evidence_ref must be a nonempty string of at most 2048 characters",
        )
        return value

    def snapshot(self) -> dict:
        return {
            **super().snapshot(),
            "target": self.target,
            "location": self.location,
            "station_id": self.station_id,
            "payload_id": self.payload_id,
            "transfer": dict(self.transfer) if self.transfer is not None else None,
            "transfer_reconciliation_required": self.transfer_reconciliation_required,
            "last_evidence_ref": self.last_evidence_ref,
            "elapsed_s": self.elapsed_s,
        }
