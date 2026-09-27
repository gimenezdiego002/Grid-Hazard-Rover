"""Finite Bluetooth advertisement discovery. Never connects or writes to a device."""

import argparse
import asyncio
import json
from pathlib import Path


async def discover(seconds=8, name_filters=None):
    from bleak import BleakScanner

    filters = name_filters or ["learm", "hiwonder", "lobot", "bt05", "hc-08", "hmsoft"]
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    candidates = []
    for device, advertisement in found.values():
        name = advertisement.local_name or device.name or ""
        if not any(part.casefold() in name.casefold() for part in filters):
            continue
        candidates.append({"name": name, "address": device.address,
                           "service_uuids": advertisement.service_uuids,
                           "rssi_dbm": advertisement.rssi,
                           "identity_verified": False})
    return {"mode": "advertisement_discovery_only", "simulated": False,
            "connected": False, "actuation_enabled": False,
            "scan_seconds": seconds, "devices_seen": len(found),
            "candidates": sorted(candidates, key=lambda row: row["name"]),
            "note": "Name matches are candidates, not proof of arm identity or protocol compatibility."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=8, choices=range(2, 31), metavar="2..30")
    parser.add_argument("--name", action="append", help="Advertised name substring; repeat to include alternatives")
    parser.add_argument("--output", type=Path, help="Optional local JSON file; use .state/ for device addresses")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(discover(args.seconds, args.name))
    except ImportError:
        parser.exit(2, "Install the optional arm-bluetooth dependency in the project .venv first.\n")
    except Exception as error:
        parser.exit(2, f"Bluetooth scan failed ({type(error).__name__}); no device was connected or commanded.\n")
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
