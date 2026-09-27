"""Offline end-to-end proof of the future FNK0052 integration path."""

from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.ai.schemas import HazardClassification
from backend.app.main import create_app
from backend.app.repository import MemoryRepository, get_repository
from relay_gateway.fleet_gateway import FleetConfig, TelemetryCache
from rover.backend_adapter import PhotoObservation
from rover.controller import MockHexapodController
from rover.location import FixedLocationProvider
from rover.navigation import NavigationPolicy, NavigationRunner
from rover.telemetry import inspection_envelope, status_envelope


def run_mock_demo() -> dict:
    """Run finite simulated hardware, Relay, image ingest, matching, and risk."""

    controller = MockHexapodController(distances_cm=(100.0, 20.0, 20.0))
    navigation = NavigationRunner(controller, NavigationPolicy(obstacle_distance_cm=30.0))
    relay_cache = TelemetryCache(FleetConfig())
    repository = MemoryRepository()
    stages: list[dict] = []

    try:
        controller.initialize()
        controller.stand()
        stages.append({"stage": "initialize_and_stand", "simulated": True, "status": "ok"})

        decisions = [navigation.step().model_dump(mode="json") for _ in range(3)]
        stages.append({"stage": "local_navigation", "simulated": True, "decisions": decisions})

        jpeg = controller.capture_frame()
        fix = FixedLocationProvider(
            -80.355, 25.765, source="operator_demo_coordinate", simulated=True
        ).get_location()
        observation = PhotoObservation(jpeg=jpeg, location=fix, robot_id=controller.robot_id)
        stages.append({
            "stage": "camera_and_location",
            "simulated": True,
            "jpeg_bytes": len(jpeg),
            "coordinates": list(fix.location.coordinates),
            "location_source": fix.source,
        })

        heartbeat = status_envelope(
            controller.health_check(), mission_id="fnk0052-demo", station_id="miami-demo",
            timestamp_seconds=1,
        )
        evidence = inspection_envelope(
            controller.health_check(), mission_id="fnk0052-demo", station_id="miami-demo",
            timestamp_seconds=2, evidence_ref="mock-frame-001",
        )
        acknowledgements = [relay_cache.accept(event) for event in (heartbeat, evidence)]
        duplicate = relay_cache.accept(evidence)
        stages.append({
            "stage": "relay_telemetry",
            "simulated": True,
            "accepted": sum(1 for item in acknowledgements if item["accepted"]),
            "duplicate_rejected": duplicate["duplicate"],
            "latest_sequence": relay_cache.read()["latest_sequence"],
        })

        classification = HazardClassification(
            hazard_detected=True,
            hazard_type="flooding_or_standing_water",
            severity=4,
            confidence=0.91,
            description="Mock classifier: standing water is visible in the simulated frame.",
        )
        app = create_app()
        app.dependency_overrides[get_repository] = lambda: repository
        files, data = observation.multipart()
        with patch("backend.app.api.classify_hazard", return_value=classification):
            with TestClient(app, client=("127.0.0.1", 12345)) as client:
                ingest = client.post("/ingest/photo", files=files, data=data)
                ingest.raise_for_status()
                summary = client.get("/api/demo-summary")
                summary.raise_for_status()
        payload = ingest.json()
        snapshot = summary.json()
        stages.append({
            "stage": "grid_hazard_pipeline",
            "simulated": True,
            "classifier": "mock",
            "hazard_id": payload["hazard"]["id"],
            "hazards": len(snapshot["hazards"]),
            "matches": len(snapshot["matches"]),
            "risk_cells": len(snapshot["risk_cells"]),
        })
        return {
            "status": "completed",
            "robot_model": "FNK0052",
            "simulated": True,
            "physical_hardware_tested": False,
            "paid_api_calls": 0,
            "stages": stages,
        }
    finally:
        controller.stop()
        stages.append({
            "stage": "failsafe_stop",
            "simulated": True,
            "movement_state": controller.health_check().movement_state.value,
        })
        controller.close()


def main() -> int:
    print(json.dumps(run_mock_demo(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
