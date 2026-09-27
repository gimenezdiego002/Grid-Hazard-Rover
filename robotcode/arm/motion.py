"""Record commanded LeArm waypoints and preview finite LSC protocol playback.

No Bluetooth, serial, GPIO, timing loop, or actuation is implemented here.
The limits in a profile are user-supplied bounds, not hardware certification.
Protocol: https://wiki.hiwonder.com/projects/24-Channel-Servo-Controller/en/latest/docs/2_Communication_Protocol.html
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


MAX_WAYPOINTS = 60
MAX_REPEATS = 5
MAX_REPLAY_MS = 120_000
MAX_JSON_BYTES = 65_536
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")


def _integer(value, minimum, maximum, name):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _identifier(value, name):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identifier")
    return value


def _fields(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f"{name} has missing or unsupported fields")


def validate_profile(profile):
    """Validate all six explicitly supplied servo bounds without guessing any."""
    _fields(profile, {"schema_version", "profile_id", "controller_family", "units",
                      "reviewed_by", "joint_bounds_us"}, "profile")
    if (profile["schema_version"] != "1" or profile["controller_family"] != "LSC"
            or profile["units"] != "microseconds"):
        raise ValueError("Expected version 1 LSC profile in microseconds")
    _identifier(profile["profile_id"], "profile_id")
    _identifier(profile["reviewed_by"], "reviewed_by")
    bounds = profile["joint_bounds_us"]
    if type(bounds) is not list or len(bounds) != 6:
        raise ValueError("Provide explicit bounds for servos 1 through 6")
    for index, pair in enumerate(bounds, 1):
        if type(pair) is not list or len(pair) != 2:
            raise ValueError(f"Servo {index} requires [minimum, maximum]")
        # LSC PC software documents 500..2500 as the outer pulse envelope.
        # This is not approval to use that whole range on an assembled LeArm.
        low = _integer(pair[0], 500, 2500, f"Servo {index} minimum")
        high = _integer(pair[1], 500, 2500, f"Servo {index} maximum")
        if low > high:
            raise ValueError(f"Servo {index} minimum exceeds maximum")
    return deepcopy(profile)


def _pose(pulses_us, duration_ms, profile):
    duration_ms = _integer(duration_ms, 100, 10_000, "duration_ms")
    if type(pulses_us) is not list or len(pulses_us) != 6:
        raise ValueError("A waypoint must explicitly specify all six commanded pulses")
    pulses = [_integer(value, *bounds, f"Servo {index} pulse")
              for index, (value, bounds) in enumerate(zip(pulses_us, profile["joint_bounds_us"]), 1)]
    return {"pulses_us": pulses, "duration_ms": duration_ms}


def new_recording(name, profile, *, initial_pose=None):
    result = {"schema_version": "1", "recording_id": _identifier(name, "recording_id"),
              "recording_kind": "commanded_waypoints", "physical_positions_measured": False,
              "profile": validate_profile(profile), "waypoints": []}
    if initial_pose is not None:
        result["initial_pose"] = {
            "pulses_us": _pose(initial_pose, 1000, result["profile"])["pulses_us"],
            "source": "operator_commanded_reference", "measured": False,
        }
    return result


def validate_recording(recording):
    expected = {"schema_version", "recording_id", "recording_kind",
                "physical_positions_measured", "profile", "waypoints"}
    if type(recording) is dict and "initial_pose" in recording:
        expected.add("initial_pose")
    _fields(recording, expected, "recording")
    if (recording["schema_version"] != "1" or recording["recording_kind"] != "commanded_waypoints"
            or recording["physical_positions_measured"] is not False):
        raise ValueError("Recording must describe commanded waypoints without measured position claims")
    checked = new_recording(recording["recording_id"], recording["profile"])
    if "initial_pose" in recording:
        initial = recording["initial_pose"]
        _fields(initial, {"pulses_us", "source", "measured"}, "initial_pose")
        if initial["source"] != "operator_commanded_reference" or initial["measured"] is not False:
            raise ValueError("Initial pose must be an unmeasured operator-commanded reference")
        checked["initial_pose"] = new_recording(
            recording["recording_id"], recording["profile"], initial_pose=initial["pulses_us"])["initial_pose"]
    waypoints = recording["waypoints"]
    if type(waypoints) is not list or len(waypoints) > MAX_WAYPOINTS:
        raise ValueError(f"Recording must contain 0..{MAX_WAYPOINTS} waypoints")
    for waypoint in waypoints:
        _fields(waypoint, {"pulses_us", "duration_ms"}, "waypoint")
        checked["waypoints"].append(_pose(**waypoint, profile=checked["profile"]))
    if sum(row["duration_ms"] for row in checked["waypoints"]) > MAX_REPLAY_MS:
        raise ValueError("A recording may contain at most 120 seconds of commanded movement")
    return checked


def append_pose(recording, pulses_us, duration_ms):
    """Return an independent recording with one user-supplied command appended."""
    updated = validate_recording(recording)
    updated["waypoints"].append(_pose(pulses_us, duration_ms, updated["profile"]))
    return validate_recording(updated)


def replace_pose(recording, index, pulses_us, duration_ms):
    """Replace a zero-based waypoint, preserving the input on any error."""
    updated = validate_recording(recording)
    index = _integer(index, 0, len(updated["waypoints"]) - 1, "index")
    updated["waypoints"][index] = _pose(pulses_us, duration_ms, updated["profile"])
    return validate_recording(updated)


def encode_servo_move(pulses_us, duration_ms, profile):
    """Return an LSC CMD_SERVO_MOVE frame for six targets; never send it."""
    pose = _pose(pulses_us, duration_ms, validate_profile(profile))
    payload = bytearray([0x55, 0x55, 6 * 3 + 5, 0x03, 6])
    payload.extend(pose["duration_ms"].to_bytes(2, "little"))
    for servo_id, pulse in enumerate(pose["pulses_us"], 1):
        payload.append(servo_id)
        payload.extend(pulse.to_bytes(2, "little"))
    return bytes(payload)


def encode_action_group(group_id, repeats=1):
    """Encode a previously taught group. Zero/infinite repeats are forbidden."""
    group_id = _integer(group_id, 0, 254, "group_id")
    repeats = _integer(repeats, 1, MAX_REPEATS, "repeats")
    return bytes([0x55, 0x55, 0x05, 0x06, group_id]) + repeats.to_bytes(2, "little")


def encode_joint_move(servo_id, pulse_us, duration_ms, profile):
    """Encode one documented ten-byte LSC move; no timing or transport."""
    profile = validate_profile(profile)
    servo_id = _integer(servo_id, 1, 6, "servo_id")
    pulse_us = _integer(pulse_us, *profile["joint_bounds_us"][servo_id - 1], "pulse_us")
    duration_ms = _integer(duration_ms, 100, 10_000, "duration_ms")
    return (bytes([0x55, 0x55, 0x08, 0x03, 1]) + duration_ms.to_bytes(2, "little")
            + bytes([servo_id]) + pulse_us.to_bytes(2, "little"))


def replay_preview(recording, repeats=1):
    checked = validate_recording(recording)
    repeats = _integer(repeats, 1, MAX_REPEATS, "repeats")
    if not checked["waypoints"]:
        raise ValueError("Record at least one commanded waypoint before previewing playback")
    total = sum(row["duration_ms"] for row in checked["waypoints"]) * repeats
    if total > MAX_REPLAY_MS:
        raise ValueError("Repeated playback may contain at most 120 seconds of commanded movement")
    events, elapsed = [], 0
    for repeat in range(repeats):
        for index, pose in enumerate(checked["waypoints"]):
            events.append({"repeat": repeat + 1, "waypoint_index": index,
                           "starts_at_ms": elapsed, **deepcopy(pose),
                           "frame_hex": encode_servo_move(**pose, profile=checked["profile"]).hex(" ")})
            elapsed += pose["duration_ms"]
    digest = hashlib.sha256(json.dumps(checked, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"mode": "dry_run", "recording_id": checked["recording_id"], "recording_sha256": digest,
            "recording_kind": "commanded_waypoints", "physical_positions_measured": False,
            "repeats": repeats, "total_duration_ms": total, "events": events,
            "simulated": True, "actuation_enabled": False, "commands_dispatched": 0,
            "physical_result": None, "api_cloud_cost_usd": 0,
            "note": "User-supplied bounds and command targets; no hardware movement or feedback verified."}


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields are not allowed")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON value")


def load_json(path):
    with Path(path).open("rb") as handle:
        contents = handle.read(MAX_JSON_BYTES + 1)
    if len(contents) > MAX_JSON_BYTES:
        raise ValueError("Motion JSON exceeds the 64 KiB limit")
    return json.loads(contents, object_pairs_hook=_unique_fields, parse_constant=_reject_constant)


def save_recording(path, recording, *, replace=False):
    """Validate before writing; creation never overwrites an existing record."""
    checked = validate_recording(recording)
    encoded = json.dumps(checked, indent=2, allow_nan=False) + "\n"
    path = Path(path)
    if not replace:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
        return
    # Replacements are explicit CLI edits. A failed write preserves the old file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".motion-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create an empty command recording with explicit bounds")
    create.add_argument("--profile", type=Path, required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--recording", type=Path, required=True)
    for command in ("add", "edit"):
        sub = commands.add_parser(command, help="Save six commanded pulses without moving any servo")
        sub.add_argument("--recording", type=Path, required=True)
        sub.add_argument("--pulses", type=int, nargs=6, required=True, metavar="US")
        sub.add_argument("--duration-ms", type=int, required=True)
        if command == "edit":
            sub.add_argument("--index", type=int, required=True)
    preview = commands.add_parser("preview", help="Generate a finite offline replay trace")
    preview.add_argument("--recording", type=Path, required=True)
    preview.add_argument("--repeats", type=int, default=1)
    group = commands.add_parser("group-preview", help="Encode a taught group without dispatching it")
    group.add_argument("--group-id", type=int, required=True)
    group.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = new_recording(args.name, load_json(args.profile))
            save_recording(args.recording, result)
        elif args.command in {"add", "edit"}:
            recording = load_json(args.recording)
            result = (append_pose(recording, args.pulses, args.duration_ms) if args.command == "add"
                      else replace_pose(recording, args.index, args.pulses, args.duration_ms))
            save_recording(args.recording, result, replace=True)
        elif args.command == "preview":
            result = replay_preview(load_json(args.recording), args.repeats)
        else:
            result = {"mode": "dry_run", "frame_hex": encode_action_group(args.group_id, args.repeats).hex(" "),
                      "group_id": args.group_id, "repeats": args.repeats,
                      "group_contents_verified": False, "duration_ms": None,
                      "actuation_enabled": False, "commands_dispatched": 0, "physical_result": None}
    except (ValueError, OSError, TypeError, UnicodeError) as error:
        parser.exit(2, f"Motion preview rejected: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
