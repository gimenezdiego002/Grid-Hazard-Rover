"""Offline mission planning and state transitions; no device or provider clients."""

from copy import deepcopy
import hashlib
import json
import re
from threading import RLock


class MissionConflict(ValueError):
    """A command conflicts with a prior action or current mission state."""


class PhysicalActionBlocked(MissionConflict):
    """This engine cannot dispatch physical actions, including reviewed ones."""


_CAPABILITIES = {"monitor", "scout", "second_view", "reviewed_response", "announce"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_OUTCOMES = {"completed", "suspected_hazard", "needs_review", "budget_refused"}
_PHYSICAL_ACTIONS = {"actuate", "move", "mitigate", "dispatch", "calibrate", "flash"}


def _identifier(value, name):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must contain 1..96 alphanumeric/._:- characters")
    return value


def default_inventory():
    """Declared demo roles, not verified hardware specifications or connections."""
    rows = [
        ("intellio-rover", "Quarky Intellio Rover", ["scout"], True),
        ("freenove-hexapod", "Freenove hexapod", ["second_view"], False),
        ("monitoring-station", "Standalone monitoring station", ["monitor"], True),
        ("learm", "Hiwonder LeArm", ["reviewed_response"], False),
        ("stackchan", "StackChan", ["announce"], True),
    ]
    return [{"device_id": device_id, "name": name, "capabilities": capabilities,
             "available": available, "simulated": True, "physical_connected": False}
            for device_id, name, capabilities, available in rows]


def _inventory(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("Inventory must contain 1..32 declared devices")
    result = []
    for row in rows:
        allowed = {"device_id", "name", "capabilities", "available", "simulated", "physical_connected"}
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError("Inventory contains unsupported fields")
        identifier = _identifier(row.get("device_id"), "device_id")
        name = row.get("name", identifier)
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or any(ord(c) < 32 for c in name):
            raise ValueError("Device name must contain 1..128 printable characters")
        capabilities = row.get("capabilities")
        if (not isinstance(capabilities, list) or not capabilities or
                any(not isinstance(c, str) or c not in _CAPABILITIES for c in capabilities) or
                len(capabilities) != len(set(capabilities))):
            raise ValueError("Device capabilities must be distinct supported demo roles")
        if type(row.get("available")) is not bool:
            raise ValueError("Device availability must be an explicit boolean")
        if row.get("simulated") is not True or row.get("physical_connected", False) is not False:
            raise ValueError("This inventory supports simulated, disconnected devices only")
        result.append({"device_id": identifier, "name": name, "capabilities": sorted(capabilities),
                       "available": row["available"], "simulated": True, "physical_connected": False})
    if len({row["device_id"] for row in result}) != len(result):
        raise ValueError("Device IDs must be unique")
    return sorted(result, key=lambda row: row["device_id"])


class MissionEngine:
    """Bounded in-memory simulator with append-only events and idempotent commands.

    State is process-local. A process restart discards missions and receipts; it
    never authorizes hardware or resumes execution. API owners provide persistence
    separately if needed. All snapshots are copies and all mutations are locked.
    """

    def __init__(self, inventory=None, *, max_missions=32, max_actions=64):
        if type(max_missions) is not int or not 1 <= max_missions <= 128:
            raise ValueError("max_missions must be 1..128")
        if type(max_actions) is not int or not 1 <= max_actions <= 256:
            raise ValueError("max_actions must be 1..256")
        self._inventory = _inventory(default_inventory() if inventory is None else inventory)
        self._missions, self._receipts = {}, {}
        self._lock = RLock()
        self._max_missions, self._max_actions = max_missions, max_actions

    def inventory(self):
        return deepcopy(self._inventory)

    def create_mission(self, mission_id, action_id, *, mode="preset", station_id="station-a",
                       target_id="inspection-area", scout_id=None, second_view=False):
        mission_id, action_id = _identifier(mission_id, "mission_id"), _identifier(action_id, "action_id")
        station_id, target_id = _identifier(station_id, "station_id"), _identifier(target_id, "target_id")
        if not isinstance(mode, str) or mode not in {"preset", "directed"} or type(second_view) is not bool:
            raise ValueError("Use preset/directed mode and a boolean second_view")
        if scout_id is not None:
            scout_id = _identifier(scout_id, "scout_id")
        command = {"action": "create", "mode": mode, "station_id": station_id,
                   "target_id": target_id, "scout_id": scout_id, "second_view": second_view}
        with self._lock:
            cached = self._replay(mission_id, action_id, command)
            if cached is not None:
                return cached
            if mission_id in self._missions:
                raise MissionConflict("Mission already exists; use a new mission ID")
            if len(self._missions) >= self._max_missions:
                raise MissionConflict("Mission capacity reached; existing state was preserved")
            mission = self._plan(mission_id, mode, station_id, target_id, scout_id, second_view)
            self._missions[mission_id] = mission
            self._receipts[mission_id] = {}
            return self._commit(mission, action_id, command, "absent")

    def _select(self, capability, selected_id=None):
        candidates = [device for device in self._inventory
                      if capability in device["capabilities"] and device["available"]]
        if selected_id is not None:
            candidates = [device for device in candidates if device["device_id"] == selected_id]
        return candidates[0] if candidates else None

    def _plan(self, mission_id, mode, station_id, target_id, scout_id, second_view):
        roles, tasks, blockers = [], [], []
        for role, required, requested, selected in (
            ("monitor", True, True, None), ("scout", True, True, scout_id),
            ("second_view", False, second_view, None), ("announce", False, True, None),
        ):
            device = self._select(role, selected) if requested else None
            reason = (f"Selected {device['device_id']}: declared {role} capability and available in simulation."
                      if device else "Optional second view was not requested." if not requested else
                      f"No available device declares {role}" + (f" with requested ID {selected}." if selected else "."))
            status = "assigned" if device else "unassigned" if required else "skipped"
            roles.append({"role": role, "device_id": device["device_id"] if device else None,
                          "status": status, "required": required, "reason": reason, "simulated": True})
            if required and device is None:
                blockers.append("missing_" + role)
            if role != "announce":
                tasks.append({"task_id": role, "role": role, "device_id": device["device_id"] if device else None,
                              "status": "pending" if device else status, "required": required,
                              "operation": "simulate_observation", "why_assigned": reason, "simulated": True,
                              "physical_action": False})
        tasks.append({"task_id": "review", "role": "human_review", "device_id": None, "status": "pending",
                      "required": True, "operation": "simulate_review_only", "simulated": True,
                      "physical_action": False, "why_assigned": "Observations require review; no automatic human approval."})
        announcer = next(role for role in roles if role["role"] == "announce")
        tasks.append({"task_id": "announce", "role": "announce", "device_id": announcer["device_id"],
                      "status": "pending" if announcer["device_id"] else "skipped", "required": False,
                      "operation": "simulate_announcement", "why_assigned": announcer["reason"],
                      "simulated": True, "physical_action": False})
        # Never convert model prose or declared availability into a manipulation task.
        roles.append({"role": "reviewed_response", "device_id": "learm" if any(
            device["device_id"] == "learm" for device in self._inventory) else None,
            "status": "blocked", "required": False, "simulated": True,
            "reason": "Physical response is disabled. LeArm remains disconnected; no mitigation task is issued."})
        return {"schema_version": "1", "mission_id": mission_id, "mode": mode,
                "preset": "water-inspection" if mode == "preset" else None,
                "station_id": station_id, "target_id": target_id,
                "status": "needs_review" if blockers else "planned", "simulated": True,
                "actuation_enabled": False, "network_requests": 0, "model_calls": 0,
                "planned_roles": roles, "proposed_tasks": tasks, "blockers": blockers,
                "suspected_hazard": False, "budget_refused": False,
                "review": {"status": "pending", "required": True, "human_review_performed": False},
                "environment_safety": "not_established", "events": []}

    def _replay(self, mission_id, action_id, command):
        receipt = self._receipts.get(mission_id, {}).get(action_id)
        if receipt is None:
            return None
        if receipt["digest"] != self._digest(command):
            raise MissionConflict("Action ID is already bound to a different command")
        return deepcopy(receipt["result"])

    @staticmethod
    def _digest(command):
        return hashlib.sha256(json.dumps(command, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode()).hexdigest()

    def _commit(self, mission, action_id, command, before):
        mission["events"].append({"sequence": len(mission["events"]) + 1, "action_id": action_id,
                                  "action": command["action"], "details": deepcopy(command),
                                  "state_before": before, "state_after": mission["status"], "simulated": True})
        result = self._snapshot(mission)
        self._receipts[mission["mission_id"]][action_id] = {"digest": self._digest(command), "result": result}
        return deepcopy(result)

    def snapshot(self, mission_id):
        _identifier(mission_id, "mission_id")
        with self._lock:
            return self._snapshot(self._missions[mission_id])

    @staticmethod
    def _next(mission):
        return next((task for task in mission["proposed_tasks"] if task["status"] == "pending"), None)

    def _snapshot(self, mission):
        result = deepcopy(mission)
        tasks = result["proposed_tasks"]
        relevant = [task for task in tasks if task["status"] != "skipped"]
        result["progress"] = {"completed": sum(task["status"] == "completed" for task in relevant),
                              "total": len(relevant), "unit": "simulated_tasks"}
        status = mission["status"]
        allowed = {"planned": ["start", "cancel"], "running": ["complete_task", "pause", "cancel"],
                   "paused": ["resume", "cancel"], "needs_review": ["simulate_review", "pause", "cancel"],
                   "completed": [], "cancelled": []}[status]
        result["allowed_actions"] = allowed
        result["next_task"] = deepcopy(self._next(mission)) if status == "running" else None
        result["outcome"] = ("needs_review" if mission["blockers"] else "suspected_hazard"
                             if mission["suspected_hazard"] else "observation_recorded"
                             if status == "completed" else "cancelled" if status == "cancelled" else "pending")
        return result

    def apply(self, mission_id, action_id, action, payload=None):
        _identifier(mission_id, "mission_id")
        _identifier(action_id, "action_id")
        if not isinstance(action, str):
            raise ValueError("Mission action must be a string")
        if action in _PHYSICAL_ACTIONS:
            raise PhysicalActionBlocked("Physical commands are always blocked by this offline engine")
        if action not in {"start", "pause", "resume", "cancel", "complete_task", "simulate_review"}:
            raise ValueError("Unsupported mission action")
        payload = {} if payload is None else payload
        if not isinstance(payload, dict):
            raise ValueError("Action payload must be an object")
        allowed_fields = ({"task_id", "outcome", "summary"} if action == "complete_task" else
                          {"decision"} if action == "simulate_review" else set())
        if set(payload) - allowed_fields:
            raise ValueError("Action payload contains unsupported fields")
        if action == "complete_task":
            _identifier(payload.get("task_id"), "task_id")
            if not isinstance(payload.get("outcome"), str) or payload["outcome"] not in _OUTCOMES:
                raise ValueError("Unsupported simulated task outcome")
            summary = payload.get("summary", "")
            if not isinstance(summary, str) or len(summary) > 500 or any(ord(c) < 32 for c in summary):
                raise ValueError("Summary must contain at most 500 printable characters")
        if action == "simulate_review" and (not isinstance(payload.get("decision"), str) or
                                             payload["decision"] not in {"acknowledge", "request_followup"}):
            raise ValueError("Simulated review decision must be acknowledge or request_followup")
        command = {"action": action, "payload": deepcopy(payload)}
        with self._lock:
            mission = self._missions[mission_id]
            cached = self._replay(mission_id, action_id, command)
            if cached is not None:
                return cached
            if len(self._receipts[mission_id]) >= self._max_actions:
                raise MissionConflict("Action capacity reached; existing events and receipts were preserved")
            if action not in self._snapshot(mission)["allowed_actions"]:
                raise MissionConflict("Action is not allowed in the current mission state")
            # Stage changes on a copy: a rejected command never partly mutates state.
            updated = deepcopy(mission)
            before = updated["status"]
            if action == "start":
                updated["status"] = "running"
            elif action == "pause":
                updated["resume_status"], updated["status"] = before, "paused"
            elif action == "resume":
                updated["status"] = updated.pop("resume_status")
            elif action == "cancel":
                updated["status"] = "cancelled"
                for task in updated["proposed_tasks"]:
                    if task["status"] in {"pending", "unassigned"}:
                        task["status"] = "cancelled"
            elif action == "complete_task":
                self._complete_task(updated, payload)
            else:
                self._review(updated, payload["decision"])
            self._missions[mission_id] = updated
            return self._commit(updated, action_id, command, before)

    def _complete_task(self, mission, payload):
        task = self._next(mission)
        if task is None or task["task_id"] != payload["task_id"] or task["role"] == "human_review":
            raise MissionConflict("Complete the next simulated observation/announcement; review is a separate action")
        outcome = payload["outcome"]
        task.update(status="needs_review" if outcome in {"needs_review", "budget_refused"} else "completed",
                    outcome=outcome, summary=payload.get("summary", ""))
        if outcome == "suspected_hazard":
            mission["suspected_hazard"] = True
        if outcome in {"needs_review", "budget_refused"}:
            mission["blockers"].append(outcome)
            mission["budget_refused"] |= outcome == "budget_refused"
            mission["status"] = "needs_review"
        else:
            next_task = self._next(mission)
            mission["status"] = "completed" if next_task is None else "needs_review" if next_task["role"] == "human_review" else "running"

    def _review(self, mission, decision):
        review_task = next(task for task in mission["proposed_tasks"] if task["role"] == "human_review")
        mission["review"]["status"] = "simulated_acknowledged" if decision == "acknowledge" else "simulated_followup_requested"
        if decision == "request_followup":
            if "followup_requested" not in mission["blockers"]:
                mission["blockers"].append("followup_requested")
            return
        # Simulated acknowledgement never releases budget/resource/follow-up blocks.
        if mission["blockers"]:
            return
        review_task["status"] = "completed"
        mission["status"] = "running" if self._next(mission) else "completed"
