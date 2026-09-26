"""Exercise the real pinned package contracts without provider or hardware calls."""

from importlib.metadata import version

import pytest
from pollard_jev.contracts import PolicyOutcome

from relay_gateway.jev_pollard import PERMITTED_ACTIONS, validate_choice


def admit(choice="request_evidence", **overrides):
    arguments = {
        "allowed_actions": PERMITTED_ACTIONS,
        "observed_at_seconds": 10,
        "now_seconds": 11,
        "max_age_seconds": 5,
    }
    arguments.update(overrides)
    return validate_choice(choice, **arguments)


def test_actual_pinned_package_supplies_typed_policy_without_dispatch():
    assert version("pollard-jev") == "0.1"
    result = admit()
    assert result.accepted
    assert result.action == "request_evidence"
    assert isinstance(result.policy, PolicyOutcome)
    assert result.policy.parameters == {}
    assert result.as_dict()["simulated"] is True
    assert result.as_dict()["dispatched"] is False


@pytest.mark.parametrize("choice", PERMITTED_ACTIONS)
def test_each_reviewed_supervisory_label_can_be_admitted(choice):
    assert admit(choice).accepted


@pytest.mark.parametrize("now", [9, 15, 16])
def test_future_or_expired_evidence_defers_even_hold(now):
    result = admit("hold", now_seconds=now)
    assert not result.accepted
    assert result.reason == "stale_or_future_evidence"
    assert result.action is None
    assert result.policy.disposition == "defer"


def test_dispatch_time_recheck_can_reject_previously_admitted_choice():
    assert admit(now_seconds=14).accepted
    result = admit(now_seconds=15)
    assert not result.accepted
    assert result.action is None


def test_local_controller_can_remove_monitoring_when_alarm_or_uncertainty_latches():
    result = admit("continue_monitoring", allowed_actions=("hold", "request_evidence", "escalate_gemini"))
    assert result.reason == "unauthorized_action"
    assert result.action is None
    assert not result.accepted


@pytest.mark.parametrize("choice,reason", [
    (None, "no_proposal"),
    ({"action": "hold", "distance_cm": 20}, "invalid_choice"),
    (["hold"], "invalid_choice"),
    (True, "invalid_choice"),
    ("drive_forward", "unauthorized_action"),
    ("clear_hazard", "unauthorized_action"),
    ("hold ", "unauthorized_action"),
])
def test_malformed_or_unlisted_proposals_never_become_actions(choice, reason):
    result = admit(choice)
    assert result.reason == reason
    assert result.action is None
    assert not result.accepted


@pytest.mark.parametrize("allowlist", [
    (), [], ("hold", "hold"), ("hold", "drive_forward"), "hold", None,
    {"hold": {}}, (True,), ("hold",) * 100,
])
def test_invalid_allowlist_fails_closed(allowlist):
    result = admit(allowed_actions=allowlist)
    assert not result.accepted
    assert result.reason in {"invalid_allowlist", "no_permitted_action"}


@pytest.mark.parametrize("argument,value", [
    ("observed_at_seconds", -1), ("observed_at_seconds", True),
    ("observed_at_seconds", "10"), ("observed_at_seconds", float("nan")),
    ("observed_at_seconds", float("inf")), ("observed_at_seconds", 10**400),
    ("now_seconds", -1), ("now_seconds", False),
    ("max_age_seconds", 0), ("max_age_seconds", -1),
    ("max_age_seconds", float("nan")), ("max_age_seconds", 10**100),
    ("request_id", ""),
])
def test_invalid_freshness_context_fails_closed(argument, value):
    result = admit(**{argument: value})
    assert not result.accepted
    assert result.reason == "invalid_freshness_context"
    assert result.policy is None


def test_missing_evidence_timestamp_has_no_fabricated_freshness():
    result = admit(observed_at_seconds=None)
    assert result.reason == "missing_observation_timestamp"
    assert not result.accepted


def test_deadline_expiry_rejects_fresh_high_support_choice_without_scoring():
    result = admit(deadline_expired=True)
    assert not result.accepted
    assert result.action is None
    assert result.reason == "deadline_expired"


def test_deadline_context_is_not_coerced_from_strings():
    result = admit(deadline_expired="false")
    assert result.reason == "invalid_deadline_context"
    assert not result.accepted


def test_rejection_evidence_does_not_echo_arbitrary_provider_content():
    proposal = "SECRET-LIKE-UNTRUSTED-CONTENT"
    result = admit(proposal)
    assert proposal not in str(result.as_dict())
