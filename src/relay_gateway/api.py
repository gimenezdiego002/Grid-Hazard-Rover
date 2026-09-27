"""Loopback demo API. HTTP endpoints always use the mock provider."""

from pathlib import Path
import json
import os
from threading import Lock
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .gateway import compare_scenario, run_scenario
from .models import MissionRequest


PROJECT_ROOT = Path(os.environ.get("RELAY_ASSET_ROOT", Path(__file__).resolve().parents[2])).resolve()
app = FastAPI(title="Relay local simulator", version="0.1.0",
              description="Offline mock fleet inspection. No hardware actuation or paid API calls.")

_mission_engine = None
_mission_engine_lock = Lock()
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


@app.get("/api/hiwonder/status")
def hiwonder_status():
    """Read-only local BLE status; never sends an arm-control command."""
    from .hiwonder_ble import read_status
    return read_status()


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
