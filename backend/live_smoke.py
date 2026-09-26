"""Optional one-call Gemini smoke test; never part of automated tests.

Usage: python -m backend.live_smoke path\to\sample.jpg
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.ai.classifier import ClassificationError, classify_image_file
from backend.app.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one LIVE Gemini image classification.")
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.gemini_api_key or not settings.gemini_model:
        print("LIVE SKIPPED: GEMINI_API_KEY and GEMINI_MODEL are required.")
        return 0
    if not args.image.is_file():
        print(f"LIVE SKIPPED: image not found: {args.image}")
        return 0
    try:
        result = classify_image_file(args.image)
    except ClassificationError as error:
        print(f"LIVE FAILED: {error}")
        return 1
    print("LIVE GEMINI RESULT")
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
