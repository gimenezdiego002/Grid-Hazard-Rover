"""Offline classifier checks: generated in-memory JPEGs and mocked Gemini only."""

from __future__ import annotations

import base64
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from backend.app.ai import classifier as c
from backend.app.config import Settings


class ClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        with BytesIO() as output:
            Image.new("RGB", (16, 16), "white").save(output, format="JPEG")
            self.jpeg = output.getvalue()
        self.payload = dict(hazard_detected=True, hazard_type="fallen_branch",
                            severity=3, confidence=0.9, description="Branch blocks access.")
        self.settings = Settings(gemini_api_key="unit-test-secret", gemini_model="test-model")
        self.config_patch = patch.object(c, "get_settings", return_value=self.settings)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.client_patch = patch.object(c.genai, "Client")
        self.constructor = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.client = self.constructor.return_value.__enter__.return_value
        self.client.interactions.create.return_value = SimpleNamespace(
            status="completed", output_text=json.dumps(self.payload)
        )

    def test_structured_request_and_cleanup(self) -> None:
        result = c.classify_hazard(self.jpeg)
        self.assertEqual(result.severity, 3)
        self.client.interactions.create.assert_called_once()
        request = self.client.interactions.create.call_args.kwargs
        self.assertEqual(request["model"], "test-model")
        self.assertEqual(base64.b64decode(request["input"][0]["data"]), self.jpeg)
        self.assertEqual(request["input"][0]["mime_type"], "image/jpeg")
        self.assertEqual(request["response_format"]["mime_type"], "application/json")
        self.assertIn("hazard_detected", request["response_format"]["schema"]["properties"])
        self.assertFalse(request["store"])
        self.assertEqual(request["timeout"], 30)
        options = self.constructor.call_args.kwargs["http_options"]
        self.assertEqual(options.retry_options.attempts, 0)
        self.assertEqual(options.timeout, 30000)
        self.constructor.return_value.__exit__.assert_called_once()

    def test_no_hazard_preserved(self) -> None:
        self.payload.update(hazard_detected=False, hazard_type=None, severity=None)
        self.client.interactions.create.return_value.output_text = json.dumps(self.payload)
        result = c.classify_hazard(self.jpeg)
        self.assertFalse(result.hazard_detected)
        self.assertIsNone(result.severity)

    def test_fenced_json(self) -> None:
        for prefix in ("```json\n", "```\n"):
            with self.subTest(prefix=prefix):
                result = c.parse_classification(prefix + json.dumps(self.payload) + "\n```")
                self.assertEqual(result.hazard_type, "fallen_branch")

    def test_malformed_and_invalid_responses(self) -> None:
        for text in (None, "", "not-json", "[]", "{}", "x" * (c.MAX_RESPONSE_CHARS + 1),
                     json.dumps({**self.payload, "severity": 6}),
                     json.dumps({**self.payload, "hazard_detected": False})):
            with self.subTest(text=str(text)[:30]), self.assertRaises(c.ClassificationResponseError):
                c.parse_classification(text)

    def test_incomplete_response(self) -> None:
        self.client.interactions.create.return_value.status = "failed"
        with self.assertRaises(c.ClassificationResponseError):
            c.classify_hazard(self.jpeg)

    def test_invalid_image_blocks_api(self) -> None:
        for data in (b"", b"not a jpeg", self.jpeg[:100], self.jpeg[:-100], "not bytes"):
            with self.subTest(data=str(data)[:20]), self.assertRaises(c.ImageInputError):
                c.classify_hazard(data)
        self.constructor.assert_not_called()

    def test_non_jpeg_rejected(self) -> None:
        output = BytesIO()
        Image.new("RGB", (2, 2)).save(output, format="PNG")
        with self.assertRaises(c.ImageInputError):
            c.classify_hazard(output.getvalue())
        self.constructor.assert_not_called()

    def test_size_and_pixel_limits(self) -> None:
        with patch.object(c, "MAX_IMAGE_BYTES", 10), self.assertRaises(c.ImageInputError):
            c.classify_hazard(self.jpeg)
        with patch.object(c, "MAX_IMAGE_PIXELS", 10), self.assertRaises(c.ImageInputError):
            c.classify_hazard(self.jpeg)
        self.constructor.assert_not_called()

    def test_missing_configuration_blocks_api(self) -> None:
        for settings, variable in ((Settings(), "GEMINI_API_KEY"),
                                   (Settings(gemini_api_key="test"), "GEMINI_MODEL")):
            with patch.object(c, "get_settings", return_value=settings):
                with self.assertRaisesRegex(c.GeminiConfigurationError, variable):
                    c.classify_hazard(self.jpeg)
        self.constructor.assert_not_called()

    def test_provider_error_redacted_and_client_closed(self) -> None:
        self.client.interactions.create.side_effect = RuntimeError("unit-test-secret raw response")
        with self.assertRaises(c.GeminiRequestError) as caught:
            c.classify_hazard(self.jpeg)
        self.assertNotIn("unit-test-secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        self.client.interactions.create.assert_called_once()
        self.constructor.return_value.__exit__.assert_called_once()

    def test_timeout_distinct_and_not_retried(self) -> None:
        self.client.interactions.create.side_effect = httpx.ReadTimeout("sensitive detail")
        with self.assertRaises(c.GeminiTimeoutError):
            c.classify_hazard(self.jpeg)
        self.client.interactions.create.assert_called_once()

    def test_unreadable_file(self) -> None:
        with patch("pathlib.Path.open", side_effect=OSError("sensitive path")):
            with self.assertRaisesRegex(c.ImageInputError, "Could not read"):
                c.classify_image_file("missing.jpg")
        self.constructor.assert_not_called()

    def test_file_read_is_bounded(self) -> None:
        with patch("pathlib.Path.open") as opened:
            opened.return_value.__enter__.return_value.read.return_value = self.jpeg
            result = c.classify_image_file("test.jpg")
            opened.return_value.__enter__.return_value.read.assert_called_once_with(c.MAX_IMAGE_BYTES + 1)
        self.assertTrue(result.hazard_detected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
