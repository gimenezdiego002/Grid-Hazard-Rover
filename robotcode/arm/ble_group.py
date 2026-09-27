"""Preview or explicitly run one already-taught LSC action group over Bluetooth.

Default operation is offline. A live run requires a present operator, an explicit
device address/inspected handle, and an already verified stored action group.
Controller completion is not proof of successful physical manipulation.
"""

import argparse
import asyncio
import json

from robotcode.arm.motion import encode_action_group


SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
BATTERY_QUERY = bytes.fromhex("55 55 02 0f")
GROUP_STOP = bytes.fromhex("55 55 02 07")
DISCONNECT_TIMEOUT = 3


class _Frames:
    """Small incremental LSC frame decoder; discard noise and bound retained data."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        if len(self.buffer) > 1024:
            del self.buffer[:-1024]
        frames = []
        while len(self.buffer) >= 3:
            start = self.buffer.find(b"\x55\x55")
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1] == 0x55 else b""
                break
            del self.buffer[:start]
            if len(self.buffer) < 3:
                break
            size = self.buffer[2]
            if not 2 <= size <= 64:
                del self.buffer[0]
                continue
            if len(self.buffer) < size + 2:
                break
            frames.append(bytes(self.buffer[:size + 2]))
            del self.buffer[:size + 2]
        return frames


def _request(group_id, repeats, timeout_seconds):
    frame = encode_action_group(group_id, repeats)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be an integer from 1 to 120")
    return frame


def preview_group(group_id, repeats=1, timeout_seconds=30):
    frame = _request(group_id, repeats, timeout_seconds)
    return {"mode": "dry_run", "group_id": group_id, "repeats": repeats,
            "timeout_seconds": timeout_seconds, "frame_hex": frame.hex(" "),
            "group_contents_verified": False, "actuation_enabled": False,
            "group_write_attempted": False, "completion_reported": False,
            "physical_result": None,
            "note": "Preview only; use an operator-verified stored group for any explicit live run."}


async def _execute_group(client, handle, group_id, repeats, timeout_seconds):
    """Run against one connected client; kept separate for fake-transport tests."""
    frame = _request(group_id, repeats, timeout_seconds)
    result = {"mode": "live_stored_group", "group_id": group_id, "repeats": repeats,
              "timeout_seconds": timeout_seconds, "handle": handle,
              "outcome": "not_sent", "voltage_mv": None,
              "group_write_attempted": False, "group_write_completed": False,
              "completion_reported": False, "stop_write_attempted": False,
              "stop_write_completed": False, "physical_result": None,
              "automatic_retry": False,
              "note": "Controller receipts are not measured physical success. Stop affects action groups only."}
    characteristic = client.services.get_characteristic(handle)
    if (characteristic is None or characteristic.handle != handle
            or characteristic.service_uuid.lower() != SERVICE_UUID
            or characteristic.uuid.lower() != CHARACTERISTIC_UUID
            or not {"notify", "write"}.issubset(characteristic.properties)):
        raise ValueError("Explicit handle must match inspected fff0/ffe1 notify/write characteristic")
    decoder, battery, completed = _Frames(), asyncio.Event(), asyncio.Event()
    phase = "preflight"

    def notified(_, data):
        for incoming in decoder.feed(data):
            if phase == "preflight" and incoming[:4] == bytes.fromhex("55 55 04 0f"):
                result["voltage_mv"] = int.from_bytes(incoming[4:6], "little")
                battery.set()
            elif (phase == "group" and incoming[:4] == bytes.fromhex("55 55 05 08")
                  and incoming[4] == group_id
                  and int.from_bytes(incoming[5:7], "little") == repeats):
                result["completion_reported"] = True
                completed.set()

    subscribed = False
    try:
        await asyncio.wait_for(client.start_notify(characteristic, notified), 3)
        subscribed = True
        await asyncio.wait_for(client.write_gatt_char(characteristic, BATTERY_QUERY, response=True), 3)
        await asyncio.wait_for(battery.wait(), 4)
        # Do not let a prior partial frame become this run's completion receipt.
        decoder.buffer.clear()
        phase = "group"
        result["group_write_attempted"] = True
        await asyncio.wait_for(client.write_gatt_char(characteristic, frame, response=True), 3)
        result["group_write_completed"] = True
        await asyncio.wait_for(completed.wait(), timeout_seconds)
        result["outcome"] = "controller_reported_completion"
    except asyncio.CancelledError:
        result["outcome"] = "unknown" if result["group_write_attempted"] else "not_sent"
        result["reason"] = "cancelled"
    except TimeoutError:
        result["outcome"] = "unknown" if result["group_write_attempted"] else "not_sent"
        result["reason"] = "completion_timeout" if result["group_write_attempted"] else "preflight_timeout"
    except Exception as error:
        result["outcome"] = "unknown" if result["group_write_attempted"] else "not_sent"
        result["reason"] = "transport_error"
        result["error_type"] = type(error).__name__
    finally:
        if result["group_write_attempted"] and result["outcome"] != "controller_reported_completion":
            result["stop_write_attempted"] = True
            try:
                await asyncio.wait_for(client.write_gatt_char(characteristic, GROUP_STOP, response=True), 3)
                result["stop_write_completed"] = True
            except (Exception, asyncio.CancelledError):
                pass
        if subscribed:
            try:
                await asyncio.wait_for(client.stop_notify(characteristic), 3)
            except (Exception, asyncio.CancelledError):
                pass
    return result


async def run_group(*, group_id, repeats=1, timeout_seconds=30, live=False,
                    operator_present=False, group_contents_verified=False, address=None, handle=None):
    preview = preview_group(group_id, repeats, timeout_seconds)
    if type(live) is not bool:
        raise ValueError("live must be an explicit boolean")
    if not live:
        return preview
    if operator_present is not True:
        raise ValueError("Live playback requires an explicitly present operator")
    if group_contents_verified is not True:
        raise ValueError("Live playback requires operator verification of the stored group's contents")
    if not isinstance(address, str) or not address.strip() or len(address) > 128:
        raise ValueError("Live playback requires the inspected device address")
    if type(handle) is not int or not 1 <= handle <= 65535:
        raise ValueError("Live playback requires an explicit inspected characteristic handle")
    # No environment key or dry-run path can import or initialize the transport.
    from bleak import BleakClient, BleakScanner
    device = await asyncio.wait_for(BleakScanner.find_device_by_address(address, timeout=8), 10)
    if device is None:
        raise ValueError("Selected arm is not advertising; no group was sent")
    client, result = BleakClient(device, timeout=12), None
    try:
        await asyncio.wait_for(client.connect(), 12)
        result = await _execute_group(client, handle, group_id, repeats, timeout_seconds)
        result["group_contents_verification"] = "operator_asserted"
    finally:
        try:
            await asyncio.wait_for(client.disconnect(), DISCONNECT_TIMEOUT)
        except (Exception, asyncio.CancelledError):
            if result is not None:
                result["connection_cleanup"] = "unknown"
                result["outcome"] = "unknown"
                result["reason"] = "disconnect_failed"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-id", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--operator-present", action="store_true")
    parser.add_argument("--group-contents-verified", action="store_true")
    parser.add_argument("--address")
    parser.add_argument("--handle", type=int)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run_group(**vars(args)))
    except (Exception, KeyboardInterrupt) as error:
        parser.exit(2, f"Stored-group runner stopped ({type(error).__name__}); no automatic retry. "
                    "If a send was interrupted, physical outcome remains unknown.\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    if result.get("outcome") in {"unknown", "not_sent"}:
        parser.exit(2)


if __name__ == "__main__":
    main()
