from __future__ import annotations

from datetime import datetime, timezone
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.integrations.relay_adapter import (
    RelayHazardCandidate,
    relay_candidate_to_hazard,
)
from backend.app.main import create_app
from backend.app.repository import MemoryRepository, get_repository
from relay_gateway.models import Finding
from shared.schemas import PointGeometry


def candidate_payload() -> dict:
    return {
        "finding": {
            "status": "suspected_hazard",
            "hazard_type": "flooding",
            "confidence_milli": 875,
            "summary": "Standing water is visible near the inspection route.",
            "recommended_action": "Request field review.",
            "cited_reference_ids": ["procedure-1"],
        },
        "event_id": "camera-42",
        "mission_id": "miami-demo",
        "robot_id": "fnk0052-01",
        "location": {"type": "Point", "coordinates": [-80.36, 25.76]},
        "timestamp": "2026-09-27T14:00:00Z",
        "severity": 4,
        "reviewed": True,
        "simulated": True,
        "evidence_ref": "mock-frame-42",
    }


class RelayAdapterTests(unittest.TestCase):
    def test_reviewed_candidate_becomes_stable_canonical_hazard(self) -> None:
        candidate = RelayHazardCandidate.model_validate(candidate_payload())
        first = relay_candidate_to_hazard(candidate)
        second = relay_candidate_to_hazard(candidate)

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.location.coordinates, (-80.36, 25.76))
        self.assertEqual(first.confidence, 0.875)
        self.assertEqual(first.severity, 4)
        self.assertTrue(first.metadata["simulated"])

    def test_provisional_or_incomplete_finding_is_rejected(self) -> None:
        for change in (
            {"reviewed": False},
            {"severity": 6},
            {"timestamp": "2026-09-27T14:00:00"},
            {"finding": {**candidate_payload()["finding"], "status": "needs_review"}},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                RelayHazardCandidate.model_validate({**candidate_payload(), **change})

    def test_clear_finding_is_not_a_hazard(self) -> None:
        finding = Finding(
            status="clear",
            confidence_milli=900,
            summary="No visible hazard.",
            recommended_action="Continue monitoring.",
        )
        with self.assertRaises(ValidationError):
            RelayHazardCandidate(
                finding=finding,
                event_id="event-1",
                mission_id="mission-1",
                robot_id="robot-1",
                location=PointGeometry(coordinates=(-80.36, 25.76)),
                timestamp=datetime.now(timezone.utc),
                severity=1,
                reviewed=True,
                simulated=True,
            )


class RelayIntegrationRouteTests(unittest.TestCase):
    def test_route_persists_hazard_and_updates_grid_snapshot(self) -> None:
        repository = MemoryRepository(projects=[], records=[], hazards=[])
        app = create_app()
        app.dependency_overrides[get_repository] = lambda: repository
        with TestClient(app) as client:
            response = client.post("/api/integrations/relay/hazards", json=candidate_payload())
            self.assertEqual(response.status_code, 201, response.text)
            hazard = response.json()
            self.assertEqual(hazard["location"]["coordinates"], [-80.36, 25.76])
            self.assertEqual(client.get("/api/hazards").json(), [hazard])

    def test_relay_app_is_mounted_without_endpoint_collisions(self) -> None:
        with TestClient(create_app(), client=("127.0.0.1", 12345)) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            relay = client.get("/relay/health")
            self.assertEqual(relay.status_code, 200)
            self.assertTrue(relay.json()["simulated"])
            self.assertFalse(relay.json()["actuation_enabled"])

            event = {
                "schema_version": "1",
                "event_id": "heartbeat-1",
                "mission_id": "miami-demo",
                "source_id": "fnk0052-01",
                "station_id": "inspection-area",
                "kind": "heartbeat",
                "timestamp_seconds": 1,
                "simulated": True,
                "status": "idle",
            }
            accepted = client.post("/relay/fleet/telemetry", json=event)
            duplicate = client.post("/relay/fleet/telemetry", json=event)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            self.assertTrue(duplicate.json()["duplicate"])


if __name__ == "__main__":
    unittest.main()
