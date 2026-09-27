"""Explicit non-motion LSC status query; no servo/action-group command support.

Protocol: Hiwonder LSC Series Controller Communication Protocol, command 15.
Characteristic handle must come from this device's prior GATT inspection.
"""

import argparse
import asyncio
import json
from pathlib import Path

BATTERY_QUERY = bytes.fromhex("55 55 02 0f")
POSITIONS_QUERY = bytes.fromhex("55 55 09 15 06 01 02 03 04 05 06")


def parse_response(received, query):
    if query == "battery":
        marker = received.find(bytes.fromhex("55 55 04 0f"))
        if marker >= 0 and len(received) >= marker + 6:
            return {"voltage_mv": int.from_bytes(received[marker + 4:marker + 6], "little")}
    elif query == "positions":
        marker = received.find(bytes.fromhex("55 55 15 15 06"))
        if marker >= 0 and len(received) >= marker + 23:
            positions = {}
            for offset in range(marker + 5, marker + 23, 3):
                identifier = received[offset]
                if identifier not in range(1, 7) or identifier in positions:
                    return None
                positions[identifier] = int.from_bytes(received[offset + 1:offset + 3], "little")
            return {"controller_reported_positions": positions,
                    "position_semantics": "Controller values; physical joint measurement unverified"}
    return None


async def query_status(address, handle, query="battery"):
    if query not in {"battery", "positions"}:
        raise ValueError("Only non-motion battery or position queries are supported")
    if type(handle) is not int or handle <= 0:
        raise ValueError("Use the positive characteristic handle observed during GATT inspection")
    from bleak import BleakClient, BleakScanner

    device = await BleakScanner.find_device_by_address(address, timeout=8)
    if device is None:
        raise ValueError("Selected device is not advertising")
    received = bytearray()
    event = asyncio.Event()
    packet = BATTERY_QUERY if query == "battery" else POSITIONS_QUERY
    result = {"mode": "non_motion_" + query + "_query", "address": address,
              "handle": handle, "query_hex": packet.hex(" "),
              "motion_commands_sent": 0,
              "protocol_response_verified": False}

    def notified(_, data):
        received.extend(data)
        if len(received) > 1024:
            del received[:-1024]
        parsed = parse_response(received, query)
        if parsed is not None:
            result.update(parsed)
            result["protocol_response_verified"] = True
            event.set()

    async with BleakClient(device, timeout=12) as client:
        characteristic = client.services.get_characteristic(handle)
        if characteristic is None or not {"notify", "write"}.issubset(characteristic.properties):
            raise ValueError("Inspected characteristic must support notify and write")
        if (characteristic.service_uuid.lower() != "0000fff0-0000-1000-8000-00805f9b34fb"
                or characteristic.uuid.lower() != "0000ffe1-0000-1000-8000-00805f9b34fb"):
            raise ValueError("Use the observed Hiwonder fff0/ffe1 interface")
        result["service_uuid"] = characteristic.service_uuid
        result["characteristic_uuid"] = characteristic.uuid
        await client.start_notify(characteristic, notified)
        await client.write_gatt_char(characteristic, packet, response=True)
        try:
            await asyncio.wait_for(event.wait(), timeout=4)
        except TimeoutError:
            pass
        await client.stop_notify(characteristic)
    result["response_hex"] = received.hex(" ")
    result["note"] = "Reply verifies this query only; servo control, calibration and motion remain unverified."
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--handle", required=True, type=int)
    parser.add_argument("--query", choices=["battery", "positions"], default="battery")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(asyncio.wait_for(query_status(args.address, args.handle, args.query), 30))
    except ImportError:
        parser.exit(2, "Install the arm-bluetooth optional dependency first.\n")
    except Exception as error:
        parser.exit(2, f"Status query failed ({type(error).__name__}); no motion command was sent.\n")
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
