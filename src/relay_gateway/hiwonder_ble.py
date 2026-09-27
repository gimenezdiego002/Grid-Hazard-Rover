"""Read-only Bluetooth status probe for the legacy Hiwonder LeArm.

This module deliberately never writes to a characteristic. It verifies that
Windows can see and connect to the arm, discovers its GATT profile, and reports
that the project is still in read-only mode.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any


DEVICE_NAME = "Hiwonder"
STATUS_TIMEOUT_SECONDS = 8.0
_DEVICE_INFO_UUIDS = {
    "00002a29-0000-1000-8000-00805f9b34fb": "manufacturer",
    "00002a24-0000-1000-8000-00805f9b34fb": "model",
    "00002a26-0000-1000-8000-00805f9b34fb": "firmware",
    "00002a28-0000-1000-8000-00805f9b34fb": "software",
}


def _decode(value: bytearray | bytes | None) -> str | None:
    if not value:
        return None
    return bytes(value).decode("utf-8", errors="replace").strip() or None


async def _probe() -> dict[str, Any]:
    from bleak import BleakClient, BleakScanner

    configured_address = os.environ.get("HIWONDER_BLUETOOTH_ADDRESS", "").strip()
    device = None
    if configured_address:
        device = await BleakScanner.find_device_by_address(
            configured_address,
            timeout=STATUS_TIMEOUT_SECONDS,
        )
    if device is None:
        devices = await BleakScanner.discover(timeout=STATUS_TIMEOUT_SECONDS)
        device = next(
            (
                candidate
                for candidate in devices
                if (candidate.name or "").strip().lower() == DEVICE_NAME.lower()
            ),
            None,
        )
    if device is None:
        return {
            "connected": False,
            "device_name": DEVICE_NAME,
            "reason": "Hiwonder was not discovered by the Windows Bluetooth adapter.",
        }

    async with BleakClient(device, timeout=STATUS_TIMEOUT_SECONDS) as client:
        services = client.services
        characteristics = [
            {
                "uuid": characteristic.uuid,
                "properties": sorted(characteristic.properties),
            }
            for service in services
            for characteristic in service.characteristics
        ]
        device_info: dict[str, str] = {}
        for characteristic in (
            characteristic
            for service in services
            for characteristic in service.characteristics
        ):
            key = _DEVICE_INFO_UUIDS.get(characteristic.uuid.lower())
            if key and "read" in characteristic.properties:
                try:
                    value = _decode(await client.read_gatt_char(characteristic.uuid))
                except Exception:
                    value = None
                if value:
                    device_info[key] = value
        return {
            "connected": bool(client.is_connected),
            "device_name": device.name or DEVICE_NAME,
            "address": getattr(device, "address", None),
            "gatt_service_count": len(list(services)),
            "characteristics": characteristics,
            "device_info": device_info,
            "control_mode": "read_only_ble",
            "actuation_enabled": False,
            "writes_performed": 0,
        }


def read_status() -> dict[str, Any]:
    """Return a sanitized, read-only Hiwonder connection status."""
    try:
        return _run_probe()
    except ImportError:
        return {
            "connected": False,
            "device_name": DEVICE_NAME,
            "reason": "The optional bleak Bluetooth dependency is not installed.",
            "control_mode": "unavailable",
            "actuation_enabled": False,
            "writes_performed": 0,
        }
    except Exception as error:
        return {
            "connected": False,
            "device_name": DEVICE_NAME,
            "reason": f"Bluetooth status probe failed: {type(error).__name__}.",
            "control_mode": "unavailable",
            "actuation_enabled": False,
            "writes_performed": 0,
        }


def _run_probe() -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_probe())
    # FastAPI invokes the synchronous route in a worker thread, but preserve a
    # safe fallback if another caller invokes this function from an event loop.
    result: dict[str, Any] = {}
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.update(asyncio.run(_probe()))
        except BaseException as exc:  # pragma: no cover - defensive fallback
            error.append(exc)

    import threading

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join(STATUS_TIMEOUT_SECONDS + 2)
    if error:
        raise error[0]
    if not result:
        raise TimeoutError("Bluetooth probe timed out")
    return result
