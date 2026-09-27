"""Deliberate local supervisor demo; Gemini roles remain explicit fixtures."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from .jev_comparison import synthetic_missions
from .jev_gemini import FixtureGeminiRoles
from .jev_open_client import LoopbackOpenJevProvider
from .jev_supervisor import RelaySupervisor


def run_demo(provider, mission_name="wet_episode"):
    health = provider.health()
    mission = next(row for row in synthetic_missions() if row["mission_id"] == mission_name)
    run_id = "openjev-" + uuid.uuid4().hex[:16]
    gemini = FixtureGeminiRoles()
    try:
        plan = gemini.run("mission", {"text": mission["text"]}, run_id + ":mission")
        supervisor = RelaySupervisor(run_id, jev=provider, gemini=gemini)
        events = [supervisor.observe(frame) for frame in mission["frames"]]
        facts = {"local_alarm_latched": supervisor.local_alarm,
                 "review_required": any(event["status"] == "needs_review" for event in events)}
        report = gemini.run("report", {"facts": facts}, run_id + ":report")
        provider_results = [result for event in events for result in event["provider_results"]]
        # An uncalibrated NLI abstention is a completed inspection attempt that
        # needs review. Transport, deadline and admission failures are distinct.
        incomplete = any(result.get("status") != "completed"
                         and result.get("reason") != "insufficient_nli_support"
                         for result in provider_results)
        return {"schema_version": "1", "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "run_kind": "local_openjev_with_gemini_fixtures", "mission_id": mission_name,
                "provider_modes": {"supervisor": "actual_local_openjev", "mission_evidence_report": "fixture"},
                "observations_simulated": True, "actions_simulated": True, "actuation_enabled": False,
                "cloud_api_requests": 0, "actual_paid_api_usd": "0", "energy_joules": None,
                "execution_status": "incomplete" if incomplete else "completed",
                "service": health, "mission": plan, "events": events, "report": report,
                "facts": facts, "scope": "Synthetic observations; no robot or leak-detection validation."
                }
    finally:
        gemini.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "demo"))
    parser.add_argument("--local", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--mission", choices=("wet_episode", "dry_monitoring", "conflicting"), default="wet_episode")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    proof = None
    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            proof = args.output.open("x", encoding="utf-8")
            proof.write(json.dumps({"status": "pending", "note": "Local inference may still be running; inspect before retrying."}) + "\n")
            proof.flush()
        provider = LoopbackOpenJevProvider(allow_local=args.local, port=args.port)
        result = provider.health() if args.command == "status" else run_demo(provider, args.mission)
        encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if proof is not None:
            proof.seek(0)
            proof.truncate()
            proof.write(encoded)
        print(encoded)
        return 2 if result.get("execution_status") == "incomplete" else 0
    except Exception:
        if proof is not None:
            try:
                proof.seek(0)
                proof.truncate()
                proof.write(json.dumps({"status": "failed_or_unknown", "note": "Local worker unavailable or unverified. No hosted fallback was attempted."}) + "\n")
            except OSError:
                pass  # A failed disk write does not justify rerunning inference.
        parser.exit(1, "Local OpenJev worker unavailable or unverified; no hosted fallback was attempted.\n")
    finally:
        if proof is not None:
            proof.close()


if __name__ == "__main__":
    raise SystemExit(main())
