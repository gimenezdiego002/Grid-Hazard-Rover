"""Send a prepared JPEG as a simulated Grid Hazard Rover observation.

Examples:
    python rover/simulate_upload.py --image C:/path/to/pothole.jpg
    python rover/simulate_upload.py --image C:/path/to/pothole.jpg \
        --api-url https://api.fieldsight.biz --token "$env:ROVER_API_TOKEN"

This uses the same multipart contract as the Raspberry Pi client. It does not
pretend that a downloaded photograph is a physical observation: the source
defaults to ``simulated-rover-01`` and is shown in the API metadata.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


MAX_IMAGE_BYTES = 8 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path, help="JPEG file to upload")
    parser.add_argument("--api-url", default=os.getenv("ROVER_API_URL", "http://127.0.0.1:8000"), help="Backend origin")
    parser.add_argument("--longitude", type=float, default=-80.36)
    parser.add_argument("--latitude", type=float, default=25.76)
    parser.add_argument("--timestamp", help="ISO timestamp; defaults to current UTC time")
    parser.add_argument("--source", default="simulated-rover-01")
    parser.add_argument("--token", default=os.getenv("ROVER_API_TOKEN"), help="Optional bearer token for a public backend")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the request without sending it")
    return parser.parse_args()


def iso_timestamp(raw: str | None) -> str:
    if raw is None:
        return datetime.now(timezone.utc).isoformat()
    value = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--timestamp must include a timezone, for example 2026-09-26T12:00:00Z")
    return parsed.isoformat()


def validate(args: argparse.Namespace) -> tuple[Path, str]:
    image = args.image.expanduser().resolve()
    if not image.is_file():
        raise ValueError(f"JPEG does not exist: {image}")
    if image.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("The rover endpoint accepts JPEG files only (.jpg or .jpeg)")
    if image.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("JPEG exceeds the backend limit of 8 MiB")
    if not -180 <= args.longitude <= 180 or not -90 <= args.latitude <= 90:
        raise ValueError("coordinates are outside valid longitude/latitude bounds")
    return image, iso_timestamp(args.timestamp)


def main() -> int:
    args = parse_args()
    try:
        image, timestamp = validate(args)
    except (OSError, ValueError) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 2

    api_url = args.api_url.rstrip("/") + "/ingest/photo"
    print(f"Simulated rover: {args.source}")
    print(f"JPEG: {image.name} ({image.stat().st_size:,} bytes)")
    print(f"Location: [{args.longitude}, {args.latitude}] (longitude, latitude)")
    print(f"Captured: {timestamp}")
    print(f"Endpoint: {api_url}")
    if args.dry_run:
        print("Dry run complete; no upload sent.")
        return 0

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    try:
        with image.open("rb") as handle:
            response = requests.post(
                api_url,
                files={"image": (image.name, handle, mimetypes.types_map.get(image.suffix.lower(), "image/jpeg"))},
                data={
                    "longitude": str(args.longitude),
                    "latitude": str(args.latitude),
                    "timestamp": timestamp,
                    "source": args.source,
                },
                headers=headers,
                timeout=90,
            )
    except requests.RequestException as error:
        print(f"Upload failed: {error}", file=sys.stderr)
        return 1

    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": response.text[:500]}
    if not response.ok:
        print(f"Upload rejected ({response.status_code}): {payload.get('detail', payload)}", file=sys.stderr)
        return 1

    classification = payload.get("classification") or {}
    print(f"Upload accepted ({response.status_code})")
    print(f"Hazard detected: {payload.get('hazard_detected')}")
    print(f"Classification: {classification.get('hazard_type') or 'none'}")
    print(f"Severity: {classification.get('severity') or 'n/a'} / 5")
    print(f"Confidence: {classification.get('confidence', 0):.0%}")
    print(f"Persisted: {payload.get('persisted')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
