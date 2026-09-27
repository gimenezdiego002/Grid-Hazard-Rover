"""Build a finite, offline Relay demo packet from the canonical synthetic fixture."""

import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory, mkdtemp

from relay_gateway.gateway import compare_scenario, run_scenario
from relay_gateway.integrations.workflow import run_integration_demo
from relay_gateway.missions import MissionConflict, MissionEngine
from relay_gateway.models import Scenario
from relay_gateway.providers import MockProvider


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "scenarios" / "leak.json"
PROVIDERS = ["snowflake", "gemini", "tiger", "mongodb", "elevenlabs", "solana"]
LIMITS = [
    "Every reading, mission assignment, model result, review and adapter operation in this packet is simulated.",
    "Workflow completion does not establish environmental safety or real human approval. No hardware is connected or actuated.",
    "The six adapters run locally as mocks. This packet establishes no live provider, cloud, domain or blockchain proof.",
    "The ElevenLabs stage creates a descriptor, not audio. The Solana stage checks a local hash, not a transaction.",
    "Costs and tokens are illustrative simulation measurements; new paid provider charges for this packet are zero.",
    "The comparison covers one synthetic wet interval. No real-world accuracy, energy, carbon, battery or water savings were measured.",
    "Existing cloud resources may accrue costs independently. This command neither checks nor modifies the canonical spending ledger.",
]


def load_fixture():
    # No arbitrary fixture option: bound even the checked-in file before parsing.
    with FIXTURE.open("rb") as stream:
        raw = stream.read(32_769)
    if len(raw) > 32_768:
        raise ValueError("Canonical fixture exceeds the 32 KiB rehearsal limit")
    scenario = Scenario.model_validate_json(raw)
    if (scenario.scenario_id != "synthetic-water-onset-v1" or
            not scenario.simulated or len(scenario.observations) != 12 or
            any(not row.simulated or row.kind != "water" or row.evidence_uri is not None or
                row.timestamp_seconds > 120 or row.value_milli is None or
                not 0 <= row.value_milli <= 1000 for row in scenario.observations)):
        raise ValueError("Rehearsal requires the canonical twelve-reading synthetic water fixture")
    return scenario, hashlib.sha256(raw).hexdigest()


def _try_announcement(engine, mission_id, action_id):
    before = engine.snapshot(mission_id)
    try:
        engine.apply(mission_id, action_id, "complete_task",
                     {"task_id": "announce", "outcome": "completed"})
    except MissionConflict:
        return {"rejected": True, "state_preserved": engine.snapshot(mission_id) == before}
    return {"rejected": False, "state_preserved": engine.snapshot(mission_id) == before}


def _mission(engine, scenario, mode, directory, *, refused=False):
    mission_id = "rehearsal-refusal" if refused else "rehearsal-" + mode
    fixture = scenario.model_copy(deep=True)
    fixture.mission_id = mission_id
    if refused:
        fixture.budget.max_requests = 0
    planned = engine.create_mission(
        mission_id, "plan", mode=mode, station_id=fixture.station_id,
        target_id="loading-bay" if mode == "directed" else "inspection-area",
        scout_id="intellio-rover" if mode == "directed" else None,
        second_view=True,
    )
    engine.apply(mission_id, "start", "start")
    engine.apply(mission_id, "monitor", "complete_task", {"task_id": "monitor", "outcome": "completed"})
    analysis = run_scenario(fixture, "economy", provider=MockProvider(),
                            store_path=directory / (mission_id + ".sqlite"))
    if any(event["reason"] == "budget_refused" for event in analysis["events"]):
        outcome = "budget_refused"
    elif analysis["outcome"] == "needs_review":
        outcome = "needs_review"
    elif any(finding["status"] == "suspected_hazard" for finding in analysis["findings"]):
        outcome = "suspected_hazard"
    else:
        outcome = "completed"
    before_review = engine.apply(mission_id, "scout", "complete_task",
                                 {"task_id": "scout", "outcome": outcome})
    early_announcement = _try_announcement(engine, mission_id, "announce-before-review")
    after_review = engine.apply(mission_id, "review", "simulate_review", {"decision": "acknowledge"})
    if refused:
        blocked_announcement = _try_announcement(engine, mission_id, "announce-after-refusal")
    else:
        blocked_announcement = None
        engine.apply(mission_id, "announce", "complete_task", {"task_id": "announce", "outcome": "completed"})
    return {"planned": planned, "analysis": analysis, "before_review": before_review,
            "early_announcement": early_announcement, "after_review": after_review,
            "blocked_announcement": blocked_announcement, "final": engine.snapshot(mission_id)}


def verify_packet(packet):
    """Compute checks from returned evidence; never rely on Python assert/-O."""
    checks = []

    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})

    for name, mission in packet["missions"].items():
        final, analysis = mission["final"], mission["analysis"]
        check(name + ": disconnected simulation", final["simulated"] and
              not final["actuation_enabled"] and final["network_requests"] == 0 and
              final["review"]["human_review_performed"] is False and
              final["environment_safety"] == "not_established")
        check(name + ": mock analysis audit", analysis["provider_mode"] == "mock" and
              analysis["simulated"] and analysis["audit_verified"] and
              analysis["accounting"]["actual_paid_usd"] == "0.000000" and
              not analysis["accounting"]["shared_spend_operation_ids"])
        check(name + ": review gates announcement", mission["before_review"]["status"] == "needs_review" and
              mission["early_announcement"] == {"rejected": True, "state_preserved": True})
        check(name + ": unavailable second view skipped", any(task["task_id"] == "second_view" and
              task["status"] == "skipped" for task in final["proposed_tasks"]))
        if name == "zero_request_refusal":
            check(name + ": zero requests and tokens", analysis["accounting"]["new_requests"] == 0 and
                  analysis["accounting"]["requests"] == 0 and analysis["accounting"]["tokens"] == 0)
            check(name + ": refused analysis keeps local alarm", analysis["outcome"] == "needs_review" and
                  any(event["reason"] == "budget_refused" and event["local_alarm"] for event in analysis["events"]))
            check(name + ": acknowledgement cannot release refusal", final["status"] == "needs_review" and
                  final["budget_refused"] is True and "complete_task" not in final["allowed_actions"] and
                  mission["blocked_announcement"] == {"rejected": True, "state_preserved": True} and
                  any(task["task_id"] == "announce" and task["status"] == "pending" for task in final["proposed_tasks"]))
        else:
            check(name + ": mission completes with suspected hazard", final["status"] == "completed" and
                  final["suspected_hazard"] and not final["budget_refused"] and
                  final["progress"]["completed"] == final["progress"]["total"] == 4 and
                  analysis["outcome"] == "complete" and analysis["accounting"]["new_requests"] == 1)
            check(name + ": expected mission assignment", final["mode"] == name and
                  final["target_id"] == ("loading-bay" if name == "directed" else "inspection-area") and
                  any(role["role"] == "scout" and role["device_id"] == "intellio-rover" for role in final["planned_roles"]))

    comparison = packet["comparison"]
    baseline, economy = comparison["baseline"], comparison["economy"]
    check("comparison: complete mock runs", comparison["comparison_complete"] and comparison["simulated"] and
          comparison["actual_paid_usd"] == "0.000000" and all(row["provider_mode"] == "mock" and
          row["audit_verified"] and row["outcome"] == "complete" for row in (baseline, economy)))
    check("comparison: twelve versus one requests", baseline["accounting"]["new_requests"] ==
          baseline["accounting"]["requests"] == 12 and economy["accounting"]["new_requests"] ==
          economy["accounting"]["requests"] == 1)
    check("comparison: fewer simulated tokens", baseline["accounting"]["tokens"] > economy["accounting"]["tokens"] > 0)
    check("comparison: same labeled incident detected", all(row["evaluation"].get("available") and
          row["evaluation"]["labeled_hazard_episodes"] == row["evaluation"]["detected_hazard_episodes"] == 1 and
          row["evaluation"]["detection_latency_seconds"] == [0] and
          row["evaluation"]["false_positive_findings"] == 0 for row in (baseline, economy)))

    integration = packet["integration"]
    check("integration: six completed mock adapters", integration["status"] == "completed" and
          [step["provider"] for step in integration["steps"]] == PROVIDERS and all(
              step["status"] == "completed" and step["mode"] == "mock" and step["simulated"] and
              step["remote_verified"] is False for step in integration["steps"]))
    check("integration: no remote work claimed", integration["mode"] == "mock" and integration["simulated"] and
          integration["network_requests"] == 0 and integration["actuation_enabled"] is False and
          integration["production_spend_ledger_modified"] is False and not integration["live_services_verified"] and
          integration["actual_paid_usd"] == "0.000000" and
          all(service["remote_verified"] is False for service in integration["services"]))
    check("integration: twelve telemetry readings persist idempotently", integration["telemetry_persistence"] ==
          {"inserted": 12, "replay_inserted": 0, "readback_count": 12, "verified": True} and
          len(integration["telemetry"]) == 12 and all(row["simulated"] for row in integration["telemetry"]))
    reference_ids = {row["reference_id"] for row in integration["references"]}
    check("integration: report readback and reference grounding", integration["mission_persistence"]["verified"] and
          integration["mission_outcome"] == "complete" and bool(integration["findings"]) and all(
              bool(finding["cited_reference_ids"]) and set(finding["cited_reference_ids"]).issubset(reference_ids)
              for finding in integration["findings"]))
    check("integration: no real review or audio", integration["report"]["review"]["human_review_performed"] is False and
          integration["report"]["finalization"]["status"] == "simulated_finalization" and
          integration["briefing"]["audio_path"] is None and integration["briefing"]["request_sent"] is False)
    check("integration: local receipt accepts original and rejects tamper", integration["receipt"]["signature"] is None and
          integration["receipt"]["chain_verified"] is False and integration["receipt_verification"]["valid"] is True and
          integration["tamper_verification"]["valid"] is False and
          integration["tamper_verification"]["status"] == "report_changed")
    return checks


def build_packet():
    scenario, fixture_sha256 = load_fixture()
    engine = MissionEngine()
    with TemporaryDirectory(prefix="relay-rehearsal-") as temporary:
        directory = Path(temporary)
        missions = {mode: _mission(engine, scenario, mode, directory) for mode in ("preset", "directed")}
        missions["zero_request_refusal"] = _mission(engine, scenario, "preset", directory, refused=True)
    packet = {
        "schema": "relay.rehearsal.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "simulated": True, "fixture": {"path": "scenarios/leak.json", "sha256": fixture_sha256,
                                        "scenario_id": scenario.scenario_id, "readings": len(scenario.observations)},
        "missions": missions, "comparison": compare_scenario(scenario),
        "integration": run_integration_demo(scenario.model_dump(mode="json")), "limitations": list(LIMITS),
    }
    packet["checks"] = verify_packet(packet)
    packet["status"] = "passed" if all(check["passed"] for check in packet["checks"]) else "failed"
    return packet


def render_html(packet):
    """No script, remote assets, raw HTML from findings, or browser execution."""
    def text(value):
        return escape(str(value), quote=True)

    comparison = packet["comparison"]
    rows = "".join("<tr><td>" + text(mode) + "</td><td>" + text(comparison[mode]["accounting"]["requests"]) +
                   "</td><td>" + text(comparison[mode]["accounting"]["tokens"]) + "</td><td>$" +
                   text(comparison[mode]["accounting"]["estimated_usd"]) + "</td></tr>"
                   for mode in ("baseline", "economy"))
    missions = "".join("<li><strong>" + text(name) + ": " + text(mission["final"]["status"]) +
                       "</strong> — human review: " + text(mission["final"]["review"]["human_review_performed"]) +
                       "; environmental safety: " + text(mission["final"]["environment_safety"]) + "</li>"
                       for name, mission in packet["missions"].items())
    checks = "".join("<li>" + ("PASS" if check["passed"] else "FAIL") + " — " +
                     text(check["name"]) + "</li>" for check in packet["checks"])
    limitations = "".join("<li>" + text(limit) + "</li>" for limit in packet["limitations"])
    evidence = text(json.dumps(packet, indent=2, ensure_ascii=False, allow_nan=False))
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Relay offline rehearsal</title><style>
body{font:16px/1.6 system-ui,sans-serif;max-width:1000px;margin:32px auto;padding:0 20px;background:#f5f7fa;color:#182b38}
h1,h2{line-height:1.2}.banner{background:#fce9ad;border:2px solid #8c6200;padding:16px;font-weight:700}
table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #bcc7ce;padding:10px;text-align:left}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:16px;border:1px solid #bcc7ce}
li{margin:6px 0}summary{cursor:pointer;font-weight:700}details{margin:20px 0}
</style></head><body><p class="banner">SIMULATION · OFFLINE · NO HARDWARE OR LIVE PROVIDER PROOF</p>
<h1>Relay rehearsal: """ + text(packet["status"].upper()) + "</h1><p>Generated " + text(packet["generated_at"]) + """.
This saved packet works without the dashboard or an internet connection. It replays the canonical twelve-reading water fixture.</p>
<h2>Mission boundaries</h2><ul>""" + missions + """</ul><p>Both inspection workflows require a simulated review transition.
The zero-request mission must keep its local alarm and remain blocked after simulated acknowledgement.</p>
<h2>Illustrative model work</h2><table><thead><tr><th>Policy</th><th>Mock requests</th><th>Simulated tokens</th>
<th>Simulated estimated USD</th></tr></thead><tbody>""" + rows + """</tbody></table>
<p>Actual new paid provider charges for this replay: $0. These results cover one synthetic incident and are not energy or carbon measurements.</p>
<h2>Six mock adapters</h2><p>Snowflake reference retrieval → Gemini gateway → Tiger Data telemetry → MongoDB report →
ElevenLabs briefing descriptor → Solana local report hash. Cloud hosting and domain setup require separate evidence.</p>
<h2>Proof limits</h2><ul>""" + limitations + """</ul><details open><summary>Verified outcome checks</summary><ul>""" + checks + """</ul></details>
<details><summary>Full evidence (also saved as packet.json)</summary><pre>""" + evidence + "</pre></details></body></html>\n"


def save_packet(packet, output_directory):
    # Exclusive unique directory creation preserves all previous and unrelated files.
    serialized = json.dumps(packet, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    html = render_html(packet)
    output_directory = Path(output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    run_directory = Path(mkdtemp(prefix="run-", dir=output_directory))
    (run_directory / "packet.json").write_text(serialized, encoding="utf-8")
    (run_directory / "index.html").write_text(html, encoding="utf-8")
    return run_directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "rehearsal",
                        help="Parent folder for a new unique run directory (default: artifacts/rehearsal)")
    args = parser.parse_args(argv)
    try:
        packet = build_packet()
        output = save_packet(packet, args.output_dir)
    except Exception as exc:
        # Exception messages may include environment data; never echo them.
        print("Offline rehearsal could not complete (" + type(exc).__name__ + "). No passing packet was produced.", file=sys.stderr)
        return 1
    passed = sum(check["passed"] for check in packet["checks"])
    print(f"SIMULATION: {packet['status']} ({passed}/{len(packet['checks'])} checks); zero new paid provider charges.")
    print(f"Evidence: {output / 'packet.json'}")
    print(f"Open offline: {output / 'index.html'}")
    return 0 if packet["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
