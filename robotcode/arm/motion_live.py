"""Explicit operator-taught Bluetooth waypoints; default mode never uses radio.

Starting values are an operator-provided commanded reference, NOT measured
positions. Direct servo moves cannot be stopped by the action-group stop packet.
Ctrl+C prevents subsequent writes; already issued moves may continue. Keep the
verified physical/vendor stop available and the workspace clear.
"""

import argparse
import asyncio
import json
from pathlib import Path

from robotcode.arm.ble_group import BATTERY_QUERY, CHARACTERISTIC_UUID, SERVICE_UUID, _Frames
from robotcode.arm.motion import (
    append_pose, encode_joint_move, load_json, new_recording, replay_preview,
    save_recording, validate_profile, validate_recording,
)


MAX_STEP_US = 100  # Application increment cap, not a mechanical limit.
DISCONNECT_TIMEOUT = 3


class MotionUncertain(RuntimeError):
    def __init__(self, receipt):
        super().__init__("Movement outcome is unknown; do not retry automatically")
        self.receipt = receipt


def _checked_pose(profile, previous, pulses, duration_ms):
    if type(duration_ms) is not int or not 1000 <= duration_ms <= 10_000:
        raise ValueError("Live moves require 1000..10000 ms")
    prior = new_recording("validation", profile, initial_pose=previous)
    checked = append_pose(prior, pulses, duration_ms)["waypoints"][0]
    if any(abs(target - old) > MAX_STEP_US for target, old in zip(pulses, previous)):
        raise ValueError("Each joint may change at most 100 us from the prior commanded reference")
    return checked


def validate_live_recording(recording, repeats=1):
    checked = validate_recording(recording)
    replay_preview(checked, repeats)  # Shared count, duration and repeat bounds.
    if "initial_pose" not in checked:
        raise ValueError("Live replay requires a saved operator-commanded initial reference")
    previous = checked["initial_pose"]["pulses_us"]
    for _ in range(repeats):
        for pose in checked["waypoints"]:
            _checked_pose(checked["profile"], previous, pose["pulses_us"], pose["duration_ms"])
            previous = pose["pulses_us"]
    return checked


def _live_preview(recording, repeats):
    preview = replay_preview(recording, repeats)
    preview["initial_pose"] = recording["initial_pose"]
    preview["simultaneous"] = False
    preview["timing_note"] = "Planned durations exclude BLE write latency; joints are commanded sequentially."
    for event in preview["events"]:
        event.pop("frame_hex")
        event["joint_frames_hex"] = [
            encode_joint_move(servo_id, pulse, event["duration_ms"], recording["profile"]).hex(" ")
            for servo_id, pulse in enumerate(event["pulses_us"], 1)]
    return preview


async def _preflight(client, handle):
    characteristic = client.services.get_characteristic(handle)
    if (characteristic is None or characteristic.handle != handle
            or characteristic.service_uuid.lower() != SERVICE_UUID
            or characteristic.uuid.lower() != CHARACTERISTIC_UUID
            or not {"notify", "write"}.issubset(characteristic.properties)):
        raise ValueError("Handle must match the inspected fff0/ffe1 notify/write characteristic")
    decoder, ready, voltage = _Frames(), asyncio.Event(), None
    def notified(_, data):
        nonlocal voltage
        for frame in decoder.feed(data):
            if frame[:4] == bytes.fromhex("55 55 04 0f"):
                voltage = int.from_bytes(frame[4:6], "little")
                ready.set()
    subscribed = False
    try:
        await asyncio.wait_for(client.start_notify(characteristic, notified), 3)
        subscribed = True
        await asyncio.wait_for(client.write_gatt_char(characteristic, BATTERY_QUERY, response=True), 3)
        await asyncio.wait_for(ready.wait(), 4)
    finally:
        if subscribed:
            await asyncio.wait_for(client.stop_notify(characteristic), 3)
    return characteristic, voltage


async def send_pose(client, characteristic, *, profile, previous, pulses_us, duration_ms,
                    wait=asyncio.sleep):
    """Send six individual frames sequentially; any ambiguous partial write aborts."""
    pose = _checked_pose(profile, previous, pulses_us, duration_ms)
    receipt = {"outcome": "unknown", "frames_attempted": 0, "writes_accepted": 0,
               "wait_elapsed": False, "pulses_us": pose["pulses_us"],
               "duration_ms": duration_ms, "simultaneous": False,
               "physical_positions_measured": False, "physical_result": None,
               "automatic_retry": False}
    try:
        for servo_id, pulse in enumerate(pose["pulses_us"], 1):
            frame = encode_joint_move(servo_id, pulse, duration_ms, profile)
            receipt["frames_attempted"] += 1
            await asyncio.wait_for(client.write_gatt_char(characteristic, frame, response=True), 3)
            receipt["writes_accepted"] += 1
        # Last joint starts later than the first. Wait from the final accepted write.
        await wait(duration_ms / 1000)
        receipt["wait_elapsed"] = True
        receipt["outcome"] = "commands_accepted_and_wait_elapsed"
        return receipt
    except (Exception, asyncio.CancelledError) as error:
        receipt["error_type"] = type(error).__name__
        raise MotionUncertain(receipt) from None


def _result(mode, recording):
    return {"mode": mode, "recording_id": recording["recording_id"],
            "initial_pose": recording["initial_pose"], "receipts": [],
            "outcome": "no_motion_sent", "physical_result": None,
            "physical_positions_measured": False, "automatic_retry": False,
            "note": "Commands were staggered across joints. Neither writes nor elapsed time verify actual motion."}


async def _replay_connected(client, characteristic, recording, repeats, *, wait=asyncio.sleep):
    checked = validate_live_recording(recording, repeats)
    result, previous = _result("live_waypoint_replay", checked), checked["initial_pose"]["pulses_us"]
    try:
        for _ in range(repeats):
            for pose in checked["waypoints"]:
                receipt = await send_pose(client, characteristic, profile=checked["profile"],
                                          previous=previous, **pose, wait=wait)
                result["receipts"].append(receipt)
                previous = pose["pulses_us"]
        result["outcome"] = "commands_accepted_and_wait_elapsed"
    except MotionUncertain as error:
        result["receipts"].append(error.receipt)
        result["outcome"] = "unknown"
    return result


async def _teach_connected(client, characteristic, recording, path, *, read_line=input, wait=asyncio.sleep):
    checked = validate_recording(recording)
    result, previous = _result("live_waypoint_teaching", checked), checked["initial_pose"]["pulses_us"]
    save_recording(path, checked)  # Never overwrite a prior recording.
    try:
        while len(checked["waypoints"]) < 60:
            line = read_line("Six pulse targets and duration_ms, or done: ").strip()
            if line.lower() == "done":
                break
            try:
                values = [int(part) for part in line.split()]
                if len(values) != 7:
                    raise ValueError("Enter exactly six integer pulses followed by duration_ms")
                pose = _checked_pose(checked["profile"], previous, values[:6], values[6])
                pending = append_pose(checked, **pose)  # Capacity check BEFORE radio work.
            except ValueError as error:
                print(f"Rejected without sending: {error}")
                continue
            print("Command targets (not measured positions): " + json.dumps(pose))
            receipt = await send_pose(client, characteristic, profile=checked["profile"],
                                      previous=previous, **pose, wait=wait)
            result["receipts"].append(receipt)
            try:
                save_recording(path, pending, replace=True)
            except OSError:
                result["outcome"] = "unknown"
                result["reason"] = "commands_sent_but_recording_save_failed"
                return result
            checked, previous = pending, pose["pulses_us"]
        result["outcome"] = "teaching_finished" if checked["waypoints"] else "no_motion_sent"
    except MotionUncertain as error:
        result["receipts"].append(error.receipt)
        result["outcome"] = "unknown"
    except (KeyboardInterrupt, EOFError, asyncio.CancelledError):
        result["outcome"] = "teaching_interrupted_between_commands"
    return result


async def run(args):
    if args.command == "teach":
        if not args.profile or args.start_pulses is None:
            raise ValueError("Teaching requires an explicit profile and six operator-provided starting references")
        recording = new_recording(args.name, validate_profile(load_json(args.profile)), initial_pose=args.start_pulses)
    else:
        recording = validate_live_recording(load_json(args.recording), args.repeats)
    if not args.live:
        return (_live_preview(recording, args.repeats) if args.command == "replay" else {
            "mode": "dry_run", "actuation_enabled": False, "recording": recording,
            "motion_commands_sent": 0, "note": "No file saved and no radio imported; live teaching requires explicit flags."})
    if not args.operator_present or not args.initial_pose_confirmed:
        raise ValueError("Live use requires operator presence and confirmation of the supplied unmeasured starting reference")
    if not args.address or type(args.handle) is not int or not 1 <= args.handle <= 65535:
        raise ValueError("Live use requires an inspected device address and explicit handle")
    if args.command == "teach" and args.recording.exists():
        raise ValueError("Use a new recording path; live teaching never appends to an uncertain old session")
    print("Starting reference supplied by operator, NOT measured: " + json.dumps(recording["initial_pose"]))
    print("Ctrl+C prevents further writes; already-issued moves may continue. Keep the verified physical stop available.")
    from bleak import BleakClient, BleakScanner
    device = await asyncio.wait_for(BleakScanner.find_device_by_address(args.address, timeout=8), 10)
    if device is None:
        raise ValueError("Selected arm is not advertising; no motion was sent")
    client, result = BleakClient(device, timeout=12), None
    try:
        await asyncio.wait_for(client.connect(), 12)
        characteristic, voltage = await _preflight(client, args.handle)
        result = (await _teach_connected(client, characteristic, recording, args.recording)
                  if args.command == "teach" else
                  await _replay_connected(client, characteristic, recording, args.repeats))
        result["voltage_mv"] = voltage
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
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("teach", "replay"):
        sub = commands.add_parser(command)
        sub.add_argument("--recording", type=Path, required=True)
        sub.add_argument("--live", action="store_true")
        sub.add_argument("--operator-present", action="store_true")
        sub.add_argument("--initial-pose-confirmed", action="store_true",
                         help="Operator confirms starting reference; this is NOT measured readback")
        sub.add_argument("--address")
        sub.add_argument("--handle", type=int)
        sub.add_argument("--repeats", type=int, default=1, choices=range(1, 6))
        if command == "teach":
            sub.add_argument("--profile", type=Path, required=True)
            sub.add_argument("--start-pulses", type=int, nargs=6, required=True)
            sub.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as error:
        parser.exit(2, f"Waypoint session stopped ({type(error).__name__}): {error}. No automatic retry.\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    if result.get("outcome") == "unknown":
        parser.exit(2)


if __name__ == "__main__":
    main()
