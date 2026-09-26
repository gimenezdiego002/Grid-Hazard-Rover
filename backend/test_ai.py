"""Deterministic AI response validation tests. No Gemini calls or API key needed."""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from backend.app.ai.schemas import HazardClassification


class ClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hazard = dict(
            hazard_detected=True,
            hazard_type="fallen_branch",
            severity=3,
            confidence=0.9,
            description="A fallen branch visibly blocks the access path.",
        )
        self.clear = dict(
            hazard_detected=False,
            hazard_type=None,
            severity=None,
            confidence=0.8,
            description="No visible infrastructure hazard in this image.",
        )

    def test_valid_hazard(self) -> None:
        result = HazardClassification.model_validate(self.hazard)
        self.assertTrue(result.hazard_detected)
        self.assertEqual(result.hazard_type, "fallen_branch")
        self.assertEqual(result.severity, 3)

    def test_no_hazard(self) -> None:
        result = HazardClassification.model_validate_json(json.dumps(self.clear))
        self.assertFalse(result.hazard_detected)
        self.assertIsNone(result.severity)
        self.assertIsNone(result.hazard_type)

    def test_inclusive_boundaries(self) -> None:
        for severity in (1, 5):
            for confidence in (0.0, 1.0):
                with self.subTest(severity=severity, confidence=confidence):
                    result = HazardClassification.model_validate(
                        {**self.hazard, "severity": severity, "confidence": confidence}
                    )
                    self.assertEqual(result.severity, severity)
                    self.assertEqual(result.confidence, confidence)

    def test_invalid_severity(self) -> None:
        for value in (0, 6, -1, 2.5, True, "3"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                HazardClassification.model_validate({**self.hazard, "severity": value})

    def test_invalid_confidence(self) -> None:
        for value in (-0.1, 1.1, float("nan"), float("inf"), True, "0.9"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                HazardClassification.model_validate({**self.hazard, "confidence": value})

    def test_detection_requires_category_and_severity(self) -> None:
        for missing in ("hazard_type", "severity"):
            with self.subTest(field=missing), self.assertRaises(ValidationError):
                HazardClassification.model_validate({**self.hazard, missing: None})

    def test_no_detection_rejects_hazard_fields(self) -> None:
        for field, value in (("hazard_type", "fallen_branch"), ("severity", 1)):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                HazardClassification.model_validate({**self.clear, field: value})

    def test_description_validation(self) -> None:
        for value in ("", "  ", "x" * 501, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                HazardClassification.model_validate({**self.hazard, "description": value})
        result = HazardClassification.model_validate({**self.hazard, "description": " Evidence. "})
        self.assertEqual(result.description, "Evidence.")

    def test_unknown_category_and_non_boolean_flag_rejected(self) -> None:
        for field, value in (("hazard_type", "unlisted"), ("hazard_detected", "false"),
                             ("hazard_detected", 1)):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                HazardClassification.model_validate({**self.hazard, field: value})

    def test_external_metadata_and_risk_fields_rejected(self) -> None:
        for field in ("id", "location", "timestamp", "image_url", "risk_score"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                HazardClassification.model_validate({**self.hazard, field: "invented"})

    def test_all_fields_explicitly_required(self) -> None:
        for field in self.clear:
            incomplete = self.clear.copy()
            del incomplete[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                HazardClassification.model_validate(incomplete)

    def test_json_round_trip_and_schema(self) -> None:
        for payload in (self.hazard, self.clear):
            result = HazardClassification.model_validate_json(json.dumps(payload))
            self.assertEqual(json.loads(result.model_dump_json()), payload)
        schema = HazardClassification.model_json_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(self.hazard))
        json.dumps(schema)  # Ready to supply as a structured-output JSON schema.


if __name__ == "__main__":
    unittest.main(verbosity=2)
