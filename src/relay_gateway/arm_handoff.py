"""Offline inspection-to-arm proposal seam. This module never dispatches motion.

The working Bluetooth app is operator-reported evidence, not a connected Python
driver. Proposal IDs identify repeatable previews; they are not execution tokens.
"""

from __future__ import annotations

import hashlib
import json
import re


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_EVIDENCE = re.compile(r"sim://[A-Za-z0-9][A-Za-z0-9_.:/-]{0,191}\Z")
_SOURCES = {"intellio-rover", "freenove-hexapod"}


def _identifier(value, name):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{name} must contain 1..96 alphanumeric/._:- characters")
    return value


def arm_connection_status():
    """Return a fresh capability report without probing a port or device."""
    return {
        "device_id": "learm",
        "software_connection": "not_configured",
        "physical_connected": False,
        "actuation_enabled": False,
        "proposal_actions": ["place_marker"],
        "motion_recording_available": False,
        "motion_playback_available": False,
        "required_handoff": [
            "Exact LeArm generation and controller board identifier",
            "Working Bluetooth app name and version; board connection method",
            "Matching official programming interface and action-recording example",
            "Operator-attended taught routine and verified stop procedure",
        ],
        "network_requests": 0,
        "commands_dispatched": 0,
    }


def build_arm_handoff(*, event_id, mission_id, source_id, evidence_ref,
                      station_id="station-a", simulated=True,
                      action="place_marker", target_id="learm"):
    """Build a bounded review preview from a simulated inspection event.

    A review of this payload cannot authorize motion. There is no transport,
    hardware confirmation input, joint target, or executable routine in it.
    """
    for name, value in (("event_id", event_id), ("mission_id", mission_id),
                        ("station_id", station_id)):
        _identifier(value, name)
    if not isinstance(source_id, str) or source_id not in _SOURCES:
        raise ValueError("source_id must identify the simulated rover or hexapod")
    if simulated is not True:
        raise ValueError("Only explicitly simulated inspection evidence is supported")
    if not isinstance(evidence_ref, str) or not _EVIDENCE.fullmatch(evidence_ref):
        raise ValueError("evidence_ref must be a bounded sim:// reference")
    if action != "place_marker" or target_id != "learm":
        raise ValueError("Only a place_marker preview addressed to learm is supported")
    inspection = {
        "event_id": event_id, "mission_id": mission_id, "source_id": source_id,
        "station_id": station_id, "evidence_ref": evidence_ref, "simulated": True,
    }
    identity = {"inspection": inspection, "action": action, "target_id": target_id}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": "1",
        "proposal_id": "arm-preview-" + digest[:24],
        **identity,
        "status": "needs_review",
        "preview_only": True,
        "simulated": True,
        "confirmation_source": "synthetic_inspection",
        "physical_connected": False,
        "actuation_enabled": False,
        "human_review_performed": False,
        "environment_safety": "not_established",
        "commands_dispatched": 0,
        "network_requests": 0,
        "model_calls": 0,
        "api_cloud_cost_usd": 0,
        "physical_result": None,
        "next_step": "Review the simulated evidence; connect a verified taught routine separately.",
    }
