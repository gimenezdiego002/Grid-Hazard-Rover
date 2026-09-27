import asyncio
import builtins
import sys
from types import SimpleNamespace

import pytest

from robotcode.arm.ble_group import (
    BATTERY_QUERY, CHARACTERISTIC_UUID, GROUP_STOP, SERVICE_UUID, _Frames,
    _execute_group, preview_group, run_group,
)


class FakeClient:
    def __init__(self, mode="complete", service=SERVICE_UUID):
        self.mode, self.writes, self.callback = mode, [], None
        self.characteristic = SimpleNamespace(handle=24, service_uuid=service,
                                              uuid=CHARACTERISTIC_UUID,
                                              properties=["notify", "write"])
        self.services = SimpleNamespace(get_characteristic=lambda _: self.characteristic)
        self.unsubscribed = False

    async def start_notify(self, characteristic, callback):
        self.callback = callback

    async def stop_notify(self, characteristic):
        self.unsubscribed = True

    async def write_gatt_char(self, characteristic, data, response):
        assert characteristic is self.characteristic and response is True
        self.writes.append(data)
        if data == BATTERY_QUERY:
            if self.mode == "preflight_failure":
                raise OSError("fixture error")
            self.callback(characteristic, bytes.fromhex("55 55 04"))
            self.callback(characteristic, bytes.fromhex("0f c9 1e"))
        elif data == GROUP_STOP:
            if self.mode == "stop_failure":
                raise OSError("fixture stop error")
        elif self.mode == "complete":
            self.callback(characteristic, bytes.fromhex("55 55 05 08 08 01 00"))
        elif self.mode == "wrong_completion":
            self.callback(characteristic, bytes.fromhex("55 55 05 08 09 01 00"))
        elif self.mode == "cancel":
            raise asyncio.CancelledError
        elif self.mode == "send_failure":
            raise OSError("ambiguous write fixture")


def test_frame_decoder_handles_noise_splits_and_combined_frames():
    decoder = _Frames()
    assert decoder.feed(b"noise\x55") == []
    assert decoder.feed(bytes.fromhex("55 04 0f c9")) == []
    assert decoder.feed(bytes.fromhex("1e 55 55 05 08 08 01 00")) == [
        bytes.fromhex("55 55 04 0f c9 1e"), bytes.fromhex("55 55 05 08 08 01 00")]
    assert decoder.feed(bytes.fromhex("55 55 ff 55 55 02 07")) == [GROUP_STOP]


def test_default_run_never_imports_bluetooth(monkeypatch):
    original = builtins.__import__
    def blocked(name, *args, **kwargs):
        assert name != "bleak", "Offline preview attempted to import Bluetooth"
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", blocked)
    result = asyncio.run(run_group(group_id=8))
    assert result["mode"] == "dry_run" and not result["group_write_attempted"]


def test_live_validation_requires_presence_address_and_explicit_handle():
    for changes in ({}, {"operator_present": True},
                    {"operator_present": True, "group_contents_verified": True, "address": "test"},
                    {"operator_present": True, "group_contents_verified": True, "address": "test", "handle": True}):
        with pytest.raises(ValueError):
            asyncio.run(run_group(group_id=8, live=True, **changes))


def test_disconnect_hang_is_bounded_and_does_not_retry(monkeypatch):
    import robotcode.arm.ble_group as module
    client = FakeClient()
    async def connect():
        pass
    async def disconnect():
        await asyncio.Future()
    async def discover(*args, **kwargs):
        return object()
    client.connect, client.disconnect = connect, disconnect
    monkeypatch.setattr(module, "DISCONNECT_TIMEOUT", 0.001)
    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(
        BleakClient=lambda *a, **k: client,
        BleakScanner=SimpleNamespace(find_device_by_address=discover)))
    result = asyncio.run(run_group(group_id=8, live=True, operator_present=True,
                                  group_contents_verified=True, address="fixture", handle=24))
    assert result["outcome"] == "unknown" and result["completion_reported"]
    assert result["reason"] == "disconnect_failed" and len(client.writes) == 2


def test_preflight_and_completion_report_controller_state_only():
    client = FakeClient()
    result = asyncio.run(_execute_group(client, 24, 8, 1, 1))
    assert client.writes == [BATTERY_QUERY, bytes.fromhex("55 55 05 06 08 01 00")]
    assert result["voltage_mv"] == 7881 and result["completion_reported"]
    assert result["outcome"] == "controller_reported_completion"
    assert result["physical_result"] is None and not result["stop_write_attempted"]
    assert client.unsubscribed


def test_duplicate_characteristic_uuid_under_wrong_service_never_writes():
    client = FakeClient(service="0000ffe0-0000-1000-8000-00805f9b34fb")
    with pytest.raises(ValueError):
        asyncio.run(_execute_group(client, 24, 8, 1, 1))
    assert client.writes == []


def test_preflight_failure_sends_no_group_or_stop():
    client = FakeClient("preflight_failure")
    result = asyncio.run(_execute_group(client, 24, 8, 1, 1))
    assert result["outcome"] == "not_sent"
    assert client.writes == [BATTERY_QUERY]
    assert not result["group_write_attempted"] and not result["stop_write_attempted"]


@pytest.mark.parametrize("mode", ["wrong_completion", "send_failure", "cancel", "stop_failure"])
def test_timeout_failure_and_cancellation_attempt_one_stop_without_retry(mode):
    client = FakeClient(mode)
    result = asyncio.run(_execute_group(client, 24, 8, 1, 1))
    assert result["outcome"] == "unknown" and result["physical_result"] is None
    assert result["group_write_attempted"] and result["stop_write_attempted"]
    assert result["stop_write_completed"] is (mode != "stop_failure")
    assert client.writes == [BATTERY_QUERY, bytes.fromhex("55 55 05 06 08 01 00"), GROUP_STOP]
    assert not result["automatic_retry"] and client.unsubscribed


@pytest.mark.parametrize("repeats,timeout", [(0, 30), (6, 30), (1, 0), (1, 121), (1, True)])
def test_preview_rejects_infinite_or_unbounded_execution(repeats, timeout):
    with pytest.raises(ValueError):
        preview_group(8, repeats, timeout)
