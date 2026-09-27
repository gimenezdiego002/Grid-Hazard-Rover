"""Finite offline two-robot kinematic rehearsal in a local metric world.

This extends robotcode.demo's synthetic mission story with A* navigation and
sample-driven accounting. It is not a dynamics, hardware, camera, model-provider,
or shared Grid Hazard Rover contract implementation. Nothing runs in background.
"""

from copy import deepcopy
from heapq import heappop, heappush
import json
import math
import re
from threading import RLock
from uuid import uuid4


class SimulatorConflict(ValueError):
    """Stale, conflicting, or currently unavailable simulator action."""


def default_world():
    return {
        "width_m": 24, "height_m": 16, "cell_size_m": 0.5,
        "coordinate_system": "local_xy_meters_not_geographic",
        "obstacles": [
            {"id": "equipment", "x": 8, "y": 6, "width": 3, "height": 5},
            {"id": "partition", "x": 14, "y": 2, "width": 2, "height": 7},
            {"id": "storage", "x": 16, "y": 13, "width": 5, "height": 1},
        ],
        "station": {"x": 3.0, "y": 12.0},
        "hazard": {"x": 20.0, "y": 11.0, "radius_m": 1.5},
        "patrol": [{"x": 9.0, "y": 3.0}, {"x": 20.0, "y": 4.0}],
    }


def point_free(world, point, radius=0.3):
    x, y = point["x"], point["y"]
    if not radius <= x <= world["width_m"] - radius or not radius <= y <= world["height_m"] - radius:
        return False
    return not any(o["x"] - radius <= x <= o["x"] + o["width"] + radius
                   and o["y"] - radius <= y <= o["y"] + o["height"] + radius
                   for o in world["obstacles"])


def segment_free(world, start, end):
    """Conservative sampled clearance finer than the navigation grid."""
    distance = math.hypot(end["x"] - start["x"], end["y"] - start["y"])
    n = max(1, math.ceil(distance / 0.05))
    return all(point_free(world, {"x": start["x"] + (end["x"] - start["x"]) * i / n,
                                  "y": start["y"] + (end["y"] - start["y"]) * i / n})
               for i in range(n + 1))


def plan_path(world, start, target):
    """Bounded four-neighbour A*, obstacle inflation and endpoint validation."""
    if not point_free(world, start) or not point_free(world, target):
        return None
    cell = world["cell_size_m"]
    first = (round(start["x"] / cell), round(start["y"] / cell))
    last = (round(target["x"] / cell), round(target["y"] / cell))
    point = lambda p: {"x": p[0] * cell, "y": p[1] * cell}
    if not segment_free(world, start, point(first)) or not segment_free(world, point(last), target):
        return None
    frontier, costs, parent = [(0, first)], {first: 0}, {}
    while frontier:
        _, here = heappop(frontier)
        if here == last:
            nodes = [here]
            while here in parent:
                here = parent[here]
                nodes.append(here)
            path = [point(node) for node in reversed(nodes)]
            if path[-1] != target:
                path.append(dict(target))
            return path
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            nxt = (here[0] + dx, here[1] + dy)
            if not point_free(world, point(nxt)) or not segment_free(world, point(here), point(nxt)):
                continue
            cost = costs[here] + 1
            if cost < costs.get(nxt, math.inf):
                costs[nxt], parent[nxt] = cost, here
                heuristic = abs(nxt[0] - last[0]) + abs(nxt[1] - last[1])
                heappush(frontier, (cost + heuristic, nxt))
    return None


class Simulator:
    """One process-local scene with bounded actions, traces, and simulated time."""

    MAX_ACTIONS = 4096
    MAX_ELAPSED_S = 1200
    SAMPLE_PERIOD_S = 2
    _identifier = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")

    def __init__(self):
        self._lock = RLock()
        self._session = uuid4().hex[:12]
        self._generation = 0
        self._reset_receipt = None
        self._reset()

    def _reset(self):
        self._generation += 1
        self.run_id = f"sim-{self._session}-{self._generation}"
        self.world = default_world()
        self.status, self.stage, self.mode = "idle", "ready", "preset"
        self.elapsed_s = self._sample_elapsed = 0.0
        self._patrol_index = 0
        self._dwell_s = 0.0
        self._receipts, self._evidence_keys = {}, set()
        self.events, self.observations = [], []
        self._event_sequence = 0
        self.review = {"required": False, "acknowledged": False,
                       "environment_safety": "not_established", "scope": "simulated_workflow_only"}
        self.arm_handoff = {"status": "awaiting_inspection", "preview_only": True,
                            "actuation_enabled": False, "physical_connected": False,
                            "commands_dispatched": 0, "proposal": None}
        self.target = {k: self.world["hazard"][k] for k in ("x", "y")}
        self.robots = [self._robot("rover", "Quarky Intellio Rover", "wheeled", 2, 2, 1.4),
                       self._robot("hexapod", "Freenove hexapod crawler", "hexapod", 2, 5, 0.8)]
        self.counters = {"observations": 0, "eligible_observations": 0, "routine_filtered": 0,
                         "duplicates_filtered": 0, "governed_requests": 0,
                         "modeled_request_allowance": 6, "budget_refused": False}
        self._event("ready", "Offline metric scene ready. All sensors and motion are simulated.")

    @staticmethod
    def _robot(identifier, name, kind, x, y, speed):
        return {"id": identifier, "name": name, "kind": kind, "x": float(x), "y": float(y),
                "home": {"x": float(x), "y": float(y)}, "heading_deg": 0.0,
                "speed_mps": speed, "battery_pct": 100.0, "distance_m": 0.0,
                "state": "idle", "payload_id": None, "target": None, "path": [],
                "trail": [{"x": float(x), "y": float(y)}], "fault": None,
                "sensors": {"source": "synthetic", "valid": True,
                            "nearest_obstacle_m": None, "hazard_signal": 0.0},
                "simulated": True, "physical_connected": False}

    def _event(self, kind, message, robot_id=None):
        self._event_sequence += 1
        self.events.append({"sequence": self._event_sequence, "time_s": round(self.elapsed_s, 2),
                            "kind": kind, "message": message, "robot_id": robot_id,
                            "simulated": True})
        self.events = self.events[-256:]

    def _allowed(self):
        actions = ["reset"]
        if self.status == "idle":
            actions += ["start", "direct"]
        if self.status == "running":
            actions += ["step", "pause", "stop", "inject_fault"]
        if self.status == "paused":
            actions += ["step", "resume", "stop", "inject_fault"]
        if self.status == "faulted":
            actions += ["clear_fault", "stop"]
        if self.status == "needs_review":
            actions += ["review", "stop"]
        return actions

    def snapshot(self):
        with self._lock:
            counters = deepcopy(self.counters)
            baseline, governed = counters["observations"], counters["governed_requests"]
            estimate = lambda n: round(n * (1800 * 0.3 + 220 * 2.5) / 1_000_000, 8)
            metrics = {**counters, "baseline_requests": baseline,
                       "avoided_requests": baseline - governed,
                       "request_reduction_pct": round(100 * (baseline - governed) / baseline, 1) if baseline else 0,
                       "baseline_input_tokens": baseline * 1800, "governed_input_tokens": governed * 1800,
                       "baseline_output_tokens": baseline * 220, "governed_output_tokens": governed * 220,
                       "baseline_estimated_cost_usd": estimate(baseline),
                       "governed_estimated_cost_usd": estimate(governed),
                       "estimated_cost_avoided_usd": estimate(baseline - governed),
                       "actual_model_calls": 0, "actual_api_cost_usd": 0, "energy_measured": False,
                       "assumptions": {"input_tokens_per_request": 1800, "output_tokens_per_request": 220,
                                       "input_usd_per_million": 0.3, "output_usd_per_million": 2.5,
                                       "label": "Illustrative assumptions; not provider pricing or measured tokens"}}
            return deepcopy({"schema_version": "1", "run_id": self.run_id, "status": self.status,
                             "stage": self.stage, "mode": self.mode, "elapsed_s": round(self.elapsed_s, 2),
                             "world": self.world, "target": self.target, "robots": self.robots,
                             "events": self.events, "observations": self.observations,
                             "metrics": metrics, "review": self.review, "arm_handoff": self.arm_handoff,
                             "allowed_actions": self._allowed(), "simulated": True,
                             "simulation_model": "2D kinematic A*; no terrain, gait, traction, dynamic robot collision, camera or energy validation",
                             "storage": "bounded_process_memory", "actuation_enabled": False,
                             "network_requests": 0, "actual_model_calls": 0, "actual_api_cost_usd": 0})

    def apply(self, run_id, action_id, action, **params):
        if not isinstance(run_id, str) or not self._identifier.fullmatch(run_id):
            raise ValueError("Invalid run ID")
        if not isinstance(action_id, str) or not self._identifier.fullmatch(action_id):
            raise ValueError("Invalid action ID")
        fields = {"start": set(), "step": {"dt_s", "steps"}, "pause": set(), "resume": set(),
                  "stop": set(), "reset": set(), "direct": {"target"},
                  "inject_fault": {"robot_id", "fault"}, "clear_fault": set(), "review": {"decision"}}
        if action not in fields or set(params) - fields[action]:
            raise ValueError("Unsupported action or action parameters")
        command = json.dumps({"action": action, **params}, sort_keys=True, allow_nan=False)
        with self._lock:
            # An exact retry never advances simulated time, including reset retries.
            if self._reset_receipt and (run_id, action_id) == self._reset_receipt[:2]:
                if command != self._reset_receipt[2]:
                    raise SimulatorConflict("Action ID already used with different arguments")
                return {**self.snapshot(), "replayed": True}
            if run_id != self.run_id:
                raise SimulatorConflict("Stale run ID; refresh the scene")
            if action_id in self._receipts:
                if self._receipts[action_id] != command:
                    raise SimulatorConflict("Action ID already used with different arguments")
                return {**self.snapshot(), "replayed": True}
            if action not in self._allowed():
                raise SimulatorConflict("Action unavailable in this state")
            if len(self._receipts) >= self.MAX_ACTIONS and action not in {"reset", "stop"}:
                raise SimulatorConflict("Run action limit reached; reset the scene")
            if action == "reset":
                self._reset_receipt = (run_id, action_id, command)
                self._reset()
                return self.snapshot()
            self._apply(action, params)
            self._receipts[action_id] = command
            return self.snapshot()

    def _apply(self, action, params):
        if action in {"start", "direct"}:
            if action == "direct":
                target = params.get("target")
                if (not isinstance(target, dict) or set(target) != {"x", "y"}
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in target.values())
                        or not point_free(self.world, target)):
                    raise ValueError("Target must be a free point inside the local world")
                if plan_path(self.world, self.robots[0], target) is None:
                    raise ValueError("Target is unreachable")
                self.target, self.mode = dict(target), "directed"
            self.status = "running"
            self.stage = "rover_patrol" if self.mode == "preset" else "rover_investigate"
            self._navigate(self.robots[0], self.world["patrol"][0] if self.mode == "preset" else self.target)
            self._event("mission_started", f"{self.mode.title()} inspection started; navigation uses local A*.")
        elif action == "step":
            dt, steps = params.get("dt_s", 0.5), params.get("steps", 1)
            if type(dt) not in (int, float) or not math.isfinite(dt) or not 0.1 <= dt <= 2:
                raise ValueError("dt_s must be 0.1..2 seconds")
            if type(steps) is not int or not 1 <= steps <= 20:
                raise ValueError("steps must be an integer 1..20")
            was_paused = self.status == "paused"
            self.status = "running"
            for _ in range(steps):
                if self.status != "running":
                    break
                self._tick(float(dt))
            if was_paused and self.status == "running":
                self.status = "paused"
        elif action == "pause":
            self.status = "paused"
            self._event("paused", "Simulation paused; no clock or motion advances.")
        elif action == "resume":
            self.status = "running"
            self._event("resumed", "Simulation resumed by explicit operator action.")
        elif action == "stop":
            self.status = "stopped"
            for robot in self.robots:
                robot["state"], robot["path"] = "stopped", []
            self._event("stopped", "Mission stopped. Reset is required for a new run.")
        elif action == "inject_fault":
            self._inject(params)
        elif action == "clear_fault":
            self.world["obstacles"] = [o for o in self.world["obstacles"] if o["id"] != "injected-barrier"]
            self.status = "paused"
            for robot in self.robots:
                if robot["fault"] == "low_battery":
                    robot["battery_pct"] = 100.0
                robot["fault"] = None
                robot["sensors"]["valid"] = True
                if robot["target"] is not None:
                    self._navigate(robot, robot["target"])
                else:
                    robot["state"] = "idle"
            if self.status == "faulted":
                self._event("recovery_blocked", "Recovery found a blocked route; fleet remains frozen.")
            else:
                self._event("fault_cleared", "Synthetic fault cleared and route replanned; explicit resume required.")
        elif action == "review":
            decision = params.get("decision")
            if decision not in {"acknowledge", "abort"}:
                raise ValueError("Review decision must be acknowledge or abort")
            if decision == "abort":
                self._apply("stop", {})
            elif self.counters["budget_refused"]:
                raise SimulatorConflict("Review cannot override the modeled allowance; reset required")
            else:
                self.review["acknowledged"] = True
                self.arm_handoff["status"] = "preview_ready"
                self.status, self.stage = "running", "return_to_station"
                self._navigate(self.robots[0], self.robots[0]["home"])
                self._navigate(self.robots[1], self.world["station"])
                self._event("review_acknowledged", "Operator acknowledged simulated evidence. Arm proposal remains preview-only.")

    def _inject(self, params):
        robot_id, fault = params.get("robot_id"), params.get("fault")
        if robot_id not in {"rover", "hexapod"} or fault not in {"blocked_path", "sensor_dropout", "low_battery", "budget_exhausted"}:
            raise ValueError("Select a known robot and supported fault")
        if fault == "budget_exhausted":
            self.counters["modeled_request_allowance"] = self.counters["governed_requests"]
            self._event("budget_exhausted", "Modeled request allowance exhausted; next novel eligible observation will require review.")
            return
        robot = next(r for r in self.robots if r["id"] == robot_id)
        robot["fault"], robot["state"] = fault, "faulted"
        if fault == "blocked_path":
            self.world["obstacles"].append({"id": "injected-barrier", "x": 12, "y": 0, "width": 0.5, "height": 16})
        if fault == "sensor_dropout":
            robot["sensors"]["valid"] = False
        if fault == "low_battery":
            robot["battery_pct"] = 5.0
        self.status = "faulted"
        self._event("fault", f"{fault.replace('_', ' ')} injected. Fleet motion frozen for recovery.", robot_id)

    def _navigate(self, robot, target):
        path = plan_path(self.world, robot, target)
        robot["target"] = dict(target)
        if path is None:
            robot["fault"], robot["state"] = "blocked_path", "faulted"
            self.status = "faulted"
            self._event("route_blocked", "No collision-free route; fleet frozen.", robot["id"])
            return
        robot["path"], robot["state"] = path, "moving"

    def _close_view_target(self):
        """Keep the two simulated bodies visible; this is not collision dynamics."""
        for dx, dy in ((-1, 0), (0, 1), (1, 0), (0, -1), (-1, -1), (1, 1)):
            candidate = {"x": self.target["x"] + dx, "y": self.target["y"] + dy}
            if point_free(self.world, candidate) and plan_path(self.world, self.robots[1], candidate) is not None:
                return candidate
        return None

    def _move(self, robot, dt):
        remaining = robot["speed_mps"] * dt
        while robot["path"] and remaining > 1e-9:
            nxt = robot["path"][0]
            dx, dy = nxt["x"] - robot["x"], nxt["y"] - robot["y"]
            distance = math.hypot(dx, dy)
            if distance < 1e-9:
                robot["path"].pop(0)
                continue
            travel = min(distance, remaining)
            position = {"x": robot["x"] + dx * travel / distance,
                        "y": robot["y"] + dy * travel / distance}
            if not segment_free(self.world, robot, position):
                robot["fault"], robot["state"], self.status = "blocked_path", "faulted", "faulted"
                self._event("route_blocked", "Obstacle intersects route; fleet motion stopped.", robot["id"])
                return
            robot.update(position)
            robot["heading_deg"] = math.degrees(math.atan2(dy, dx))
            robot["distance_m"] += travel
            robot["battery_pct"] = max(0, robot["battery_pct"] - travel * 0.03)
            remaining -= travel
            if travel >= distance - 1e-9:
                robot["path"].pop(0)
        if robot["state"] == "moving" and not robot["path"]:
            robot["state"] = "arrived"
            self._event("arrived", "Reached planned waypoint with obstacle clearance.", robot["id"])
        current = {"x": round(robot["x"], 4), "y": round(robot["y"], 4)}
        if current != robot["trail"][-1]:
            robot["trail"].append(current)
            robot["trail"] = robot["trail"][-256:]

    def _tick(self, dt):
        self.elapsed_s += dt
        if self.elapsed_s >= self.MAX_ELAPSED_S:
            self.status = "stopped"
            for robot in self.robots:
                robot["state"], robot["path"] = "stopped", []
            self._event("time_limit", "Finite simulation time limit reached; reset required.")
            return
        for robot in self.robots:
            if robot["state"] == "moving":
                self._move(robot, dt)
                if self.status != "running":
                    return
            x, y = robot["x"], robot["y"]
            distances = [min(x, y, self.world["width_m"] - x, self.world["height_m"] - y)]
            for o in self.world["obstacles"]:
                distances.append(math.hypot(max(o["x"] - x, 0, x - o["x"] - o["width"]),
                                            max(o["y"] - y, 0, y - o["y"] - o["height"])))
            hazard_distance = math.hypot(x - self.world["hazard"]["x"], y - self.world["hazard"]["y"])
            robot["sensors"].update(nearest_obstacle_m=round(min(distances), 2),
                                    hazard_signal=round(max(0, 1 - hazard_distance / 3), 3))
        self._sample_elapsed += dt
        if self._sample_elapsed >= self.SAMPLE_PERIOD_S:
            self._sample_elapsed -= self.SAMPLE_PERIOD_S
            for robot in self.robots:
                finding = "suspected_hazard" if robot["sensors"]["hazard_signal"] > 0.2 else "routine_clear"
                self._observe(robot, finding)
                if self.status != "running":
                    return
        self._advance(dt)

    def _observe(self, robot, finding):
        self.counters["observations"] += 1
        eligible = finding != "routine_clear"
        decision = "routine_filtered"
        key = f"{robot['id']}:{finding}"
        if eligible:
            self.counters["eligible_observations"] += 1
            if key in self._evidence_keys:
                decision = "duplicates_filtered"
                self.counters[decision] += 1
            elif self.counters["governed_requests"] >= self.counters["modeled_request_allowance"]:
                decision = "budget_refused"
                self.counters["budget_refused"] = True
                self.status = "needs_review"
                self.review.update(required=True, reason="budget_refused")
                self._event("budget_refused", "Novel evidence exceeded the modeled request allowance. No model was called.", robot["id"])
            else:
                decision = "modeled_request"
                self._evidence_keys.add(key)
                self.counters["governed_requests"] += 1
                self._event("evidence", f"{finding.replace('_', ' ')}: one modeled inference request; no API call.", robot["id"])
        else:
            self.counters["routine_filtered"] += 1
        self.observations.append({"sequence": self.counters["observations"], "time_s": round(self.elapsed_s, 2),
                                  "robot_id": robot["id"], "finding": finding, "decision": decision,
                                  "simulated": True, "evidence_key": key})
        self.observations = self.observations[-64:]

    def _advance(self, dt):
        rover, hexapod = self.robots
        if self.stage == "rover_patrol" and rover["state"] == "arrived":
            self._patrol_index += 1
            if self._patrol_index < len(self.world["patrol"]):
                self._navigate(rover, self.world["patrol"][self._patrol_index])
            else:
                self.stage = "rover_investigate"
                self._navigate(rover, self.target)
        elif self.stage == "rover_investigate" and rover["state"] == "arrived":
            finding = "suspected_hazard" if rover["sensors"]["hazard_signal"] > 0.2 else "directed_inspection"
            self._observe(rover, finding)
            if self.status != "running":
                return
            rover["state"] = "observing"
            self.stage = "hexapod_to_station"
            self._navigate(hexapod, self.world["station"])
            self._event("carrier_dispatched", "Scout evidence requests a kit-equipped close view; crawler sent to station.")
        elif self.stage == "hexapod_to_station" and hexapod["state"] == "arrived":
            self.stage, self._dwell_s, hexapod["state"] = "station_kit_pickup", 0, "docked"
            self._event("synthetic_dock", "Crawler docked in simulation. Kit transfer is a synthetic acknowledgement.", "hexapod")
        elif self.stage == "station_kit_pickup":
            self._dwell_s += dt
            if self._dwell_s >= 3:
                hexapod["payload_id"] = "inspection-kit"
                self.stage = "hexapod_close_inspection"
                close_view = self._close_view_target()
                if close_view is None:
                    self.status, hexapod["state"], hexapod["fault"] = "faulted", "faulted", "blocked_path"
                    self._event("route_blocked", "No free stand-off point for crawler inspection; fleet frozen.", "hexapod")
                    return
                self._navigate(hexapod, close_view)
                self._event("synthetic_transfer", "Simulated kit loaded and arm clearance acknowledged. No arm command sent.", "hexapod")
        elif self.stage == "hexapod_close_inspection" and hexapod["state"] == "arrived":
            self._observe(hexapod, "close_inspection")
            if self.status != "running":
                return
            from .arm_handoff import build_arm_handoff
            self.arm_handoff["proposal"] = build_arm_handoff(
                event_id=f"inspection-{self.run_id}", mission_id=self.run_id,
                source_id="freenove-hexapod", station_id="station-a",
                evidence_ref=f"sim://{self.run_id}/close-inspection", simulated=True)
            self.arm_handoff["status"] = "needs_review"
            self.review.update(required=True, reason="inspection_complete")
            self.status, self.stage, hexapod["state"] = "needs_review", "human_review", "awaiting_review"
            self._event("review_required", "Close inspection complete. Operator review is required; arm proposal is preview-only.")
        elif self.stage == "return_to_station" and all(r["state"] == "arrived" for r in self.robots):
            hexapod["payload_id"] = None
            hexapod["state"], rover["state"] = "docked", "idle"
            self.status, self.stage = "completed", "completed"
            self._event("completed", "Rover returned home; crawler returned kit to station in simulation. No physical actions occurred.")
