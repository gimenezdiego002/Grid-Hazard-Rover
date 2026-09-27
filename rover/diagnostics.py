"""Non-moving diagnostics for mock mode and future FNK0052 bring-up."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from rover.config import RobotConfig
from rover.controller import FreenoveFNK0052Controller, MockHexapodController


def run_diagnostics(config: RobotConfig) -> dict:
    checks: list[dict] = []

    def record(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    if config.mode == "mock":
        controller = MockHexapodController(config.robot_id)
        try:
            controller.initialize()
            record("controller", "pass", "mock controller initialized; simulated=true")
            record("distance_sensor", "pass", f"simulated {controller.get_distance().distance_cm:.1f} cm")
            record("camera", "pass", f"simulated JPEG ({len(controller.capture_frame())} bytes)")
            record("servo_and_shield", "not_tested", "mock mode never touches GPIO or servos")
        finally:
            controller.close()
    else:
        controller = FreenoveFNK0052Controller(
            config.robot_id, config.freenove_server_path,
            allow_physical_actuation=config.allow_physical_actuation,
        )
        path = config.freenove_server_path
        ready = path is not None and path.is_dir() and all(
            (path / name).is_file() for name in controller.REQUIRED_FILES
        )
        record("official_freenove_software", "pass" if ready else "fail",
               str(path) if ready else "configure the official Code/Server directory")
        record("controller", "not_tested", "physical initialization is never automatic in diagnostics")
        record("servo_and_shield", "not_tested", "requires supervised hardware checklist")
        record("distance_sensor", "not_tested", "requires connected HC-SR04 on the FNK0052 shield")
        record("camera", "not_tested", "requires configured Picamera2 hardware")

    for name, url in (("grid_backend", config.backend_url), ("relay_gateway", config.relay_url)):
        parsed = urlsplit(url)
        valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        record(name, "configured" if valid else "fail", url if valid else "invalid URL")
    record("gemini", "configured" if os.getenv("GEMINI_API_KEY") else "optional_missing",
           "key present (not displayed)" if os.getenv("GEMINI_API_KEY") else "mock demo does not require a key")
    location_ready = (
        config.location_mode == "fixed"
        and config.fixed_longitude is not None
        and config.fixed_latitude is not None
    )
    record(
        "location_provider", "configured" if location_ready else "not_configured",
        "operator-provided fixed coordinate" if location_ready
        else "supply an operator/mission coordinate or future GPS adapter; FNK0052 has no assumed GPS",
    )
    return {
        "robot_model": "FNK0052",
        "mode": config.mode,
        "simulated": config.mode == "mock",
        "physical_actuation_enabled": config.allow_physical_actuation,
        "checks": checks,
    }


def main() -> int:
    result = run_diagnostics(RobotConfig.from_env())
    print(json.dumps(result, indent=2))
    return 0 if all(check["status"] != "fail" for check in result["checks"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
