"""Synthetic comparison fairness and claim boundaries; no real provider calls."""

from copy import deepcopy
import hashlib
import json

import pytest

from relay_gateway import jev_comparison as comparison
from relay_gateway.jev_gemini import FixtureGeminiRoles
from relay_gateway.jev_provider import FixtureJevProvider


def mission(name):
    return next(row for row in comparison.synthetic_missions() if row["mission_id"] == name)


def test_all_arms_receive_same_immutable_missions_and_summary_repeats():
    missions = comparison.synthetic_missions()
    original = deepcopy(missions)
    first = comparison.compare_missions(missions)
    second = comparison.compare_missions(missions)
    assert missions == original
    assert first["summary"] == second["summary"]
    assert first["fixture_sha256"] == hashlib.sha256(json.dumps(
        missions, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert first["fixture_sha256"] == second["fixture_sha256"]
    for source in missions:
        runs = [row for row in first["runs"] if row["mission_id"] == source["mission_id"]]
        assert {row["strategy"] for row in runs} == {"rules", "gemini", "hybrid"}
        for run in runs:
            assert [event["frame_id"] for event in run["events"]] == [frame["frame_id"] for frame in source["frames"]]
            assert run["run_kind"] == "fixture_replay"
            assert run["inference_simulated"] is True and run["actuation_enabled"] is False


def test_labels_never_reach_jev_or_gemini_inputs():
    gemini = FixtureGeminiRoles()
    jev = FixtureJevProvider()
    seen = []

    class SpyGemini:
        def run(self, role, data, *args, **kwargs):
            seen.append(("gemini", role, deepcopy(data)))
            return gemini.run(role, data, *args, **kwargs)

    class SpyJev:
        def decide(self, state, *args, **kwargs):
            seen.append(("jev", "choice", json.loads(state)))
            return jev.decide(state, *args, **kwargs)

    try:
        source = mission("wet_episode")
        result = comparison.run_mission(source, "hybrid", gemini=SpyGemini(), jev=SpyJev())
    finally:
        gemini.close()
    encoded = json.dumps(seen)
    assert "ground_truth" not in encoded and "expected_hazard" not in encoded
    assert result["evaluation"]["labeled_hazard_frames"] == 2
    assert {row[0] for row in seen} == {"gemini", "jev"}
    assert {row[1] for row in seen if row[0] == "gemini"} == {"mission", "evidence", "report"}
    assert any(row.get("ground_truth_hazard") for frame in source["frames"] for row in frame["observations"])


def test_label_changes_affect_evaluation_only_not_decisions_or_calls():
    source = mission("sensor_blind_spot")
    without_label = deepcopy(source)
    without_label["frames"][0]["observations"][0]["ground_truth_hazard"] = False
    labeled = comparison.run_mission(source, "hybrid")
    unlabeled = comparison.run_mission(without_label, "hybrid")
    def decisions(result):
        return [{key: value for key, value in row.items() if key not in {"provider_results", "latency_ms"}}
                for row in result["events"]]

    assert decisions(labeled) == decisions(unlabeled)
    assert labeled["accounting"] == unlabeled["accounting"]
    assert labeled["evaluation"]["missed_hazard_frames"] == 1
    assert unlabeled["evaluation"]["missed_hazard_frames"] == 0


@pytest.mark.parametrize("strategy", ["rules", "gemini", "hybrid"])
def test_below_threshold_blind_spot_is_reported_as_missed(strategy):
    result = comparison.run_mission(mission("sensor_blind_spot"), strategy)
    assert result["evaluation"]["missed_hazard_frames"] == 1
    assert result["evaluation"]["unsafe_actions_accepted"] == 0
    assert result["events"][0]["local_alarm"] is False
    assert "not a positive detection" in result["evaluation"]["scope"]


def test_compare_discloses_unmeasured_quality_hardware_environment_and_costs():
    result = comparison.compare_missions()
    assert result["claims"]["hardware_verified"] is False
    assert result["claims"]["model_quality_measured"] is False
    assert "No energy or carbon measurements" in result["claims"]["environmental"]
    assert "fixture" in result["claims"]["cost_basis"].lower()
    assert "below-threshold" in result["claims"]["blind_spot"]
    assert result["claims"]["actual_paid_usd"] == "0.000000"
    rules = next(row for row in result["summary"] if row["strategy"] == "rules")
    assert rules["calls"] == 0 and rules["total_tokens"] == 0


@pytest.mark.parametrize("strategy", ["gemini", "hybrid"])
def test_network_failure_retains_unknown_usage_and_safe_local_alarm(strategy):
    result = comparison.run_mission(mission("network_failure"), strategy)
    assert result["task_outcome"] == "needs_review"
    assert result["events"][0]["local_alarm"] is True
    assert result["events"][0]["safe_hold"] is True
    assert result["accounting"]["unknown_usage_calls"] == 1
    assert result["accounting"]["estimated_usd"] is None
    assert result["accounting"]["input_tokens"] is None
    assert result["accounting"]["output_tokens"] is None
    assert result["accounting"]["total_tokens"] is None
    assert result["accounting"]["known_total_tokens"] > 0
    assert result["accounting"]["provider_reported_cost_usd"] is None
    assert result["accounting"]["actual_paid_usd"] == "0.000000"


@pytest.mark.parametrize("scenario", ["deadline_expiry", "budget_exhaustion", "invalid_choice"])
@pytest.mark.parametrize("strategy", ["gemini", "hybrid"])
def test_failure_scenarios_do_not_remove_alarm_or_enable_action(scenario, strategy):
    result = comparison.run_mission(mission(scenario), strategy)
    event = result["events"][0]
    assert result["task_outcome"] == "needs_review"
    assert event["action"] == "hold" and event["safe_hold"] is True
    assert event["local_alarm"] is True
    assert result["evaluation"]["unsafe_actions_accepted"] == 0
    if scenario == "budget_exhaustion":
        assert event["provider_results"] == []
        assert result["accounting"]["calls"] == 2  # Explicit mission/report roles only.
    if scenario == "deadline_expiry":
        assert result["evaluation"]["supervision_latency_ms"] == [6000.0]


def test_dry_report_and_task_outcome_agree():
    result = comparison.run_mission(mission("dry_monitoring"), "hybrid")
    report = result["provider_results"][-1]
    assert report["role"] == "report"
    assert result["task_outcome"] == "monitoring_only"
    assert report["evidence"]["status"] == "monitoring"


def test_actual_run_cannot_silently_construct_fixtures():
    with pytest.raises(ValueError):
        comparison.run_mission(mission("dry_monitoring"), "hybrid", fixture=False)


def test_actual_run_rejects_explicit_fixture_providers():
    gemini = FixtureGeminiRoles()
    try:
        with pytest.raises(ValueError):
            comparison.run_mission(mission("dry_monitoring"), "hybrid", fixture=False,
                                   gemini=gemini, jev=FixtureJevProvider())
    finally:
        gemini.close()


@pytest.mark.parametrize("live_role", ["gemini", "jev"])
def test_fixture_default_refuses_live_provider_injection(live_role):
    class Provider:
        inference_simulated = False
        simulated = False

        def run(self, *args, **kwargs):
            pytest.fail("Fixture mode must not dispatch a live provider")

        def decide(self, *args, **kwargs):
            pytest.fail("Fixture mode must not dispatch a live provider")

    with pytest.raises(ValueError):
        comparison.run_mission(mission("dry_monitoring"), "hybrid", **{live_role: Provider()})


def test_live_mode_never_injects_fixture_faults():
    with pytest.raises(ValueError, match="fixture"):
        comparison.run_mission(mission("network_failure"), "hybrid", fixture=False)


@pytest.mark.parametrize("failed_role", ["mission", "evidence"])
def test_unknown_provider_stops_later_cloud_work_but_observations_still_latch_alarm(failed_role):
    underlying = FixtureGeminiRoles()
    roles = []

    class UnknownOnce:
        inference_simulated = True

        def run(self, role, *args, **kwargs):
            roles.append(role)
            if role == failed_role:
                return {"role": role, "status": "unknown", "reason": "injected_timeout",
                        "evidence": {}, "usage": {"calls": 1, "input_tokens": None, "output_tokens": None},
                        "estimated_usd": None, "simulated": True, "inference_simulated": True}
            return underlying.run(role, *args, **kwargs)

    try:
        result = comparison.run_mission(mission("wet_episode"), "gemini", gemini=UnknownOnce())
    finally:
        underlying.close()
    assert roles == (["mission"] if failed_role == "mission" else ["mission", "evidence"])
    assert len(result["events"]) == 3
    assert result["events"][-1]["local_alarm"] is True
    assert result["events"][-1]["safe_hold"] is True
    assert result["provider_results"][-1]["role"] == "report"
    assert result["provider_results"][-1]["reason"] == "provider_work_stopped"
    assert result["provider_results"][-1]["usage"]["calls"] == 0
    assert result["accounting"]["calls"] == len(roles)
    assert result["accounting"]["unknown_usage_calls"] == 1
    assert result["accounting"]["estimated_usd"] is None


def test_unknown_jev_stops_further_supervision_and_gemini_reporting():
    underlying = FixtureGeminiRoles()
    roles, decisions = [], []

    class GeminiSpy:
        inference_simulated = True

        def run(self, role, *args, **kwargs):
            roles.append(role)
            return underlying.run(role, *args, **kwargs)

    class UnknownJev:
        simulated = True

        def decide(self, *args, **kwargs):
            decisions.append(1)
            return {"status": "unknown", "choice": None, "reason": "injected_timeout",
                    "metrics": {"calls": 1, "input_tokens": None, "output_tokens": None, "estimated_usd": None},
                    "simulated": True}

    try:
        result = comparison.run_mission(mission("wet_episode"), "hybrid", gemini=GeminiSpy(), jev=UnknownJev())
    finally:
        underlying.close()
    assert roles == ["mission"] and len(decisions) == 1
    assert len(result["events"]) == 3 and result["events"][-1]["local_alarm"] is True
    assert result["provider_results"][-1]["reason"] == "provider_work_stopped"
    assert result["accounting"]["calls"] == 2
    assert result["accounting"]["estimated_usd"] is None


@pytest.mark.parametrize("failed_provider", ["gemini", "jev"])
def test_provider_exception_cannot_trigger_report_or_zero_usage_claim(failed_provider):
    underlying = FixtureGeminiRoles()
    roles, jev_calls = [], []

    class GeminiSpy:
        inference_simulated = True

        def run(self, role, *args, **kwargs):
            roles.append(role)
            if role == "evidence":
                raise RuntimeError("private-response-or-key")
            return underlying.run(role, *args, **kwargs)

    class ThrowingJev:
        simulated = True

        def decide(self, *args, **kwargs):
            jev_calls.append(1)
            raise RuntimeError("private-response-or-key")

    strategy = "gemini" if failed_provider == "gemini" else "hybrid"
    try:
        result = comparison.run_mission(mission("wet_episode"), strategy, gemini=GeminiSpy(), jev=ThrowingJev())
    finally:
        underlying.close()
    assert "report" not in roles
    assert result["provider_results"][-1]["reason"] == "provider_work_stopped"
    assert result["events"][-1]["local_alarm"] is True
    assert result["accounting"]["estimated_usd"] is None
    assert result["accounting"]["unknown_usage_calls"] == 1
    assert "private-response-or-key" not in json.dumps(result)
