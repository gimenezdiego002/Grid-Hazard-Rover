"""Finite patrol and directed inspection logic; sensor inputs are synthetic.

No PictoBlox module import or hardware API is guessed here. A scan is one
explicit sensor sample, not an unbounded driving or model-call loop.
"""

from copy import deepcopy
from robotcode.runtime import RobotBase


class RoverController(RobotBase):
    def __init__(self, robot_id="rover-1", io=None, minimum_clearance_cm=25, lease_s=30):
        super().__init__(robot_id, io)
        self.minimum_clearance_cm = self._seconds(minimum_clearance_cm, "minimum_clearance_cm")
        self.lease_s = self._seconds(lease_s, "lease_s")
        self.elapsed_s = 0.0
        self.route = []
        self.route_index = 0
        self.target = None
        self.location = None
        self.reports = []
        self.last_scan = None

    def snapshot(self):
        return {**super().snapshot(), "target": self.target, "location": self.location,
                "route": list(self.route), "route_index": self.route_index,
                "reports": deepcopy(self.reports), "elapsed_s": self.elapsed_s}

    def _on_stop(self):
        self.target = None
        self.last_scan = None

    def _on_reset(self):
        self.elapsed_s = 0.0
        self.route = []
        self.route_index = 0

    def _handle(self, action, p):
        if action == "patrol":
            self._params(p, {"waypoints"})
            self._require(self.state == "idle", "Patrol requires idle state")
            route = p["waypoints"]
            self._require(isinstance(route, list) and 1 <= len(route) <= 32,
                          "Patrol needs 1 to 32 named waypoints")
            route = [self._identifier(value, "waypoint") for value in route]
            self.route, self.route_index = route, 0
            self.target, self.state, self.elapsed_s = route[0], "patrolling", 0.0
            # Motion requires the next explicit clear sensor sample.
        elif action == "investigate":
            self._params(p, {"target"})
            target = self._identifier(p["target"], "target")
            self._require(self.state in {"idle", "patrolling", "reported", "blocked"},
                          "Directed inspection unavailable in this state")
            self.io.stop("directed_retask")
            self.target, self.state, self.elapsed_s = target, "investigating", 0.0
            self.last_scan = None
        elif action == "scan":
            self._require(self.state in {"patrolling", "investigating"}, "Scan requires an active task")
            try:
                self._params(p, {"obstacle_cm", "hazard_detected", "evidence_ref"})
                distance = self._seconds(p["obstacle_cm"], "obstacle_cm") if p["obstacle_cm"] != 0 else 0
                self._require(type(p["obstacle_cm"]) in (int, float), "Invalid clearance reading")
                self._require(type(p["hazard_detected"]) is bool, "hazard_detected must be boolean")
                evidence = self._identifier(p["evidence_ref"], "evidence_ref")
            except ValueError:
                self._stop("invalid_sensor")
                raise
            self.last_scan = {"obstacle_cm": distance, "evidence_ref": evidence}
            self.io.perform("scan", target=self.target, **self.last_scan)
            if p["hazard_detected"]:
                self.io.stop("suspected_hazard")
                self.reports.append({"report_id": f"report-{len(self.reports) + 1}",
                                     "target": self.target, "evidence_ref": evidence,
                                     "finding": "suspected_hazard", "simulated": True})
                self.state = "reported"
            elif distance < self.minimum_clearance_cm:
                self.io.stop("obstacle")
                self.state = "blocked"
            else:
                self.io.perform("move_toward", target=self.target)
        elif action == "arrive":
            self._params(p, {"target"})
            self._require(self.state in {"patrolling", "investigating"}, "Arrival requires an active task")
            self._require(p["target"] == self.target, "Arrival must match commanded target")
            self._require(self.last_scan is not None, "A clear scan is required before arrival")
            self.io.stop("waypoint_arrival")
            self.location, self.last_scan = self.target, None
            if self.state == "patrolling":
                self.route_index += 1
                if self.route_index < len(self.route):
                    self.target = self.route[self.route_index]
                else:
                    self.target, self.state = None, "idle"
            else:
                self.state = "at_target"
        elif action == "complete_inspection":
            self._params(p, {"evidence_ref"})
            self._require(self.state == "at_target", "Inspection requires confirmed arrival")
            evidence = self._identifier(p["evidence_ref"], "evidence_ref")
            self.reports.append({"report_id": f"report-{len(self.reports) + 1}",
                                 "target": self.target, "evidence_ref": evidence,
                                 "finding": "inspection_observation", "simulated": True})
            self.target, self.state = None, "reported"
        elif action == "acknowledge_report":
            self._params(p, {"report_id"})
            self._require(self.state == "reported" and self.reports[-1]["report_id"] == p["report_id"],
                          "Acknowledge the current report")
            self.state, self.target, self.last_scan = "idle", None, None
        elif action == "tick":
            self._params(p, {"elapsed_s"})
            elapsed = self._seconds(p["elapsed_s"])
            if self.state in {"patrolling", "investigating", "at_target"}:
                self.elapsed_s += elapsed
                if self.elapsed_s >= self.lease_s:
                    self._stop("mission_timeout")
        else:
            raise ValueError("Unsupported rover action")
