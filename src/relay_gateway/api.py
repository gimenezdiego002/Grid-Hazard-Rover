"""Loopback demo API. HTTP endpoints always use the mock provider."""

from pathlib import Path
import json
import os
from threading import Lock
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .gateway import compare_scenario, run_scenario
from .models import MissionRequest


PROJECT_ROOT = Path(os.environ.get("RELAY_ASSET_ROOT", Path(__file__).resolve().parents[2])).resolve()
app = FastAPI(title="FieldSight local simulator", version="0.1.0",
              description="Offline mock fleet inspection. No hardware actuation or paid API calls.")

_mission_engine = None
_mission_engine_lock = Lock()
_simulator = None
_simulator_lock = Lock()
_arm_simulator = None
_arm_simulator_lock = Lock()
_MISSION_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$"


class MissionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mission_id: str = Field(pattern=_MISSION_ID, max_length=96)
    action_id: str = Field(pattern=_MISSION_ID, max_length=96)
    mode: Literal["preset", "directed"] = "preset"
    station_id: str = Field(default="station-a", pattern=_MISSION_ID, max_length=96)
    target_id: str = Field(default="inspection-area", pattern=_MISSION_ID, max_length=96)
    scout_id: str | None = Field(default=None, pattern=_MISSION_ID, max_length=96)
    second_view: bool = False


class MissionActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: str = Field(pattern=_MISSION_ID, max_length=96)
    action: Literal["start", "pause", "resume", "cancel", "complete_task", "simulate_review"]
    payload: dict = Field(default_factory=dict, max_length=4)


class SimulatorPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: float = Field(ge=0, le=24, allow_inf_nan=False)
    y: float = Field(ge=0, le=16, allow_inf_nan=False)


class SimulatorActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str = Field(pattern=_MISSION_ID, max_length=96)
    action_id: str = Field(pattern=_MISSION_ID, max_length=96)
    action: Literal["start", "step", "pause", "resume", "stop", "reset", "direct",
                    "inject_fault", "clear_fault", "review"]
    dt_s: float = Field(default=0.5, ge=0.1, le=2, allow_inf_nan=False)
    steps: int = Field(default=1, ge=1, le=20)
    target: SimulatorPoint | None = None
    robot_id: Literal["rover", "hexapod"] | None = None
    fault: Literal["blocked_path", "sensor_dropout", "low_battery", "budget_exhausted"] | None = None
    decision: Literal["acknowledge", "abort"] | None = None


class ArmSimulatorActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str = Field(pattern=_MISSION_ID, max_length=96)
    action_id: str = Field(pattern=_MISSION_ID, max_length=96)
    action: Literal["start", "pose", "capture", "replay", "clear_recording", "step", "pause",
                    "resume", "stop", "reset", "inject_fault", "clear_fault"]
    joints_deg: list[Annotated[float, Field(ge=0, le=180, allow_inf_nan=False)]] | None = Field(
        default=None, min_length=6, max_length=6)
    duration_s: float = Field(default=2, ge=0.5, le=10, allow_inf_nan=False)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    repeats: int = Field(default=1, ge=1, le=5)
    dt_s: float = Field(default=0.25, ge=0.1, le=2, allow_inf_nan=False)
    steps: int = Field(default=1, ge=1, le=20)
    fault: Literal["joint_stall", "grip_loss"] | None = None


def arm_simulator():
    """Independent virtual joint scene; cannot initialize a hardware transport."""
    global _arm_simulator
    with _arm_simulator_lock:
        if _arm_simulator is None:
            from .arm_simulator import ArmSimulator
            _arm_simulator = ArmSimulator()
    return _arm_simulator


@app.get("/api/simulator/arm")
def read_arm_simulator():
    return arm_simulator().snapshot()


@app.post("/api/simulator/arm/actions")
def arm_simulator_action(request: ArmSimulatorActionRequest):
    from .arm_simulator import ArmSimulatorConflict
    try:
        return arm_simulator().apply(**request.model_dump(exclude_unset=True))
    except ArmSimulatorConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def simulator():
    """A process-local, explicitly stepped scene with no hardware clients."""
    global _simulator
    with _simulator_lock:
        if _simulator is None:
            from .simulator import Simulator
            _simulator = Simulator()
    return _simulator


@app.get("/api/simulator")
def read_simulator():
    return simulator().snapshot()


@app.post("/api/simulator/actions")
def simulator_action(request: SimulatorActionRequest):
    from .simulator import SimulatorConflict
    try:
        return simulator().apply(**request.model_dump(exclude_unset=True))
    except SimulatorConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/simulator")
def simulator_page():
    path = PROJECT_ROOT / "web" / "simulator.html"
    if not path.is_file():
        raise HTTPException(404, "Simulator interface not found")
    return FileResponse(path)


def mission_engine():
    """One bounded process-local simulation; never an actuator connection."""
    global _mission_engine
    with _mission_engine_lock:
        if _mission_engine is None:
            from .missions import MissionEngine
            _mission_engine = MissionEngine()
    return _mission_engine


def mission_operation(operation):
    from .missions import MissionConflict
    try:
        return operation()
    except KeyError:
        raise HTTPException(404, "Simulated mission not found; the service may have restarted.") from None
    except MissionConflict:
        raise HTTPException(409, "Action conflicts with the mission state or an existing action ID.") from None
    except ValueError:
        raise HTTPException(400, "Invalid simulated mission request. Check target, scout and task details.") from None


@app.get("/api/missions/inventory")
def mission_inventory():
    from .missions import default_inventory
    return {"inventory": default_inventory(), "simulated": True,
            "physical_connections_verified": False, "actuation_enabled": False,
            "mission_storage": "bounded_process_memory"}


@app.post("/api/missions")
def plan_mission(request: MissionPlanRequest):
    return mission_operation(lambda: mission_engine().create_mission(**request.model_dump()))


@app.get("/api/missions/{mission_id}")
def read_mission(mission_id: str):
    return mission_operation(lambda: mission_engine().snapshot(mission_id))


@app.post("/api/missions/{mission_id}/actions")
def act_on_simulation(mission_id: str, request: MissionActionRequest):
    return mission_operation(lambda: mission_engine().apply(mission_id, **request.model_dump()))


@app.get("/health")
def health():
    return {"status": "ok", "provider_mode": "mock", "simulated": True,
            "actuation_enabled": False, "paid_api_enabled": False,
            "session_api_ceiling_usd": "15.00", "reserved_usd": "5.00"}


@app.post("/api/run")
def run(request: MissionRequest):
    return run_scenario(request.scenario, request.strategy)


@app.post("/api/compare")
def compare(request: MissionRequest):
    return compare_scenario(request.scenario)


@app.post("/api/integrations/demo")
def integration_demo():
    """Exercise adapters offline; no live mode or credential input is accepted."""
    from .integrations.workflow import run_integration_demo
    fixture = json.loads((PROJECT_ROOT / "scenarios" / "leak.json").read_text(encoding="utf-8"))
    return run_integration_demo(fixture)


@app.get("/scenarios/leak.json")
def scenario():
    path = PROJECT_ROOT / "scenarios" / "leak.json"
    if not path.is_file():
        raise HTTPException(404, "Demo scenario has not been created")
    return FileResponse(path, media_type="application/json")


@app.get("/")
def index():
    path = PROJECT_ROOT / "web" / "index.html"
    if not path.is_file():
        return {"message": "Local gateway ready", "docs": "/docs", "health": "/health"}
    return FileResponse(path)


web = PROJECT_ROOT / "web"
if web.is_dir():
    app.mount("/static", StaticFiles(directory=web), name="static")
