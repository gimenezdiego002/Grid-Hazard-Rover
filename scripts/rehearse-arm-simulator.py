"""Finite virtual-arm demo rehearsal; never opens a hardware transport."""

import json
from pathlib import Path
import tempfile

from relay_gateway.arm_simulator import ArmSimulator, ArmSimulatorConflict


def rehearse():
    engine = ArmSimulator()
    sequence = 0

    def send(action, **params):
        nonlocal sequence
        sequence += 1
        return engine.apply(engine.snapshot()["run_id"], f"arm-rehearsal-{sequence}", action, **params)

    def advance():
        for _ in range(40):
            if engine.snapshot()["status"] != "running":
                return engine.snapshot()
            send("step", dt_s=0.25, steps=20)
        raise AssertionError("Virtual arm exceeded the bounded rehearsal")

    send("start")
    preset = advance()
    assert preset["status"] == "completed"
    assert preset["payload"]["state"] == "placed"

    send("reset")
    send("capture", name="virtual-home", duration_s=1)
    send("pose", joints_deg=[120, 70, 65, 100, 115, 20], duration_s=2)
    assert advance()["status"] == "completed"
    send("capture", name="virtual-reach", duration_s=2)
    send("replay", repeats=2)
    taught = advance()
    assert taught["status"] == "completed" and taught["repeat_index"] == 2
    assert len(taught["recording"]["poses"]) == 2
    assert taught["recording"]["recording_kind"] == "simulated_joint_angles"

    send("reset")
    send("start")
    send("step", dt_s=0.25, steps=16)
    assert engine.snapshot()["payload"]["state"] == "held"
    fault = send("inject_fault", fault="grip_loss")
    assert fault["status"] == "faulted" and fault["payload"]["state"] == "dropped"
    try:
        send("step")
    except ArmSimulatorConflict:
        pass
    else:
        raise AssertionError("Fault allowed the virtual arm to advance")
    assert engine.snapshot() == fault
    recovered = send("clear_fault")
    assert recovered["status"] == "paused" and recovered["payload"]["state"] == "held"
    send("resume")
    resumed = advance()
    assert resumed["status"] == "completed" and resumed["payload"]["state"] == "placed"

    for state in (preset, taught, fault, recovered, resumed):
        assert state["actuation_enabled"] is False and state["physical_connected"] is False
        assert state["commands_dispatched"] == state["model_calls"] == state["api_cloud_cost_usd"] == 0
        assert state["physical_result"] is None
    return {"simulated": True, "commands_dispatched": 0, "model_calls": 0,
            "preset_completed": preset, "taught_replay_completed": taught,
            "grip_loss": fault, "restored_virtual_checkpoint": recovered,
            "recovered_completed": resumed}


def main():
    result = rehearse()
    parent = Path(__file__).resolve().parents[1] / "artifacts" / "arm-simulator-rehearsal"
    parent.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="run-", dir=parent)) / "rehearsal.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "evidence": str(destination),
                      "checks": ["marker pick/place", "capture/replay twice", "grip-loss freeze",
                                 "explicit checkpoint restoration and resume", "no hardware or model calls"]}, indent=2))


if __name__ == "__main__":
    main()
