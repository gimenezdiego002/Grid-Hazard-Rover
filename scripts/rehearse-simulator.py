"""Finite, offline spatial mission rehearsal; saves actual simulator results."""

import json
from pathlib import Path
import tempfile

from relay_gateway.simulator import Simulator, SimulatorConflict


def rehearse():
    engine = Simulator()
    sequence = 0

    def send(action, **params):
        nonlocal sequence
        sequence += 1
        return engine.apply(engine.snapshot()["run_id"], f"rehearsal-{sequence}", action, **params)

    def advance():
        for _ in range(60):
            if engine.snapshot()["status"] != "running":
                return engine.snapshot()
            send("step", dt_s=0.5, steps=20)
        raise AssertionError("Mission exceeded the bounded rehearsal")

    send("start")
    send("step", dt_s=0.5, steps=5)
    paused = send("pause")
    assert engine.snapshot()["elapsed_s"] == paused["elapsed_s"]
    send("resume")
    reviewed = advance()
    assert reviewed["status"] == "needs_review"
    assert reviewed["arm_handoff"]["proposal"]["preview_only"] is True
    send("review", decision="acknowledge")
    completed = advance()
    assert completed["status"] == "completed"
    assert completed["metrics"]["governed_requests"] < completed["metrics"]["baseline_requests"]
    assert completed["actual_model_calls"] == completed["actual_api_cost_usd"] == 0

    send("reset")
    send("direct", target={"x": 19.0, "y": 10.0})
    send("inject_fault", robot_id="hexapod", fault="sensor_dropout")
    faulted = engine.snapshot()
    assert faulted["status"] == "faulted"
    assert send("clear_fault")["status"] == "paused"
    send("resume")
    assert advance()["status"] == "needs_review"
    send("review", decision="acknowledge")
    directed = advance()
    assert directed["status"] == "completed"

    send("reset")
    send("start")
    send("inject_fault", robot_id="rover", fault="budget_exhausted")
    refused = advance()
    assert refused["status"] == "needs_review"
    assert refused["metrics"]["budget_refused"] is True
    try:
        send("review", decision="acknowledge")
    except SimulatorConflict:
        pass
    else:
        raise AssertionError("Review bypassed the simulated allowance")
    return {"simulated": True, "actual_model_calls": 0, "actual_api_cost_usd": 0,
            "preset_at_review": reviewed, "preset_completed": completed,
            "directed_fault": faulted, "directed_completed": directed,
            "budget_refused": refused}


def main():
    result = rehearse()
    parent = Path(__file__).resolve().parents[1] / "artifacts" / "simulator-rehearsal"
    parent.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="run-", dir=parent)) / "rehearsal.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "evidence": str(destination),
                      "preset_metrics": result["preset_completed"]["metrics"],
                      "checks": ["preset", "pause/resume", "review", "return",
                                 "directed", "fault/recovery", "budget refusal"]}, indent=2))


if __name__ == "__main__":
    main()
