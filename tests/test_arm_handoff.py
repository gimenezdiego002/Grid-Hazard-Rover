"""The inspection seam can export previews but cannot authorize actuation."""

from copy import deepcopy

import pytest

from relay_gateway.arm_handoff import arm_connection_status, build_arm_handoff


@pytest.fixture
def inspection():
    return {"event_id": "inspection-demo-1", "mission_id": "demo-1",
            "source_id": "freenove-hexapod", "station_id": "station-a",
            "evidence_ref": "sim://demo-1/close-inspection", "simulated": True}


def test_preview_retains_provenance_and_cannot_claim_hardware_execution(inspection):
    original = deepcopy(inspection)
    proposal = build_arm_handoff(**inspection)
    assert proposal["inspection"] == original == inspection
    assert proposal["action"] == "place_marker" and proposal["target_id"] == "learm"
    assert proposal["preview_only"] and proposal["simulated"]
    assert not proposal["human_review_performed"]
    assert not proposal["actuation_enabled"] and not proposal["physical_connected"]
    assert proposal["commands_dispatched"] == proposal["network_requests"] == proposal["model_calls"] == 0
    assert proposal["api_cloud_cost_usd"] == 0 and proposal["physical_result"] is None
    assert proposal["environment_safety"] == "not_established"
    proposal["inspection"]["source_id"] = "changed"
    assert inspection == original


def test_identity_is_repeatable_and_bound_to_all_source_evidence(inspection):
    first = build_arm_handoff(**inspection)
    assert build_arm_handoff(**inspection) == first
    for field, value in (("event_id", "inspection-2"), ("mission_id", "demo-2"),
                         ("source_id", "intellio-rover"), ("station_id", "station-b"),
                         ("evidence_ref", "sim://demo-1/another-view")):
        assert build_arm_handoff(**(inspection | {field: value}))["proposal_id"] != first["proposal_id"]


@pytest.mark.parametrize("changes", [
    {"simulated": False}, {"simulated": 1}, {"simulated": "true"},
    {"action": "close_valve"}, {"target_id": "other-arm"}, {"source_id": "learm"},
    {"source_id": []}, {"event_id": "bad\n"}, {"mission_id": "x" * 97},
    {"station_id": "../../port"}, {"evidence_ref": "https://camera/live"},
    {"evidence_ref": "sim://a\nMOVE 1"}, {"evidence_ref": "sim://" + "a" * 193},
])
def test_unsupported_provenance_or_actions_are_rejected(inspection, changes):
    with pytest.raises(ValueError):
        build_arm_handoff(**(inspection | changes))


@pytest.mark.parametrize("field", ["physical_connected", "actuation_enabled", "human_review_performed",
                                   "joint_targets", "command", "physical_result"])
def test_cannot_inject_physical_confirmations_or_commands(inspection, field):
    with pytest.raises(TypeError):
        build_arm_handoff(**inspection, **{field: True})


def test_connection_report_cannot_be_changed_through_prior_snapshot():
    status = arm_connection_status()
    assert not status["actuation_enabled"] and not status["physical_connected"]
    assert not status["motion_recording_available"] and not status["motion_playback_available"]
    status["proposal_actions"].append("move_servo")
    assert arm_connection_status()["proposal_actions"] == ["place_marker"]
