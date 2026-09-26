"""Explicit finite Jev demo. Default commands never construct live providers."""

import argparse
import json
from pathlib import Path
import re

from .jev_comparison import compare_missions, run_mission, synthetic_missions


def main(argv=None):
    parser = argparse.ArgumentParser(description="Simulated Relay Gemini/Jev/Pollard supervision")
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("compare", help="Offline three-arm fixture comparison")
    compare.add_argument("--output", type=Path)
    demo = commands.add_parser("demo", help="One offline synthetic mission")
    demo.add_argument("--strategy", choices=("rules", "gemini", "hybrid"), default="hybrid")
    demo.add_argument("--scenario", choices=[row["mission_id"] for row in synthetic_missions()], default="wet_episode")
    demo.add_argument("--output", type=Path)
    live = commands.add_parser("live-smoke", help="Explicit metered inference on synthetic observations; no hardware")
    live.add_argument("--live", action="store_true", required=True)
    live.add_argument("--provider", choices=("gemini", "jev", "both"), required=True)
    live.add_argument("--operation-id", required=True, help="Stable unique reviewed run ID; do not vary it to evade duplicate protection")
    live.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            result = compare_missions()
        elif args.command == "demo":
            mission = next(row for row in synthetic_missions() if row["mission_id"] == args.scenario)
            result = run_mission(mission, args.strategy)
        else:
            result = _live_smoke(args)
        encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            if args.command != "live-smoke":
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(encoded, encoding="utf-8")
            print(json.dumps({"output": str(args.output.resolve()), "run_kind": result.get("run_kind"),
                              "task_outcome": result.get("task_outcome"), "summary": result.get("summary")}))
        else:
            print(encoded)
        if args.command == "live-smoke":
            providers = result.get("provider_results", [result["provider_result"]] if "provider_result" in result else [])
            if any(provider.get("status") != "completed" for provider in providers):
                return 2
        return 0
    except Exception:
        # Provider exception bodies and headers may carry credentials.
        print(json.dumps({"status": "blocked", "reason": "Configuration, admission or execution failed; no automatic retry.",
                          "hint": "See docs/jev-demo.md; retain unresolved reservations and local alarms."}))
        return 2


def _live_smoke(args):
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", args.operation_id) is None:
        raise ValueError("Use a short non-sensitive operation ID")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive claim prevents concurrent runs from overwriting another proof.
    # The pending/failure marker survives interruptions and must be inspected.
    with args.output.open("x", encoding="utf-8") as proof:
        proof.write(json.dumps({"status": "pending", "operation_id": args.operation_id,
                                "note": "Inspect canonical ledger before any retry."}) + "\n")
        proof.flush()
        try:
            result = _live_smoke_body(args)
        except Exception:
            proof.seek(0)
            proof.truncate()
            proof.write(json.dumps({"status": "failed_or_unknown", "operation_id": args.operation_id,
                                    "note": "Configuration or execution failed. Inspect canonical ledger; do not auto-retry."}) + "\n")
            raise
        proof.seek(0)
        proof.truncate()
        proof.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
        return result


def _live_smoke_body(args):
    from .jev_budget import JevTaskLedger
    from .jev_gemini import GeminiRoleProvider
    from .jev_provider import JevProvider

    if re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", args.operation_id) is None:
        raise ValueError("Use a short non-sensitive operation ID")
    ledger = JevTaskLedger()
    jev = JevProvider.from_environment(allow_live=True, spend_ledger=ledger) if args.provider in {"jev", "both"} else None
    gemini = None
    try:
        if args.provider in {"gemini", "both"}:
            gemini = GeminiRoleProvider.from_environment(allow_live=True, spend_ledger=ledger)
            mission = next(row for row in synthetic_missions() if row["mission_id"] == "wet_episode")
            mission["mission_id"] = args.operation_id
            result = run_mission(mission, "hybrid" if jev else "gemini", jev=jev, gemini=gemini, fixture=False)
        else:
            response = jev.decide(json.dumps({"health": "fresh", "local_alarm": True, "changed": True,
                                  "simulated": True, "water_threshold_exceeded": True}),
                                  ("hold", "request_evidence", "escalate_gemini"),
                                  f"{args.operation_id}:jev:attempt-0", timeout_seconds=5)
            result = {"run_kind": "actual_provider_on_synthetic_observations", "provider_result": response.as_dict(),
                      "simulated": True, "actuation_enabled": False,
                      "task_outcome": "supervision_recorded" if response.status == "completed" else "needs_review",
                      "local_alarm": True, "safe_hold": True}
        result["task_spending"] = ledger.task_snapshot()
        result["limitations"] = ["No physical action, image decoding, leak-source confirmation or energy measurement.",
                                 "Provider usage estimates are not invoices; unknown reservations remain held."]
        return result
    finally:
        if gemini is not None:
            gemini.close()


if __name__ == "__main__":
    raise SystemExit(main())
