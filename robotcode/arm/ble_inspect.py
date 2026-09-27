"""Inspect one explicitly selected BLE device's GATT metadata; never write commands."""

import argparse
import asyncio
import json
from pathlib import Path


async def inspect_device(address, read_device_info=False):
    from bleak import BleakClient, BleakScanner

    device = await BleakScanner.find_device_by_address(address, timeout=8)
    if device is None:
        raise ValueError("Selected device is not advertising")
    async with BleakClient(device, timeout=12) as client:
        info = {}
        if read_device_info:
            for key, short in (("manufacturer", "2a29"), ("model", "2a24"),
                               ("firmware", "2a26"), ("software", "2a28")):
                characteristic = client.services.get_characteristic(f"0000{short}-0000-1000-8000-00805f9b34fb")
                if characteristic and "read" in characteristic.properties:
                    value = await client.read_gatt_char(characteristic)
                    info[key] = bytes(value).decode("utf-8", errors="replace").strip("\x00")
        return {"mode": "gatt_metadata_only", "name": device.name,
                "address": device.address, "connection_observed": client.is_connected,
                "motion_commands_sent": 0, "characteristic_reads": len(info), "device_info": info,
                "actuation_enabled": False, "protocol_verified": False,
                "services": [{"uuid": service.uuid,
                    "characteristics": [{"uuid": char.uuid, "properties": char.properties,
                                         "handle": char.handle}
                                        for char in service.characteristics]}
                    for service in client.services],
                "note": "Service discovery only. This does not verify servo control or position feedback."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True, help="Device address observed in a prior scan")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--read-device-info", action="store_true", help="Read standard manufacturer/model/version fields only")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(asyncio.wait_for(inspect_device(args.address, args.read_device_info), timeout=25))
    except ImportError:
        parser.exit(2, "Install the optional arm-bluetooth dependency in the project .venv first.\n")
    except Exception as error:
        parser.exit(2, f"GATT discovery failed ({type(error).__name__}); no motion commands were sent.\n")
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
