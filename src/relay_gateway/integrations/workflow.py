"""One complete, strictly offline integration rehearsal for the mission UI."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ..gateway import run_scenario
from ..models import Scenario, default_scenario
from ..providers import MockProvider
from .audio_receipt import create_report_receipt, synthesize_briefing, verify_report_receipt
from .data import MongoMissionStore, SnowflakeReferenceStore, TigerTelemetryStore


# A fixed fixture epoch preserves observation identity across demo replays.
# This is not a claim about when any real measurement was taken.
FIXTURE_START = datetime(2026, 9, 26, 18, 0, 0, tzinfo=timezone.utc)


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _step(provider, action, evidence, *, status="completed", limitations=None):
    return {"provider": provider, "action": action, "mode": "mock", "simulated": True,
            "status": status, "remote_verified": False, "evidence": evidence,
            "estimated_usd": "0.000000", "actual_billed_usd": "0.000000",
            "limitations": limitations or ["Offline contract rehearsal; no provider request was made."]}


def _service_inventory():
    exercised = {"gemini", "snowflake", "tiger", "mongodb", "elevenlabs", "solana"}
    names = {"gemini": "Gemini API", "elevenlabs": "ElevenLabs", "solana": "Solana",
             "tiger": "Tiger Data", "digitalocean": "DigitalOcean", "snowflake": "Snowflake API",
             "mongodb": "MongoDB Atlas", "godaddy": "GoDaddy Registry", "gcp": "Google Cloud"}
    return [{"provider": key, "name": name, "remote_verified": False,
             "demo_status": "mock_adapter_exercised" if key in exercised else "not_exercised",
             "connection_status": "not_checked_by_offline_demo",
             "note": ("This run does not establish an active account or remote integration."
                      if key in exercised else "Hosting/domain setup requires separate deployment evidence.")}
            for key, name in names.items()]


def run_integration_demo(scenario: dict | None = None) -> dict:
    """Retrieve -> analyze -> persist -> brief -> verify, always using mocks.

    No credentials are consulted. No production ledger, wallet, audio file or
    remote service is created. A temporary Pollard SQLite recording is removed
    at the end. Supplied observations are replayed as explicitly simulated data.
    """
    normalized = (default_scenario() if scenario is None else Scenario.model_validate(scenario)).model_copy(deep=True)
    normalized.simulated = True
    for observation in normalized.observations:
        observation.simulated = True
    seconds = [observation.timestamp_seconds for observation in normalized.observations]
    # Ensure the fixture epoch plus relative time remains representable before
    # beginning any stage. This is input validation, not a fallback timestamp.
    try:
        start = FIXTURE_START + timedelta(seconds=min(seconds))
        end = FIXTURE_START + timedelta(seconds=max(seconds) + 1)
    except OverflowError:
        raise ValueError("Scenario timestamps exceed the supported fixture timeline") from None

    steps = []
    hazard_type = ("standing_water" if any(obs.kind == "water" for obs in normalized.observations)
                   else normalized.observations[0].kind)
    reference_result = SnowflakeReferenceStore(live=False).retrieve(hazard_type)
    if reference_result["status"] != "completed":
        raise RuntimeError("Offline reference retrieval could not be verified")
    references = reference_result["references"]
    reference_context = [{key: value for key, value in reference.items() if key != "simulated"}
                         | {"is_simulated": True} for reference in references]
    steps.append(_step("snowflake", "Retrieve synthetic reference passages", {
        **reference_result["evidence"], "returned_references": len(references),
        "source_urls": [reference["source_url"] for reference in references],
    }))

    with TemporaryDirectory(prefix="relay-integrated-mock-") as directory:
        gateway = run_scenario(normalized, "economy", provider=MockProvider(),
                               store_path=Path(directory) / "mock-recording.sqlite",
                               reference_context=reference_context)
    findings = gateway["findings"]
    cited_ids = sorted({reference_id for finding in findings for reference_id in finding["cited_reference_ids"]})
    steps.append(_step("gemini", "Exercise the model gateway with deterministic findings", {
        "provider_mode": gateway["provider_mode"], "mock_model_calls": gateway["accounting"]["new_requests"],
        "findings": len(findings), "cited_reference_ids": cited_ids, "audit_verified": gateway["audit_verified"],
        "mission_outcome": gateway["outcome"],
    }, limitations=["MockProvider produced these findings; this stage did not call Gemini.",
                    "Reference use in this rehearsal is deterministic and does not establish model quality."]))

    events = [{"mission_id": normalized.mission_id, "event_id": observation.event_id,
               "robot_id": observation.robot_id,
               "observed_at": _iso(FIXTURE_START + timedelta(seconds=observation.timestamp_seconds)),
               "kind": observation.kind, "value_milli": observation.value_milli, "simulated": True}
              for observation in normalized.observations]
    tiger = TigerTelemetryStore(live=False)
    inserted = tiger.insert_telemetry(events)
    replayed = tiger.insert_telemetry(events)
    queried = tiger.query_range(normalized.mission_id, start, end)
    if any(result["status"] != "completed" for result in (inserted, replayed, queried)):
        raise RuntimeError("Offline telemetry persistence could not be verified")
    telemetry = queried["rows"]
    persistence_ok = (inserted["inserted"] == len(events) and replayed["inserted"] == 0
                      and len(telemetry) == len(events))
    steps.append(_step("tiger", "Insert, replay, and read the synthetic telemetry window", {
        "inserted_events": inserted["inserted"], "replay_inserted_events": replayed["inserted"],
        "readback_events": len(telemetry), "event_ids": [event["event_id"] for event in telemetry],
        "start_inclusive": _iso(start), "end_exclusive": _iso(end), "idempotency_verified": persistence_ok,
    }, status="completed" if persistence_ok else "failed"))

    # Review/finalization are fixture states. Never attribute them to a real
    # person or treat the automatic demo path as permission for live action.
    report = {"schema": "relay.report.v1", "report_id": normalized.mission_id + ":report-v1",
              "report_revision": 1, "mission_id": normalized.mission_id, "station_id": normalized.station_id,
              "simulated": True, "fixture_start": _iso(FIXTURE_START),
              "outcome": gateway["outcome"], "findings": findings, "observations": telemetry,
              "references": reference_context, "accounting": gateway["accounting"],
              "review": {"status": "simulated_review", "reviewed": True, "human_review_performed": False},
              "finalization": {"status": "simulated_finalization", "finalized": True},
              "actuation_enabled": False}
    mission = {"mission_id": normalized.mission_id, "station_id": normalized.station_id,
               "simulated": True, "review_status": "simulated_review", "report": report}
    mongo = MongoMissionStore(live=False)
    try:
        upserted = mongo.upsert_mission(mission)
        restored = mongo.get_mission(normalized.mission_id)
    finally:
        mongo.close()
    if any(result["status"] != "completed" for result in (upserted, restored)):
        raise RuntimeError("Offline mission persistence could not be verified")
    mission_verified = restored["mission"] == mission
    steps.append(_step("mongodb", "Store and read back the simulated reviewed report", {
        **upserted["evidence"], "inserted": upserted["inserted"], "readback_verified": mission_verified,
        "review_status": "simulated_review", "human_review_performed": False,
    }, status="completed" if mission_verified else "failed"))

    suspected = sum(finding["status"] == "suspected_hazard" for finding in findings)
    needs_review = sum(finding["status"] == "needs_review" for finding in findings)
    briefing_text = (f"Simulated inspection: {len(events)} readings across {len({event['robot_id'] for event in events})} "
                     f"robot identifiers. {suspected} suspected hazard findings; {needs_review} findings need review. "
                     "Review and finalization are simulated. No physical inspection, real human approval, or robot movement occurred.")
    # Explicit fixed IDs prevent environment voice/model settings from affecting
    # or enabling this mock briefing.
    speech = synthesize_briefing(briefing_text, reviewed=True, live=False,
                                voice_id="mock-voice", model_id="mock-model")
    steps.append(_step("elevenlabs", "Prepare a reviewed briefing descriptor without audio", {
        "characters": speech["characters"], "cache_key": speech["cache_key"],
        "audio_generated": False, "audio_path": None, "human_review_performed": False,
    }, limitations=["This is a mock descriptor; no speech was synthesized or played."]))

    receipt = create_report_receipt(report, finalized=True, live=False)
    verified = {**verify_report_receipt(report, receipt, live=False), "simulated": True}
    modified_report = {**deepcopy(report), "report_revision": 2}
    tampered = {**verify_report_receipt(modified_report, receipt, live=False), "simulated": True}
    receipt_ok = verified["valid"] is True and tampered["valid"] is False
    steps.append(_step("solana", "Verify the report hash and reject a modified copy", {
        "report_sha256": receipt["report_sha256"], "original_valid": verified["valid"],
        "modified_valid": tampered["valid"], "chain_verified": False, "transaction_signature": None,
    }, status="completed" if receipt_ok else "failed",
        limitations=["Only local hash consistency was tested; no wallet or blockchain transaction exists."]))

    return {"schema_version": "1", "mode": "mock", "simulated": True,
            "status": "completed" if all(step["status"] == "completed" for step in steps) else "failed",
            "mission_id": normalized.mission_id, "mission_outcome": gateway["outcome"],
            "actuation_enabled": False, "network_requests": 0, "live_services_verified": [],
            "production_spend_ledger_modified": False,
            "actual_paid_usd": "0.000000", "steps": steps, "services": _service_inventory(),
            "report": report, "findings": findings, "accounting": gateway["accounting"],
            "references": references, "reference_context": reference_context, "telemetry": telemetry,
            "telemetry_persistence": {"inserted": inserted["inserted"], "replay_inserted": replayed["inserted"],
                                      "readback_count": len(telemetry), "verified": persistence_ok},
            "mission_persistence": {"mission_id": normalized.mission_id, "verified": mission_verified,
                                    "content_sha256": upserted["evidence"]["content_sha256"]},
            "briefing": {**speech, "text": briefing_text, "review_status": "simulated_review",
                         "human_review_performed": False},
            "receipt": receipt, "receipt_verification": verified, "tamper_verification": tampered,
            "limitations": ["All adapter operations in this workflow are mock; remote accounts and deployments were not checked.",
                            "Supplied observations are replayed as simulated and use a fixed fixture epoch.",
                            "Review, finalization, and reference passages are demo fixtures, not real human approval.",
                            "There is no generated audio, blockchain transaction, physical actuation, or cloud provisioning.",
                            "Mock model cost estimates are illustrative; actual new provider charges for this run are zero."]}
