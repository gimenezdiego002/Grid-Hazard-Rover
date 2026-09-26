"""Simulated supervisory choices. No controller, robot transport or actuator exists here."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import time
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Observation
from .jev_pollard import validate_choice


class SupervisionFrame(BaseModel):
    """A bounded view of Relay observations, not a replacement for /shared schemas."""

    model_config = ConfigDict(extra="forbid", strict=True)
    frame_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")
    now_seconds: int = Field(ge=0)
    observations: list[Observation] = Field(default_factory=list, max_length=8)
    required_robot_ids: list[str] = Field(default_factory=lambda: ["station-a"], max_length=8)

    @model_validator(mode="after")
    def simulation_only(self):
        if any(not row.simulated for row in self.observations):
            raise ValueError("Only explicitly simulated observations are accepted")
        ids = [row.robot_id for row in self.observations]
        if len(ids) != len(set(ids)) or len(self.required_robot_ids) != len(set(self.required_robot_ids)):
            raise ValueError("A frame needs distinct robot IDs and required sources")
        if not self.required_robot_ids or any(not 1 <= len(x) <= 128 for x in self.required_robot_ids):
            raise ValueError("At least one bounded required source is necessary")
        return self


@dataclass(frozen=True)
class SupervisorLimits:
    max_age_seconds: int = 5
    deadline_seconds: float = 5.0
    max_decisions: int = 6
    max_escalations: int = 2

    def __post_init__(self):
        if type(self.max_age_seconds) is not int or not 1 <= self.max_age_seconds <= 30:
            raise ValueError("Freshness must be 1..30 seconds")
        if not isinstance(self.deadline_seconds, (int, float)) or not 0 < self.deadline_seconds <= 10:
            raise ValueError("Decision deadline must be positive and at most 10 seconds")
        if type(self.max_decisions) is not int or not 0 <= self.max_decisions <= 20:
            raise ValueError("Decision limit must be 0..20")
        if type(self.max_escalations) is not int or not 0 <= self.max_escalations <= 5:
            raise ValueError("Escalation limit must be 0..5")


class RelaySupervisor:
    """Finite event-driven simulator; local alarm is latched for the whole mission.

    Provider answers are suggestions. Every accepted choice is only a simulated
    receipt. A future hardware integration needs an independent, continuously
    running controller/watchdog; this Python workflow is not a real-time stop.
    """

    def __init__(self, mission_id: str, *, strategy: Literal["rules", "gemini", "hybrid"] = "hybrid",
                 jev=None, gemini=None, limits=None, clock: Callable[[], float] = time.monotonic):
        if strategy not in {"rules", "gemini", "hybrid"}:
            raise ValueError("Unknown strategy")
        if not isinstance(mission_id, str) or not 1 <= len(mission_id) <= 80:
            raise ValueError("A bounded mission ID is required")
        self.mission_id, self.strategy = mission_id, strategy
        self.jev, self.gemini = jev, gemini
        self.limits, self.clock = limits or SupervisorLimits(), clock
        self.local_alarm = False
        self.decisions = self.escalations = 0
        self._last_signature = None
        self._seen = {}
        self._last_now = -1
        self._cloud_stopped = False
        self._budget_refusal_reason = None

    @property
    def cloud_work_stopped(self):
        return self._cloud_stopped

    def observe(self, frame: SupervisionFrame | dict) -> dict:
        frame = SupervisionFrame.model_validate(frame)
        # Ground truth participates neither in identity nor any provider input.
        identity_data = frame.model_dump(exclude={"observations": {"__all__": {"ground_truth_hazard"}}})
        digest = hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest()
        if frame.frame_id in self._seen:
            previous_digest, previous = self._seen[frame.frame_id]
            if digest != previous_digest:
                raise ValueError("Frame ID reused with different observations")
            return {**deepcopy(previous), "replayed": True, "provider_results": [],
                    "historical_action": previous["action"], "action": "hold",
                    "local_alarm": self.local_alarm, "safe_hold": True,
                    "status": "needs_review", "reason": "replay_no_new_action"}
        if frame.now_seconds < self._last_now:
            raise ValueError("Observation time moved backwards")
        if len(self._seen) >= 100:
            raise ValueError("Mission frame limit reached")
        self._last_now = frame.now_seconds
        started = self.clock()
        valid = [row for row in frame.observations if row.kind == "water"
                 and type(row.value_milli) is int and 0 <= row.value_milli <= 1000
                 and row.unit == "wetness"]
        # Even stale evidence can latch a conservative warning, never clear it.
        self.local_alarm |= any(row.value_milli >= 700 for row in valid)
        missing = not set(frame.required_robot_ids).issubset({row.robot_id for row in frame.observations})
        stale = any(not 0 <= frame.now_seconds - row.timestamp_seconds < self.limits.max_age_seconds
                    for row in frame.observations)
        unsupported = len(valid) != len(frame.observations)
        conflicting = any(row.value_milli >= 700 for row in valid) and any(row.value_milli <= 200 for row in valid)
        health = ("missing" if missing else "stale" if stale else "unsupported" if unsupported else
                  "conflicting" if conflicting else "fresh")
        safe_monitor = health == "fresh" and not self.local_alarm
        allowed = ("hold", "request_evidence", "escalate_gemini")
        if safe_monitor:
            allowed += ("continue_monitoring",)
        # Numbers/threshold decisions are computed locally, not delegated to Jev.
        state = {"health": health, "local_alarm": self.local_alarm,
                 "water_threshold_exceeded": any(row.value_milli >= 700 for row in valid),
                 "simulated": True, "actuation_enabled": False,
                 "observations": [row.evidence() for row in frame.observations]}
        signature = (health, self.local_alarm, tuple(sorted((row.robot_id, row.kind,
                      None if row.value_milli is None else "wet" if row.value_milli >= 700 else
                      "dry" if row.value_milli <= 200 else "intermediate") for row in frame.observations)))
        changed = signature != self._last_signature
        self._last_signature = signature
        state["changed"] = changed
        result = {"frame_id": frame.frame_id, "health": health, "local_alarm": self.local_alarm,
                  "safe_hold": not safe_monitor, "action": "hold" if not safe_monitor else "continue_monitoring",
                  "status": "needs_review" if not safe_monitor else "monitoring",
                  "reason": "local_policy", "changed": changed, "allowed_actions": list(allowed),
                  "unsafe_action_rejections": 0, "provider_results": [], "simulated": True,
                  "physical_action": False, "actuation_enabled": False, "replayed": False}
        if health in {"missing", "stale", "unsupported"}:
            result["reason"] = "unusable_observations"
        elif self._cloud_stopped:
            result.update(action="hold", safe_hold=True, status="needs_review", reason="provider_work_stopped")
        elif self._budget_refusal_reason is not None:
            result.update(action="hold", safe_hold=True, status="needs_review", reason=self._budget_refusal_reason)
        elif not changed:
            result["reason"] = "unchanged_state_no_cloud_work"
        elif self.strategy == "rules":
            result["reason"] = "deterministic_rules"
        elif self.decisions >= self.limits.max_decisions:
            # A refusal needs review even when subsequent fresh frames have the
            # same engineered state. An unchanged healthy frame by itself does
            # not require another decision or consume the remaining allowance.
            self._budget_refusal_reason = "decision_budget_exhausted"
            result.update(action="hold", safe_hold=True, status="needs_review", reason="decision_budget_exhausted")
        else:
            self.decisions += 1
            choice = "escalate_gemini"
            if self.strategy == "hybrid":
                try:
                    if self.jev is None:
                        raise ValueError("No supervisor provider")
                    response = self.jev.decide(json.dumps(state, sort_keys=True, separators=(",", ":")), allowed,
                                               f"{self.mission_id}:{frame.frame_id}:jev:attempt-0",
                                               timeout_seconds=self.limits.deadline_seconds)
                    response = response.as_dict() if hasattr(response, "as_dict") else response
                    result["provider_results"].append(response)
                    choice = response.get("choice") if response.get("status") == "completed" else None
                    if choice is None:
                        self._cloud_stopped = True
                        result["reason"] = response.get("reason", "provider_failure")
                except Exception:
                    choice = None
                    self._cloud_stopped = True
                    result["reason"] = "provider_or_accounting_failure"
                    result["provider_results"].append({"status": "unknown", "choice": None,
                        "reason": "provider_or_accounting_failure", "simulated": True,
                        "metrics": {"calls": 1, "dispatches": None, "input_tokens": None,
                                    "output_tokens": None, "estimated_usd": None,
                                    "basis": "unconfirmed_provider_invocation"}})
            elapsed = max(0, self.clock() - started)
            oldest = min(row.timestamp_seconds for row in frame.observations)
            admission = validate_choice(choice, allowed, oldest, frame.now_seconds + elapsed,
                                        self.limits.max_age_seconds,
                                        deadline_expired=elapsed >= self.limits.deadline_seconds,
                                        request_id=frame.frame_id)
            if not admission.accepted:
                self._cloud_stopped = True
                result.update(action="hold", safe_hold=True, status="needs_review")
                if choice is not None:
                    result["unsafe_action_rejections"] += 1
                    result["reason"] = admission.reason
            else:
                result["action"] = choice
                result["reason"] = "validated_supervisory_choice"
                if choice == "escalate_gemini":
                    self._escalate(frame, result, started)
                elif choice in {"hold", "request_evidence"}:
                    result.update(safe_hold=True, status="needs_review")
        result["latency_ms"] = round(max(0, self.clock() - started) * 1000, 3)
        self._seen[frame.frame_id] = (digest, deepcopy(result))
        return result

    def _escalate(self, frame, result, started):
        remaining = self.limits.deadline_seconds - max(0, self.clock() - started)
        if self.escalations >= self.limits.max_escalations or remaining <= 0:
            self._budget_refusal_reason = "escalation_budget_exhausted"
            result.update(action="hold", safe_hold=True, status="needs_review", reason="escalation_budget_exhausted")
            return
        self.escalations += 1
        try:
            if self.gemini is None:
                raise ValueError("No evidence provider")
            response = self.gemini.run("evidence", {"observations": [row.evidence() for row in frame.observations]},
                                       f"{self.mission_id}:{frame.frame_id}:evidence:attempt-0",
                                       timeout_seconds=remaining)
            result["provider_results"].append(response)
            elapsed = max(0, self.clock() - started)
            expired = elapsed >= self.limits.deadline_seconds or any(
                frame.now_seconds + elapsed - row.timestamp_seconds >= self.limits.max_age_seconds
                for row in frame.observations)
            evidence = response.get("evidence") or {}
            if expired or response.get("status") != "completed" or evidence.get("status") not in {"clear", "suspected_hazard"}:
                self._cloud_stopped |= expired or response.get("status") != "completed"
                result.update(action="hold", safe_hold=True, status="needs_review",
                              reason="deadline_or_evidence_unavailable" if expired else "evidence_needs_review")
            elif evidence.get("status") == "suspected_hazard":
                self.local_alarm = True
                result.update(local_alarm=True, safe_hold=True, status="needs_review")
            # A model's 'clear' never clears local warnings or authorizes movement.
        except Exception:
            self._cloud_stopped = True
            result["provider_results"].append({"status": "unknown", "provider": "Gemini",
                "reason": "evidence_provider_failure", "estimated_usd": None,
                "usage": {"calls": 1, "input_tokens": None, "output_tokens": None,
                          "basis": "unconfirmed_provider_invocation"}})
            result.update(action="hold", safe_hold=True, status="needs_review", reason="evidence_provider_failure")
