"""Small, simulation-only command runtime shared by the three robot programs.

This is local application code, not the Grid Hazard Rover data contract or a
network/device protocol. Receipts and state exist for one process only.
"""

from copy import deepcopy
import math
import re
from threading import RLock


class SimulatedIO:
    """Records intended operations without opening a device, socket, or GPIO."""

    simulated = True

    def __init__(self):
        self.records = []

    def perform(self, action: str, **details) -> None:
        self.records.append({"action": action, "simulated": True, **deepcopy(details)})

    def stop(self, reason: str) -> None:
        self.perform("stop", reason=reason)


class _GuardedIO(SimulatedIO):
    """Distinguish adapter errors, including ValueError, from input rejection."""

    def __init__(self, delegate):
        self._delegate = delegate

    @property
    def records(self):
        return self._delegate.records

    def perform(self, action, **details):
        try:
            self._delegate.perform(action, **details)
        except Exception as exc:
            raise RuntimeError("Simulated IO operation failed") from exc

    def stop(self, reason):
        try:
            self._delegate.stop(reason)
        except Exception as exc:
            raise RuntimeError("Simulated IO stop failed") from exc


class RobotBase:
    MAX_COMMANDS = 256

    def __init__(self, robot_id: str, io: SimulatedIO | None = None):
        self.robot_id = self._identifier(robot_id, "robot_id")
        self.io = io if io is not None else SimulatedIO()
        if not isinstance(self.io, SimulatedIO) or self.io.simulated is not True:
            raise ValueError("Only simulated IO is supported; hardware adapters are unverified")
        self.io = _GuardedIO(self.io)
        self.state = "idle"
        self.fault = None
        self._receipts = {}
        self._lock = RLock()

    @staticmethod
    def _require(condition, message):
        if not condition:
            raise ValueError(message)

    @staticmethod
    def _params(params, required, optional=()):
        if not set(required) <= set(params) or set(params) - set(required) - set(optional):
            raise ValueError("Missing or unsupported action parameters")

    @staticmethod
    def _identifier(value, field):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value):
            raise ValueError(f"{field} must be a bounded identifier")
        return value

    @staticmethod
    def _seconds(value, field="elapsed_s"):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 3600:
            raise ValueError(f"{field} must be finite and greater than zero, at most 3600")
        return float(value)

    def snapshot(self):
        return {"robot_id": self.robot_id, "state": self.state, "fault": self.fault,
                "simulated": True, "hardware_connected": False}

    def command(self, command_id: str, action: str, **params):
        """Apply once. Reusing an ID returns its original receipt, or conflicts.

        Validation failures are rejected. Unexpected IO/program errors latch a
        stop. A full receipt cache refuses new work but always permits a stop.
        Do not connect this in-memory runtime to untrusted network commands.
        """
        self._identifier(command_id, "command_id")
        self._identifier(action, "action")
        request = {"action": action, "params": deepcopy(params)}
        with self._lock:
            if command_id in self._receipts:
                previous, receipt = self._receipts[command_id]
                self._require(previous == request, "Command ID already used for different parameters")
                if action == "stop":
                    # A retry of an old stop must stop even after an explicit reset.
                    self._stop(params.get("reason", "operator_stop"))
                    return deepcopy(self.snapshot())
                return deepcopy(receipt)
            if action != "stop" and len(self._receipts) >= self.MAX_COMMANDS:
                self._stop("command_capacity")
                raise ValueError("Command capacity reached; simulated robot stopped")
            try:
                if action == "stop":
                    self._params(params, set(), {"reason"})
                    reason = params.get("reason", "operator_stop")
                    self._identifier(reason, "reason")
                    self._stop(reason)
                elif action == "reset":
                    self._params(params, set())
                    self._require(self.state == "stopped", "Reset requires a stopped robot")
                    self._on_reset()
                    self.state, self.fault = "idle", None
                else:
                    self._handle(action, deepcopy(params))
            except ValueError:
                raise
            except Exception as exc:
                self._stop("runtime_failure")
                raise RuntimeError("Simulated robot stopped after a runtime failure") from exc
            receipt = deepcopy(self.snapshot())
            if len(self._receipts) < self.MAX_COMMANDS:
                self._receipts[command_id] = (request, receipt)
            return receipt

    def _stop(self, reason):
        self.state, self.fault = "stopped", reason
        try:
            self._on_stop()
        finally:
            self.io.stop(reason)

    def _on_stop(self):
        pass

    def _on_reset(self):
        pass

    def _handle(self, action, params):
        raise ValueError("Unsupported action")
