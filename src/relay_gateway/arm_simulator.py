"""Independent virtual arm rehearsal. No hardware, transport, or model imports.

Angles, dimensions, and poses are illustrative. These records are deliberately
incompatible with physical LeArm pulse recordings and carry no calibration claim.
"""

from copy import deepcopy
import json
import math
import re
from threading import RLock
from uuid import uuid4


class ArmSimulatorConflict(ValueError):
    """A stale, repeated-with-different-content, or unavailable action."""


HOME = [90.0, 60.0, 60.0, 90.0, 90.0, 20.0]
PICK = [35.0, 15.0, 105.0, 60.0, 90.0, 20.0]
PLACE = [145.0, 15.0, 105.0, 60.0, 90.0, 20.0]


def preset_routine():
    """Virtual poses only; degrees are not servo pulses or calibrated limits."""
    return [
        {"name": "home", "joints_deg": list(HOME), "duration_s": 1.0},
        {"name": "approach_marker", "joints_deg": list(PICK), "duration_s": 2.0},
        {"name": "grasp_marker", "joints_deg": [*PICK[:5], 110.0], "duration_s": 1.0},
        {"name": "lift_marker", "joints_deg": [35.0, 60.0, 60.0, 90.0, 90.0, 110.0], "duration_s": 2.0},
        {"name": "carry_marker", "joints_deg": [145.0, 60.0, 60.0, 90.0, 90.0, 110.0], "duration_s": 3.0},
        {"name": "lower_marker", "joints_deg": [*PLACE[:5], 110.0], "duration_s": 2.0},
        {"name": "release_marker", "joints_deg": list(PLACE), "duration_s": 1.0},
        {"name": "return_home", "joints_deg": list(HOME), "duration_s": 2.0},
    ]


def link_positions(joints):
    """Illustrative three-link forward kinematics, local meters, base yaw + pitch."""
    yaw = math.radians(joints[0] - 90)
    pitch = math.radians(joints[1])
    radial, height = 0.0, 0.10
    result = [{"x": 0.0, "y": 0.0, "z": height}]
    for index, length in enumerate((0.28, 0.24, 0.12)):
        if index:
            pitch += math.radians(joints[index + 1] - 90)
        radial += length * math.cos(pitch)
        height += length * math.sin(pitch)
        result.append({"x": round(radial * math.cos(yaw), 6),
                       "y": round(radial * math.sin(yaw), 6), "z": round(height, 6)})
    return result


def _pose(joints_deg, duration_s=2.0, name="taught_pose"):
    if (type(joints_deg) is not list or len(joints_deg) != 6
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 180 for v in joints_deg)):
        raise ValueError("Provide six finite virtual angles between 0 and 180 degrees")
    if type(duration_s) not in (int, float) or not math.isfinite(duration_s) or not 0.5 <= duration_s <= 10:
        raise ValueError("duration_s must be 0.5..10 simulated seconds")
    if not isinstance(name, str) or not 1 <= len(name) <= 64 or any(ord(c) < 32 for c in name):
        raise ValueError("Pose name must contain 1..64 printable characters")
    return {"name": name, "joints_deg": [float(v) for v in joints_deg], "duration_s": float(duration_s)}


class ArmSimulator:
    MAX_ACTIONS = 4096
    MAX_RECORDED_POSES = 20
    MAX_ROUTINE_S = 180
    MAX_ELAPSED_S = 600
    _identifier = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")

    def __init__(self):
        self._lock = RLock()
        self._session, self._generation = uuid4().hex[:12], 0
        self._reset_receipt = None
        self._reset()

    def _reset(self):
        self._generation += 1
        self.run_id = f"arm-sim-{self._session}-{self._generation}"
        self.status, self.stage, self.mode = "idle", "ready", "preset"
        self.elapsed_s, self._waypoint_elapsed = 0.0, 0.0
        self.joints_deg = list(HOME)
        self.routine, self.recorded_routine = preset_routine(), []
        self.current_waypoint, self.repeat_index, self.repeats = 0, 1, 1
        self._segment_start = list(HOME)
        self._receipts, self.events = {}, []
        self._event_sequence = 0
        self.fault = None
        self._fault_payload = None
        self.payload = {"state": "at_source", "position": link_positions(PICK)[-1]}
        self._event("ready", "Virtual arm ready. Angles and dimensions are illustrative, not calibrated LeArm settings.")

    def _event(self, kind, message):
        self._event_sequence += 1
        self.events.append({"sequence": self._event_sequence, "time_s": round(self.elapsed_s, 3),
                            "kind": kind, "message": message, "simulated": True})
        self.events = self.events[-128:]

    def _allowed(self):
        actions = ["reset"]
        if self.status in {"idle", "completed"}:
            actions += ["start", "pose", "capture", "clear_recording"]
            if self.recorded_routine:
                actions.append("replay")
        if self.status == "running":
            actions += ["pause", "step", "stop", "inject_fault"]
        if self.status == "paused":
            actions += ["resume", "step", "stop", "inject_fault", "capture", "clear_recording"]
        if self.status == "faulted":
            actions += ["clear_fault", "stop"]
        return actions

    def snapshot(self):
        with self._lock:
            links = link_positions(self.joints_deg)
            openness = max(0.0, min(1.0, (110 - self.joints_deg[5]) / 90))
            duration = self.routine[self.current_waypoint]["duration_s"]
            partial = min(1.0, self._waypoint_elapsed / duration)
            total = sum(p["duration_s"] for p in self.routine) * self.repeats
            progress = ((self.repeat_index - 1) * sum(p["duration_s"] for p in self.routine)
                        + sum(p["duration_s"] for p in self.routine[:self.current_waypoint])
                        + min(duration, self._waypoint_elapsed)) / total
            if self.status == "idle":
                progress = 0.0
            return deepcopy({
                "schema_version": "arm-simulation/1", "run_id": self.run_id,
                "source": "simulation", "simulated": True, "status": self.status, "stage": self.stage,
                "mode": self.mode, "elapsed_s": round(self.elapsed_s, 3),
                "joints_deg": self.joints_deg, "joint_names": ["base", "shoulder", "elbow", "wrist_pitch", "wrist_roll", "gripper"],
                "angle_unit": "degrees", "routine": self.routine, "recorded_routine": self.recorded_routine,
                "recording": {"schema_version": "arm-simulation/1", "recording_kind": "simulated_joint_angles",
                              "angle_unit": "degrees", "poses": self.recorded_routine,
                              "simulated": True, "actuation_enabled": False},
                "current_waypoint": self.current_waypoint, "repeat_index": self.repeat_index,
                "repeats": self.repeats, "progress": round(min(1.0, progress), 6),
                "waypoint_progress": round(partial, 6), "payload": self.payload,
                "gripper": {"open_fraction": round(openness, 6),
                            "state": "open" if openness >= 0.85 else "closed" if openness <= 0.15 else "moving"},
                "end_effector": links[-1], "link_positions": links,
                "stations": {"source": link_positions(PICK)[-1], "destination": link_positions(PLACE)[-1]},
                "fault": self.fault, "events": self.events, "allowed_actions": self._allowed(),
                "physical_connected": False, "actuation_enabled": False, "commands_dispatched": 0,
                "physical_result": None, "model_calls": 0, "network_requests": 0, "api_cloud_cost_usd": 0,
                "simulation_model": "Illustrative joint-angle interpolation and forward kinematics; no calibration, dynamics, collisions, load, physical contact or grip validation",
                "storage": "bounded_process_memory",
            })

    def apply(self, run_id, action_id, action, **params):
        for value in (run_id, action_id):
            if not isinstance(value, str) or not self._identifier.fullmatch(value):
                raise ValueError("Run and action IDs must be bounded identifiers")
        fields = {"start": {"repeats"}, "pose": {"joints_deg", "duration_s"},
                  "capture": {"name", "duration_s"}, "replay": {"repeats"}, "clear_recording": set(),
                  "step": {"dt_s", "steps"}, "pause": set(), "resume": set(), "stop": set(),
                  "reset": set(), "inject_fault": {"fault"}, "clear_fault": set()}
        if not isinstance(action, str) or action not in fields or set(params) - fields[action]:
            raise ValueError("Unsupported virtual arm action or action parameters")
        command = json.dumps({"action": action, **params}, sort_keys=True, allow_nan=False)
        with self._lock:
            if self._reset_receipt and (run_id, action_id) == self._reset_receipt[:2]:
                if command != self._reset_receipt[2]:
                    raise ArmSimulatorConflict("Action ID is already bound to different arguments")
                return {**self.snapshot(), "replayed": True}
            if run_id != self.run_id:
                raise ArmSimulatorConflict("Stale virtual arm run; refresh state")
            if action_id in self._receipts:
                if command != self._receipts[action_id]:
                    raise ArmSimulatorConflict("Action ID is already bound to different arguments")
                return {**self.snapshot(), "replayed": True}
            if action not in self._allowed():
                raise ArmSimulatorConflict("Action unavailable in the current virtual arm state")
            if len(self._receipts) >= self.MAX_ACTIONS and action not in {"stop", "reset"}:
                raise ArmSimulatorConflict("Virtual arm action limit reached; reset required")
            if action == "reset":
                self._reset_receipt = (run_id, action_id, command)
                self._reset()
                return self.snapshot()
            self._apply(action, params)
            self._receipts[action_id] = command
            return self.snapshot()

    def _begin(self, routine, mode, repeats):
        if type(repeats) is not int or not 1 <= repeats <= 5:
            raise ValueError("repeats must be an integer from 1 to 5")
        if not routine or sum(p["duration_s"] for p in routine) * repeats > self.MAX_ROUTINE_S:
            raise ValueError("Virtual routine must contain poses and last at most 180 simulated seconds")
        self.routine, self.mode, self.repeats = deepcopy(routine), mode, repeats
        self.current_waypoint, self.repeat_index, self._waypoint_elapsed = 0, 1, 0.0
        self._segment_start, self.status = list(self.joints_deg), "running"
        self.stage = self.routine[0]["name"]
        if mode == "preset":
            self.payload = {"state": "at_source", "position": link_positions(PICK)[-1]}
        self._event("routine_started", f"{mode.title()} virtual routine started ({repeats} repetition(s)); no device command sent.")

    def _apply(self, action, params):
        if action == "start":
            self._begin(preset_routine(), "preset", params.get("repeats", 1))
        elif action == "pose":
            self._begin([_pose(params.get("joints_deg"), params.get("duration_s", 2), "manual_pose")], "manual", 1)
        elif action == "capture":
            pose = _pose(self.joints_deg, params.get("duration_s", 2),
                         params.get("name", f"pose-{len(self.recorded_routine) + 1}"))
            if len(self.recorded_routine) >= self.MAX_RECORDED_POSES:
                raise ArmSimulatorConflict("Virtual recording holds at most 20 poses")
            self.recorded_routine.append(pose)
            self._event("pose_captured", f"Captured {pose['name']} as illustrative joint angles, not hardware pulse targets.")
        elif action == "replay":
            self._begin(self.recorded_routine, "recorded", params.get("repeats", 1))
        elif action == "clear_recording":
            self.recorded_routine = []
            self._event("recording_cleared", "Captured virtual poses cleared; active trajectory preserved.")
        elif action == "step":
            dt, steps = params.get("dt_s", 0.25), params.get("steps", 1)
            if type(dt) not in (int, float) or not math.isfinite(dt) or not 0.1 <= dt <= 2:
                raise ValueError("dt_s must be 0.1..2 simulated seconds")
            if type(steps) is not int or not 1 <= steps <= 20:
                raise ValueError("steps must be an integer from 1 to 20")
            paused = self.status == "paused"
            self.status = "running"
            for _ in range(steps):
                if self.status != "running":
                    break
                self._tick(float(dt))
            if paused and self.status == "running":
                self.status = "paused"
        elif action in {"pause", "resume", "stop"}:
            self.status = {"pause": "paused", "resume": "running", "stop": "stopped"}[action]
            self._event(action, f"Virtual arm {self.status}; no physical actuator is connected.")
        elif action == "inject_fault":
            fault = params.get("fault")
            if fault not in {"joint_stall", "grip_loss"}:
                raise ValueError("Choose joint_stall or grip_loss")
            self._fault_payload = deepcopy(self.payload)
            self.fault, self.status = fault, "faulted"
            if fault == "grip_loss":
                self.payload = {"state": "dropped", "position": link_positions(self.joints_deg)[-1]}
            self._event("fault", f"Synthetic {fault.replace('_', ' ')} injected; trajectory frozen for explicit recovery.")
        elif action == "clear_fault":
            if self.fault == "grip_loss":
                self.payload = deepcopy(self._fault_payload)
            self.fault, self.status, self._fault_payload = None, "paused", None
            self._event("fault_cleared", "Virtual fault cleared and pre-fault virtual payload restored. Explicit resume required.")

    def _sync_payload(self):
        position = link_positions(self.joints_deg)[-1]
        openness = max(0, min(1, (110 - self.joints_deg[5]) / 90))
        distance = lambda a, b: math.sqrt(sum((a[k] - b[k]) ** 2 for k in ("x", "y", "z")))
        if self.payload["state"] == "at_source" and openness <= 0.15 and distance(position, self.payload["position"]) < 0.08:
            self.payload = {"state": "held", "position": position}
            self._event("virtual_grasp", "Virtual marker attached using a proximity fixture; no physical grip was measured.")
        elif self.payload["state"] == "held":
            self.payload["position"] = position
            if openness >= 0.85:
                placed = distance(position, link_positions(PLACE)[-1]) < 0.08
                self.payload["state"] = "placed" if placed else "dropped"
                self._event("virtual_release", f"Virtual marker {self.payload['state']}; this is a simulated fixture result.")

    def _tick(self, dt):
        remaining = dt
        while remaining > 1e-9 and self.status == "running":
            pose = self.routine[self.current_waypoint]
            consume = min(remaining, pose["duration_s"] - self._waypoint_elapsed,
                          max(0, self.MAX_ELAPSED_S - self.elapsed_s))
            self._waypoint_elapsed += consume
            self.elapsed_s += consume
            remaining -= consume
            fraction = min(1.0, self._waypoint_elapsed / pose["duration_s"])
            smooth = fraction * fraction * (3 - 2 * fraction)
            self.joints_deg = [start + (target - start) * smooth
                               for start, target in zip(self._segment_start, pose["joints_deg"])]
            self._sync_payload()
            if self.elapsed_s >= self.MAX_ELAPSED_S:
                self.status = "stopped"
                self._event("time_limit", "Finite virtual session limit reached; reset required.")
                return
            if fraction >= 1:
                self._event("waypoint_reached", f"Reached virtual pose {pose['name']}.")
                if self.current_waypoint + 1 < len(self.routine):
                    self.current_waypoint += 1
                elif self.repeat_index < self.repeats:
                    self.repeat_index += 1
                    self.current_waypoint = 0
                    if self.mode == "preset":
                        self.payload = {"state": "at_source", "position": link_positions(PICK)[-1]}
                    self._event("repeat", f"Beginning virtual repetition {self.repeat_index}.")
                else:
                    self.status, self.stage = "completed", "completed"
                    self._event("completed", "Virtual routine completed. Physical result remains unverified; no device commands sent.")
                    return
                self._waypoint_elapsed = 0.0
                self._segment_start = list(self.joints_deg)
                self.stage = self.routine[self.current_waypoint]["name"]
