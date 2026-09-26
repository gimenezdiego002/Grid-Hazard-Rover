"""Finite three-arm comparison on identical labeled synthetic observations."""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.metadata
import json

from .jev_gemini import FixtureGeminiRoles
from .jev_provider import FixtureJevProvider
from .jev_supervisor import RelaySupervisor, SupervisionFrame, SupervisorLimits


def synthetic_missions():
    def observation(event_id, value, timestamp=10, *, robot="station-a", truth=False, **extra):
        return {"event_id": event_id, "robot_id": robot, "kind": "water", "value_milli": value,
                "unit": "wetness", "timestamp_seconds": timestamp, "simulated": True,
                "ground_truth_hazard": truth, **extra}

    def frame(name, rows, now=10):
        return {"frame_id": name, "now_seconds": now, "observations": rows}

    def mission(name, frames, fault=None):
        return {"mission_id": name, "text": "Inspect this simulated area for water; retain uncertain findings for review.",
                "frames": frames, "fault": fault}

    return [
        mission("dry_monitoring", [frame(f"dry-{i}", [observation(f"dry-{i}", 100, i)], i) for i in (10, 11, 12)]),
        mission("wet_episode", [frame("dry", [observation("dry", 100)]),
                                frame("wet", [observation("wet", 850, 11, truth=True)], 11),
                                frame("wet-repeat", [observation("wet-repeat", 900, 12, truth=True)], 12)]),
        mission("conflicting", [frame("conflict", [observation("wet", 850, truth=True),
                                observation("dry-scout", 100, robot="scout", truth=True)])]),
        mission("missing", [frame("missing", [])]),
        mission("stale", [frame("stale", [observation("stale", 850, 1, truth=True)])]),
        mission("future", [frame("future", [observation("future", 850, 11, truth=True)])]),
        mission("unsupported", [frame("gas", [observation("gas", None, kind="gas", unit=None, truth=True)])]),
        mission("sensor_blind_spot", [frame("blind", [observation("blind", 100, truth=True)])]),
        *[mission(name, [frame(name, [observation(name, 850, truth=True)])], name)
          for name in ("invalid_choice", "deadline_expiry", "network_failure", "budget_exhaustion")],
    ]


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _FaultJev:
    def __init__(self, base, fault, clock):
        self.base, self.fault, self.clock = base, fault, clock

    def decide(self, *args, **kwargs):
        if self.fault == "network_failure":
            return {"choice": None, "status": "unknown", "reason": "injected_network_failure", "simulated": True,
                    "metrics": {"calls": 1, "input_tokens": None, "output_tokens": None, "estimated_usd": None}}
        result = self.base.decide(*args, **kwargs)
        result = result.as_dict() if hasattr(result, "as_dict") else result
        if self.fault == "invalid_choice":
            result.update(choice="drive_forward", confidence=1.0)
        if self.fault == "deadline_expiry":
            self.clock.now += 6
        return result


class _FaultGemini:
    def __init__(self, base, fault, clock):
        self.base, self.fault, self.clock = base, fault, clock

    def run(self, role, *args, **kwargs):
        if role == "evidence" and self.fault == "network_failure":
            return {"status": "unknown", "reason": "injected_network_failure", "evidence": {},
                    "usage": {"calls": 1, "input_tokens": None, "output_tokens": None}, "estimated_usd": None,
                    "simulated": True, "inference_simulated": True}
        result = self.base.run(role, *args, **kwargs)
        if role == "evidence" and self.fault == "invalid_choice":
            result.update(status="failed", evidence={"status": "needs_review"}, reason="injected_invalid_response")
        if role == "evidence" and self.fault == "deadline_expiry":
            self.clock.now += 6
        return result


def _account(results):
    metrics = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "known_estimated_usd": Decimal(0),
               "unknown_usage_calls": 0, "gemini_calls": 0, "jev_calls": 0}
    for result in results:
        is_jev = "metrics" in result
        usage = result.get("metrics", result.get("usage", {}))
        calls = usage.get("calls", 0)
        metrics["calls"] += calls
        metrics["jev_calls" if is_jev else "gemini_calls"] += calls
        if calls and (usage.get("input_tokens") is None or usage.get("output_tokens") is None):
            metrics["unknown_usage_calls"] += calls
        for key in ("input_tokens", "output_tokens"):
            metrics[key] += usage.get(key) or 0
        amount = usage.get("estimated_usd") if is_jev else result.get("estimated_usd")
        if amount is not None:
            metrics["known_estimated_usd"] += Decimal(str(amount))
    metrics["known_estimated_usd"] = format(metrics["known_estimated_usd"], "f")
    metrics["estimated_usd"] = None if metrics["unknown_usage_calls"] else metrics["known_estimated_usd"]
    metrics.update(provider_reported_cost_usd=None, actual_paid_usd="0.000000", total_tokens=metrics["input_tokens"] + metrics["output_tokens"])
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        metrics["known_" + key] = metrics[key]
        if metrics["unknown_usage_calls"]:
            metrics[key] = None
    return metrics


def run_mission(mission, strategy, *, jev=None, gemini=None, fixture=True):
    """Both model arms use the same event trigger and safety gate; no polling baseline."""
    mission = deepcopy(mission)
    frames = [SupervisionFrame.model_validate(row) for row in mission["frames"]]
    if not 1 <= len(frames) <= 20:
        raise ValueError("A comparison mission requires 1..20 frames")
    if not fixture and mission.get("fault"):
        raise ValueError("Fault injection is fixture-only")
    if fixture and ((gemini is not None and getattr(gemini, "inference_simulated", True) is not True) or
                    (jev is not None and getattr(jev, "simulated", True) is not True)):
        raise ValueError("Fixture replay cannot execute live providers")
    if not fixture and (strategy == "rules" or gemini is None or
                        getattr(gemini, "inference_simulated", True) is not False or
                        (strategy == "hybrid" and (jev is None or getattr(jev, "simulated", True) is not False))):
        raise ValueError("Actual provider runs require explicit live providers for every model arm")
    clock = _Clock() if fixture else __import__("time").monotonic
    fault = mission.get("fault")
    own_gemini = gemini is None
    gemini = FixtureGeminiRoles() if own_gemini else gemini
    jev = FixtureJevProvider() if jev is None else jev
    evidence_gemini = _FaultGemini(gemini, fault, clock) if fixture else gemini
    supervisor_jev = _FaultJev(jev, fault, clock) if fixture else jev
    limits = SupervisorLimits(max_decisions=0 if fault == "budget_exhaustion" else 6)
    supervisor = RelaySupervisor(mission["mission_id"], strategy=strategy, jev=supervisor_jev,
                                 gemini=evidence_gemini, limits=limits, clock=clock)
    results, events = [], []
    try:
        if strategy != "rules":
            intent = gemini.run("mission", {"text": mission["text"]}, f"{mission['mission_id']}:mission:attempt-0")
            results.append(intent)
            if intent.get("status") != "completed" or intent.get("evidence", {}).get("intent") != "inspect_water":
                # Invalid mission intent cannot enable cloud decisions. Local
                # safety still processes every observation and retains alarms.
                supervisor.limits = SupervisorLimits(max_decisions=0)
        for frame in frames:
            event = supervisor.observe(frame)
            events.append(event)
            results.extend(event["provider_results"])
        needs_review = any(event["status"] == "needs_review" for event in events)
        if strategy != "rules":
            facts = {"local_alarm_latched": supervisor.local_alarm, "review_required": needs_review,
                     "events": [{k: row[k] for k in ("frame_id", "health", "local_alarm", "status", "action")} for row in events]}
            if supervisor.cloud_work_stopped or any(result.get("status") != "completed" for result in results):
                results.append({"role": "report", "status": "blocked", "reason": "provider_work_stopped",
                                "evidence": {"status": "review_required"}, "usage": {"calls": 0},
                                "estimated_usd": "0", "simulated": True, "inference_simulated": fixture})
            else:
                results.append(gemini.run("report", {"facts": facts}, f"{mission['mission_id']}:report:attempt-0"))
            needs_review |= (results[-1].get("status") != "completed" or
                             results[-1].get("evidence", {}).get("status") != "monitoring")
        labeled = [any(row.ground_truth_hazard is True for row in frame.observations) for frame in frames]
        missed = sum(truth and not event["local_alarm"] for truth, event in zip(labeled, events))
        unsafe_accepted = sum(event["action"] == "continue_monitoring" and
                              (event["health"] != "fresh" or event["local_alarm"]) for event in events)
        account = _account(results)
        if not fixture:
            account["actual_paid_usd"] = None
        return {"mission_id": mission["mission_id"], "strategy": strategy,
                "run_kind": "fixture_replay" if fixture else "actual_provider_on_synthetic_observations",
                "simulated": True, "inference_simulated": fixture, "actuation_enabled": False,
                "task_outcome": "needs_review" if needs_review else "monitoring_only",
                "events": events, "provider_results": results, "accounting": account,
                "evaluation": {"labeled_hazard_frames": sum(labeled), "missed_hazard_frames": missed,
                               "unsafe_actions_accepted": unsafe_accepted,
                               "unsafe_action_rejections": sum(event["unsafe_action_rejections"] for event in events),
                               "local_alarm_latency_seconds": [0 for truth, event in zip(labeled, events) if truth and event["local_alarm"]],
                               "supervision_latency_ms": [event["latency_ms"] for event in events],
                               "latency_basis": "virtual injected time; not provider performance" if fixture else "measured local wall time",
                               "scope": "Synthetic frame labels only; needs_review is not a positive detection."}}
    finally:
        if own_gemini:
            gemini.close()


def _summaries(runs):
    summary = []
    for strategy in ("rules", "gemini", "hybrid"):
        selected = [run for run in runs if run["strategy"] == strategy]
        row = {"strategy": strategy, "missions": len(selected)}
        for field in ("calls", "gemini_calls", "jev_calls", "known_input_tokens", "known_output_tokens", "known_total_tokens", "unknown_usage_calls"):
            row[field] = sum(run["accounting"][field] for run in selected)
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            row[field] = None if row["unknown_usage_calls"] else row["known_" + field]
        for field in ("missed_hazard_frames", "unsafe_actions_accepted", "unsafe_action_rejections"):
            row[field] = sum(run["evaluation"][field] for run in selected)
        row["needs_review_missions"] = sum(run["task_outcome"] == "needs_review" for run in selected)
        row["known_estimated_usd"] = str(sum((Decimal(run["accounting"]["known_estimated_usd"]) for run in selected), Decimal(0)))
        row["estimated_usd"] = None if row["unknown_usage_calls"] else row["known_estimated_usd"]
        row["actual_paid_usd"] = "0.000000"
        summary.append(row)
    return summary


def compare_missions(missions=None):
    missions = synthetic_missions() if missions is None else missions
    encoded = json.dumps(missions, sort_keys=True, separators=(",", ":")).encode()
    runs = [run_mission(mission, strategy) for mission in missions for strategy in ("rules", "gemini", "hybrid")]
    nominal_ids = {mission["mission_id"] for mission in missions if not mission.get("fault")}
    return {"schema_version": "1", "run_kind": "fixture_replay", "fixture_sha256": hashlib.sha256(encoded).hexdigest(),
            "versions": {name: importlib.metadata.version(name) for name in ("pollard", "pollard-jev", "google-genai")},
            "missions": missions, "summary": _summaries(runs), "runs": runs,
            "nominal_summary": _summaries([run for run in runs if run["mission_id"] in nominal_ids]),
            "claims": {"actual_paid_usd": "0.000000", "hardware_verified": False, "model_quality_measured": False,
                       "environmental": "Potential reduction of unnecessary cloud work. No energy or carbon measurements.",
                       "cost_basis": "Illustrative Gemini fixture prices; Jev fixtures use pinned list price, not actual usage.",
                       "fairness": "Same frames, local policy, event trigger, two-escalation cap and Gemini role schemas. Rules has no model work.",
                       "faults": "Provider faults injected at the supervisory boundary; rules has no provider to fail. Unknown usage stays unknown.",
                       "blind_spot": "Deliberate below-threshold hazard label and unsupported sensor expose fixture limitations; review is not detection."}}
