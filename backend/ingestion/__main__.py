"""Run with python -m backend.ingestion --help."""

import argparse
from datetime import date
import json
from pathlib import Path
import sys

import httpx

from .arcgis import ArcGIS
from .normalize import normalize_snapshot
from .sources import SOURCES, source_for


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Public ArcGIS to validated local JSON; no database required.")
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe", help="Check source fields and filtered count")
    probe.add_argument("source", choices=SOURCES)
    probe.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="Reference date YYYY-MM-DD (default: today)")
    fetch = commands.add_parser("fetch", help="Download a verifiable WGS84 source snapshot")
    fetch.add_argument("source", choices=SOURCES)
    fetch.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="Work Program includes this calendar year's fiscal label onward; not exact construction dates")
    fetch.add_argument("--limit", type=int, default=100, help="Row sample limit; 0 for all, up to 10,000")
    fetch.add_argument("--output", type=Path, required=True, help="New snapshot file; existing files are not overwritten")
    normalize = commands.add_parser("normalize", help="Validate a saved snapshot and export a new directory")
    normalize.add_argument("snapshot", type=Path)
    normalize.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "normalize":
            if args.output.exists():
                raise ValueError("Output directory already exists; choose a new run directory")
            snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
            result = normalize_snapshot(snapshot)
            args.output.mkdir(parents=True)
            for name, value in result.items():
                write_json(args.output / f"{name}.json", value)
            print(json.dumps(result["manifest"], indent=2))
            return 2 if result["rejected"] else 0
        if args.command == "fetch" and args.output.exists():
            raise ValueError("Snapshot already exists; choose a new filename")
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            arcgis = ArcGIS(client)
            source = source_for(args.source, args.as_of)
            if args.command == "probe":
                print(json.dumps(arcgis.inspect(source), indent=2))
            else:
                result = arcgis.fetch(source, limit=args.limit)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                write_json(args.output, result)
                print(f"Saved {result['selected_count']}/{result['total_count']} rows ({result['selection']}) to {args.output}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
