"""Failure-focused offline checks for local supervision invariants."""

import json

import pytest

from relay_gateway.jev_supervisor import RelaySupervisor, SupervisionFrame, SupervisorLimits


class ManualClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class JevDouble:
    def __init__(self, choice="continue_monitoring", *, response=None, callback=None):
        self.choice, self.response, self.callback = choice, response, callback
        self.calls = []

    def decide(self, state, allowed_actions, operation_id, *, timeout_seconds):
        self.calls.append({"state": json.loads(state), "allowed": allowed_actions,
                           "operation_id": operation_id, "timeout_seconds": timeout_seconds})
        if self.callback:
            self.callback()
        return self.response if self.response is not None else {
            "status": "completed", "choice": self.choice, "score": 1.0,
            "simulated": True,
        }


class GeminiDouble:
    def __init__(self, status="clear", *, response=None, callback=None):
        self.status, self.response, self.callback = status, response, callback
        self.calls = []

    def run(self, task, state, operation_id, *, timeout_seconds):
        self.calls.append({"task": task, "state": state, "operation_id": operation_id,
                           "timeout_seconds": timeout_seconds})
        if self.callback:
            self.callback()
        return self.response if self.response is not None else {
            "status": "completed", "evidence": {"status": self.status}, "simulated": True,
        }


def observation(robot_id="station-a", value=100, timestamp=10, **overrides):
    row = {"event_id": f"{robot_id}:{timestamp}", "robot_id": robot_id,
           "kind": "water", "value_milli": value, "unit": "wetness",
           "timestamp_seconds": timestamp, "simulated": True}
    row.update(overrides)
    return row


def frame(identifier="frame-1", *, rows=None, now=10, required=None):
    return {"frame_id": identifier, "now_seconds": now,
            "observations": [observation()] if rows is None else rows,
            "required_robot_ids": ["station-a"] if required is None else required}


def assert_holding(result):
    assert result["safe_hold"] is True
    assert result["status"] == "needs_review"
    assert result["simulated"] is True
    assert result["physical_action"] is False
    assert result["actuation_enabled"] is False


@pytest.mark.parametrize("rows,now,required,health", [
    ([], 10, ["station-a"], "missing"),
    ([observation()], 10, ["station-a", "station-b"], "missing"),
    ([observation(timestamp=4)], 10, ["station-a"], "stale"),
    ([observation(timestamp=11)], 10, ["station-a"], "stale"),
    ([observation(value=None)], 10, ["station-a"], "unsupported"),
    ([observation(value=-1)], 10, ["station-a"], "unsupported"),
    ([observation(value=1001)], 10, ["station-a"], "unsupported"),
    ([observation(kind="gas")], 10, ["station-a"], "unsupported"),
    ([observation(unit="percent")], 10, ["station-a"], "unsupported"),
])
def test_unusable_evidence_holds_without_any_provider_request(rows, now, required, health):
    jev, gemini = JevDouble(), GeminiDouble()
    supervisor = RelaySupervisor("mission", jev=jev, gemini=gemini)
    result = supervisor.observe(frame(rows=rows, now=now, required=required))
    assert_holding(result)
    assert result["health"] == health
    assert result["action"] == "hold"
    assert not jev.calls and not gemini.calls


@pytest.mark.parametrize("strategy", ["rules", "gemini", "hybrid"])
def test_exact_observation_expiry_is_stale_before_cloud_admission(strategy):
    jev, gemini = JevDouble(), GeminiDouble()
    supervisor = RelaySupervisor("mission", strategy=strategy, jev=jev, gemini=gemini)
    result = supervisor.observe(frame(rows=[observation(timestamp=5)], now=10))
    assert_holding(result)
    assert result["health"] == "stale"
    assert not jev.calls and not gemini.calls


def test_conflicting_readings_latch_alarm_and_reject_high_score_monitoring():
    jev = JevDouble()
    supervisor = RelaySupervisor("mission", jev=jev)
    result = supervisor.observe(frame(rows=[observation(value=900), observation("station-b", 100)],
                                      required=["station-a", "station-b"]))
    assert_holding(result)
    assert result["health"] == "conflicting"
    assert result["local_alarm"] is True
    assert result["unsafe_action_rejections"] == 1
    assert "continue_monitoring" not in jev.calls[0]["allowed"]


@pytest.mark.parametrize("choice", ["drive_forward", "clear_hazard", {"action": "hold"}])
def test_arbitrary_choices_are_rejected_even_with_maximum_provider_score(choice):
    result = RelaySupervisor("mission", jev=JevDouble(choice)).observe(frame())
    assert_holding(result)
    assert result["action"] == "hold"
    assert result["unsafe_action_rejections"] == 1


@pytest.mark.parametrize("mode", ["clear", "blocked", "exception"])
def test_local_alarm_survives_gemini_clear_budget_refusal_and_network_failure(mode):
    def fail():
        raise RuntimeError("untrusted provider error must not be persisted")

    gemini = GeminiDouble(response={"status": "blocked", "reason": "budget"} if mode == "blocked" else None,
                          callback=fail if mode == "exception" else None)
    supervisor = RelaySupervisor("mission", strategy="gemini", gemini=gemini)
    first = supervisor.observe(frame(rows=[observation(value=900)]))
    assert_holding(first)
    assert first["local_alarm"] is True
    second = supervisor.observe(frame("frame-2", rows=[observation(timestamp=11)], now=11))
    assert_holding(second)
    assert second["local_alarm"] is True
    assert supervisor.local_alarm is True
    assert "untrusted provider error" not in json.dumps(second)


def test_gemini_suspected_hazard_latches_alarm_even_below_local_numeric_threshold():
    supervisor = RelaySupervisor("mission", strategy="gemini", gemini=GeminiDouble("suspected_hazard"))
    first = supervisor.observe(frame())
    assert_holding(first)
    assert first["local_alarm"] is True
    supervisor.gemini = GeminiDouble("clear")
    second = supervisor.observe(frame("frame-2", rows=[observation(timestamp=11)], now=11))
    assert_holding(second)
    assert second["local_alarm"] is True


@pytest.mark.parametrize("response", [
    {"status": "blocked", "reason": "budget_exhausted"},
    {"status": "failed", "reason": "network_failure"},
    {"status": "completed", "choice": None},
])
def test_jev_no_decision_or_budget_denial_holds(response):
    result = RelaySupervisor("mission", jev=JevDouble(response=response)).observe(frame())
    assert_holding(result)
    assert result["action"] == "hold"


def test_jev_exception_holds_and_does_not_record_raw_exception():
    def fail():
        raise TimeoutError("SECRET-LIKE-TOKEN")

    result = RelaySupervisor("mission", jev=JevDouble(callback=fail)).observe(frame())
    assert_holding(result)
    assert "SECRET-LIKE-TOKEN" not in json.dumps(result)


@pytest.mark.parametrize("limit", [0, 1])
def test_decision_allowance_cannot_disable_local_alarm(limit):
    jev = JevDouble("hold")
    supervisor = RelaySupervisor("mission", jev=jev, limits=SupervisorLimits(max_decisions=limit))
    supervisor.observe(frame())
    result = supervisor.observe(frame("frame-2", rows=[observation(value=900, timestamp=11)], now=11))
    assert_holding(result)
    assert result["local_alarm"] is True
    assert len(jev.calls) <= limit


def test_zero_escalations_keeps_holding_without_gemini_request():
    gemini = GeminiDouble()
    supervisor = RelaySupervisor("mission", jev=JevDouble("escalate_gemini"), gemini=gemini,
                                 limits=SupervisorLimits(max_escalations=0))
    result = supervisor.observe(frame())
    assert_holding(result)
    assert not gemini.calls


def test_elapsed_inference_time_cannot_refresh_old_observation():
    clock = ManualClock()
    jev = JevDouble(callback=lambda: clock.advance(2))
    supervisor = RelaySupervisor("mission", jev=jev, clock=clock,
                                 limits=SupervisorLimits(deadline_seconds=4))
    result = supervisor.observe(frame(rows=[observation(timestamp=7)], now=10))
    assert_holding(result)
    assert result["reason"] == "stale_or_future_evidence"
    assert result["unsafe_action_rejections"] == 1


def test_jev_result_at_exact_deadline_cannot_escalate_or_monitor():
    clock, gemini = ManualClock(), GeminiDouble()
    jev = JevDouble("escalate_gemini", callback=lambda: clock.advance(2))
    supervisor = RelaySupervisor("mission", jev=jev, gemini=gemini, clock=clock,
                                 limits=SupervisorLimits(deadline_seconds=2))
    result = supervisor.observe(frame())
    assert_holding(result)
    assert result["reason"] == "deadline_expired"
    assert not gemini.calls


def test_gemini_at_exact_evidence_expiry_holds_even_before_decision_deadline():
    clock = ManualClock()
    gemini = GeminiDouble(callback=lambda: clock.advance(2))
    supervisor = RelaySupervisor("mission", strategy="gemini", gemini=gemini, clock=clock,
                                 limits=SupervisorLimits(deadline_seconds=4))
    result = supervisor.observe(frame(rows=[observation(timestamp=7)], now=10))
    assert_holding(result)
    assert result["reason"] == "deadline_or_evidence_unavailable"


def test_gemini_late_completion_cannot_change_safe_hold():
    clock = ManualClock()
    supervisor = RelaySupervisor("mission", strategy="gemini", clock=clock,
                                 gemini=GeminiDouble(callback=lambda: clock.advance(5)))
    result = supervisor.observe(frame())
    assert_holding(result)
    assert result["reason"] == "deadline_or_evidence_unavailable"


@pytest.mark.parametrize("response", [
    {"status": "completed"}, {"status": "completed", "evidence": {}},
    {"status": "completed", "evidence": {"status": "arbitrary_unreviewed_status"}},
])
def test_missing_or_unrecognized_gemini_finding_is_unavailable_evidence(response):
    supervisor = RelaySupervisor("mission", strategy="gemini", gemini=GeminiDouble(response=response))
    result = supervisor.observe(frame())
    assert_holding(result)


def test_exact_frame_replay_does_not_repeat_provider_work_or_usage():
    jev = JevDouble()
    supervisor = RelaySupervisor("mission", jev=jev)
    original = supervisor.observe(frame())
    repeated = supervisor.observe(frame())
    assert repeated["replayed"] is True
    assert repeated["action"] == "hold"
    assert repeated["historical_action"] == original["action"]
    assert repeated["reason"] == "replay_no_new_action"
    assert_holding(repeated)
    assert repeated["provider_results"] == []
    assert len(jev.calls) == 1
    assert supervisor.decisions == 1


def test_replaying_earlier_dry_frame_cannot_hide_a_later_latched_alarm():
    jev = JevDouble()
    supervisor = RelaySupervisor("mission", jev=jev)
    original_frame = frame()
    assert supervisor.observe(original_frame)["local_alarm"] is False
    wet = supervisor.observe(frame("frame-2", rows=[observation(value=900, timestamp=11)], now=11))
    assert wet["local_alarm"] is True
    replay = supervisor.observe(original_frame)
    assert replay["replayed"] is True
    assert_holding(replay)
    assert replay["local_alarm"] is True
    assert replay["provider_results"] == []
    assert len(jev.calls) == 2


def test_replaying_dry_frame_after_missing_evidence_preserves_hold_without_alarm():
    jev = JevDouble()
    supervisor = RelaySupervisor("mission", jev=jev)
    original = supervisor.observe(frame())
    missing = supervisor.observe(frame("frame-2", rows=[], now=11))
    assert_holding(missing)
    assert missing["local_alarm"] is False
    replay = supervisor.observe(frame())
    assert_holding(replay)
    assert replay["action"] == "hold"
    assert replay["historical_action"] == original["action"]
    assert replay["local_alarm"] is False
    assert len(jev.calls) == 1


def test_frame_id_reuse_with_new_evidence_is_rejected_before_provider():
    jev = JevDouble()
    supervisor = RelaySupervisor("mission", jev=jev)
    supervisor.observe(frame())
    with pytest.raises(ValueError, match="reused"):
        supervisor.observe(frame(rows=[observation(value=900)]))
    assert len(jev.calls) == 1


def test_ground_truth_labels_are_not_provider_input_or_an_extra_work_trigger():
    jev = JevDouble()
    supervisor = RelaySupervisor("mission", jev=jev)
    supervisor.observe(frame(rows=[observation(ground_truth_hazard=True)]))
    replay = supervisor.observe(frame(rows=[observation(ground_truth_hazard=False)]))
    assert replay["replayed"] is True
    assert "ground_truth" not in json.dumps(jev.calls)


def test_new_observation_with_unchanged_engineered_state_avoids_provider_call():
    jev = JevDouble()
    supervisor = RelaySupervisor("mission", jev=jev)
    supervisor.observe(frame())
    result = supervisor.observe(frame("frame-2", rows=[observation(value=150, timestamp=11)], now=11))
    assert result["reason"] == "unchanged_state_no_cloud_work"
    assert len(jev.calls) == 1


@pytest.mark.parametrize("strategy", ["hybrid", "gemini"])
@pytest.mark.parametrize("failure", ["blocked", "unknown", "exception"])
def test_provider_failure_keeps_unchanged_fresh_dry_frames_holding(strategy, failure):
    def fail():
        raise RuntimeError("private-provider-error")

    options = ({"callback": fail} if failure == "exception" else
               {"response": {"status": failure, "reason": "provider_unavailable"}})
    jev = JevDouble(**options) if strategy == "hybrid" else JevDouble()
    gemini = GeminiDouble(**options) if strategy == "gemini" else GeminiDouble()
    supervisor = RelaySupervisor("mission", strategy=strategy, jev=jev, gemini=gemini)
    first = supervisor.observe(frame())
    assert_holding(first)
    calls_before = (len(jev.calls), len(gemini.calls))
    second = supervisor.observe(frame("frame-2", rows=[observation(value=150, timestamp=11)], now=11))
    assert_holding(second)
    assert second["health"] == "fresh" and second["local_alarm"] is False
    assert second["changed"] is False and second["action"] == "hold"
    assert second["reason"] == "provider_work_stopped"
    assert second["provider_results"] == []
    assert (len(jev.calls), len(gemini.calls)) == calls_before
    assert "private-provider-error" not in json.dumps(second)


@pytest.mark.parametrize("strategy", ["hybrid", "gemini"])
@pytest.mark.parametrize("limit", [0, 1])
def test_decision_budget_refusal_keeps_unchanged_fresh_dry_frames_holding(strategy, limit):
    jev, gemini = JevDouble(), GeminiDouble()
    supervisor = RelaySupervisor("mission", strategy=strategy, jev=jev, gemini=gemini,
                                 limits=SupervisorLimits(max_decisions=limit))
    if limit:
        # Spend the single decision on a different, non-alarming state. The
        # later dry transition is denied without relying on a wet alarm latch.
        initial = supervisor.observe(frame("initial", rows=[observation(value=400, timestamp=9)], now=9))
        assert initial["status"] == "monitoring" and initial["local_alarm"] is False
    refused = supervisor.observe(frame())
    assert_holding(refused)
    assert refused["reason"] == "decision_budget_exhausted"
    calls_before = (len(jev.calls), len(gemini.calls))
    repeated = supervisor.observe(frame("frame-2", rows=[observation(value=150, timestamp=11)], now=11))
    assert_holding(repeated)
    assert repeated["health"] == "fresh" and repeated["local_alarm"] is False
    assert repeated["changed"] is False and repeated["action"] == "hold"
    assert repeated["reason"] == "decision_budget_exhausted"
    assert repeated["provider_results"] == []
    assert (len(jev.calls), len(gemini.calls)) == calls_before


@pytest.mark.parametrize("strategy", ["hybrid", "gemini"])
@pytest.mark.parametrize("limit", [0, 1])
def test_escalation_budget_refusal_keeps_unchanged_fresh_dry_frames_holding(strategy, limit):
    jev, gemini = JevDouble("escalate_gemini"), GeminiDouble()
    supervisor = RelaySupervisor("mission", strategy=strategy, jev=jev, gemini=gemini,
                                 limits=SupervisorLimits(max_escalations=limit))
    if limit:
        initial = supervisor.observe(frame("initial", rows=[observation(value=400, timestamp=9)], now=9))
        assert initial["status"] == "monitoring" and supervisor.escalations == 1
    refused = supervisor.observe(frame())
    assert_holding(refused)
    assert refused["reason"] == "escalation_budget_exhausted"
    calls_before = (len(jev.calls), len(gemini.calls))
    repeated = supervisor.observe(frame("frame-2", rows=[observation(value=150, timestamp=11)], now=11))
    assert_holding(repeated)
    assert repeated["health"] == "fresh" and repeated["local_alarm"] is False
    assert repeated["changed"] is False and repeated["action"] == "hold"
    assert repeated["reason"] == "escalation_budget_exhausted"
    assert repeated["provider_results"] == []
    assert (len(jev.calls), len(gemini.calls)) == calls_before


@pytest.mark.parametrize("strategy", ["hybrid", "gemini"])
def test_healthy_unchanged_frame_needs_no_new_decision_even_when_allowance_used(strategy):
    jev, gemini = JevDouble(), GeminiDouble()
    supervisor = RelaySupervisor("mission", strategy=strategy, jev=jev, gemini=gemini,
                                 limits=SupervisorLimits(max_decisions=1))
    first = supervisor.observe(frame())
    calls_before = (len(jev.calls), len(gemini.calls))
    assert first["status"] == "monitoring" and supervisor.decisions == 1
    repeated = supervisor.observe(frame("frame-2", rows=[observation(value=150, timestamp=11)], now=11))
    assert repeated["status"] == "monitoring" and repeated["safe_hold"] is False
    assert repeated["action"] == "continue_monitoring" and repeated["changed"] is False
    assert repeated["reason"] == "unchanged_state_no_cloud_work"
    assert repeated["provider_results"] == []
    assert (len(jev.calls), len(gemini.calls)) == calls_before


def test_time_rollback_is_rejected_before_provider():
    jev = JevDouble()
    supervisor = RelaySupervisor("mission", jev=jev)
    supervisor.observe(frame())
    with pytest.raises(ValueError, match="backwards"):
        supervisor.observe(frame("frame-2", now=9, rows=[observation(timestamp=9)]))
    assert len(jev.calls) == 1


@pytest.mark.parametrize("rows,required", [
    ([observation(simulated=False)], ["station-a"]),
    ([observation(), observation()], ["station-a"]),
    ([observation()], []),
    ([observation()], ["station-a", "station-a"]),
])
def test_real_hardware_or_ambiguous_source_frames_are_not_accepted(rows, required):
    with pytest.raises(ValueError):
        SupervisionFrame.model_validate(frame(rows=rows, required=required))
