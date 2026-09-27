"""Offline tests for signed call ingestion, privacy, and company review."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.calls.repository import clear_call_repository_cache
from backend.app.config import Settings
from backend.app.main import create_app


SECRET = "webhook-test-secret"
TOKEN = "company-test-token"


def transcription_event(conversation_id: str = "conv_test_001") -> dict:
    return {
        "type": "post_call_transcription",
        "event_timestamp": 1_800_000_000,
        "data": {
            "conversation_id": conversation_id,
            "agent_id": "agent_fieldsight",
            "agent_name": "FieldSight Operations",
            "has_audio": True,
            "metadata": {"call_duration_secs": 72},
            "conversation_initiation_client_data": {
                "dynamic_variables": {
                    "company_id": "utility-a",
                    "company_name": "Utility A",
                    "consent_to_record": "yes",
                }
            },
            "transcript": [
                {"role": "agent", "message": "How can I help?", "time_in_call_secs": 1},
                {
                    "role": "user",
                    "message": "There is an exposed cable and flood water near NW 7th Street.",
                    "time_in_call_secs": 9,
                },
            ],
            "analysis": {
                "transcript_summary": "Caller reported flooding near an exposed cable.",
                "call_successful": True,
                "data_collection_results": {
                    "category": {"value": "field_hazard"},
                    "sentiment": {"value": "concerned"},
                    "location": {"value": "NW 7th Street, Miami"},
                    "action_items": {"value": ["Dispatch a qualified reviewer."]},
                },
            },
        },
    }


def signed(payload: dict, timestamp: int | None = None) -> tuple[bytes, dict[str, str]]:
    stamp = int(time.time()) if timestamp is None else timestamp
    body = json.dumps(payload, separators=(",", ":")).encode()
    digest = hmac.new(SECRET.encode(), str(stamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return body, {"Content-Type": "application/json", "ElevenLabs-Signature": f"t={stamp},v0={digest}"}


class CallRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = Settings(
            elevenlabs_webhook_secret=SECRET,
            calls_dashboard_token=TOKEN,
            call_audio_storage_dir=Path(self.temporary.name),
        )
        clear_call_repository_cache()
        patches = [
            patch("backend.app.main.get_settings", side_effect=lambda: self.settings),
            patch("backend.app.calls.routes.get_settings", side_effect=lambda: self.settings),
            patch("backend.app.calls.repository.get_settings", side_effect=lambda: self.settings),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {TOKEN}"}

    def ingest(self, payload: dict | None = None):
        body, headers = signed(payload or transcription_event())
        return self.client.post("/webhooks/elevenlabs/post-call", content=body, headers=headers)

    def test_signed_call_is_stored_and_company_view_is_redacted(self):
        response = self.ingest()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversation_id"], "conv_test_001")

        summary = self.client.get("/api/calls", headers=self.auth)
        self.assertEqual(summary.status_code, 200)
        item = summary.json()[0]
        self.assertNotIn("transcript", item)
        self.assertEqual(item["analysis"]["urgency"], "high")
        self.assertEqual(item["company_name"], "Utility A")

        detail = self.client.get("/api/calls/conv_test_001", headers=self.auth).json()
        self.assertEqual(len(detail["transcript"]), 2)
        self.assertTrue(detail["consent_to_record"])
        self.assertEqual(detail["recording_status"], "provider_retained")

    def test_invalid_signature_and_missing_company_token_are_rejected(self):
        body, headers = signed(transcription_event())
        headers["ElevenLabs-Signature"] = f"t={int(time.time())},v0=bad"
        self.assertEqual(
            self.client.post("/webhooks/elevenlabs/post-call", content=body, headers=headers).status_code,
            401,
        )
        self.assertEqual(self.client.get("/api/calls").status_code, 401)
        self.assertEqual(
            self.client.get("/api/calls", headers={"Authorization": "Bearer wrong"}).status_code,
            401,
        )

    def test_delivery_is_idempotent_and_review_is_preserved(self):
        self.assertEqual(self.ingest().status_code, 200)
        update = self.client.patch(
            "/api/calls/conv_test_001/review",
            json={"status": "in_review", "note": "Assigned to field operations."},
            headers=self.auth,
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(self.ingest().status_code, 200)
        detail = self.client.get("/api/calls/conv_test_001", headers=self.auth).json()
        self.assertEqual(detail["review_status"], "in_review")
        self.assertEqual(detail["reviewer_note"], "Assigned to field operations.")
        self.assertEqual(len(self.client.get("/api/calls", headers=self.auth).json()), 1)

    def test_audio_is_ignored_by_default(self):
        payload = {
            "type": "post_call_audio",
            "data": {
                "conversation_id": "conv_test_001",
                "full_audio": base64.b64encode(b"ID3mock-audio").decode(),
            },
        }
        body, headers = signed(payload)
        response = self.client.post(
            "/webhooks/elevenlabs/post-call-audio", content=body, headers=headers
        )
        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(list(Path(self.temporary.name).glob("*.mp3")), [])

    def test_opt_in_audio_is_bounded_and_protected(self):
        self.settings = Settings(
            elevenlabs_webhook_secret=SECRET,
            calls_dashboard_token=TOKEN,
            elevenlabs_save_call_audio=True,
            call_audio_storage_dir=Path(self.temporary.name),
            call_audio_max_bytes=1_000,
        )
        self.assertEqual(self.ingest().status_code, 200)
        audio = b"ID3mock-audio"
        payload = {
            "type": "post_call_audio",
            "data": {
                "conversation_id": "conv_test_001",
                "full_audio": base64.b64encode(audio).decode(),
            },
        }
        body, headers = signed(payload)
        response = self.client.post(
            "/webhooks/elevenlabs/post-call-audio", content=body, headers=headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sha256"], hashlib.sha256(audio).hexdigest())
        self.assertEqual(self.client.get("/api/calls/conv_test_001/audio").status_code, 401)
        saved = self.client.get("/api/calls/conv_test_001/audio", headers=self.auth)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.content, audio)

    def test_malformed_event_does_not_persist(self):
        payload = transcription_event()
        payload["data"]["conversation_id"] = ""
        self.assertEqual(self.ingest(payload).status_code, 422)
        self.assertEqual(self.client.get("/api/calls", headers=self.auth).json(), [])


if __name__ == "__main__":
    unittest.main()
