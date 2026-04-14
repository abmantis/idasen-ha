"""Tests for ManagedIdasenDesk."""

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.backends.device import BLEDevice
from idasen import (
    _COMMAND_REFERENCE_INPUT_STOP,
    _COMMAND_STOP,
    _UUID_COMMAND,
    _UUID_REFERENCE_INPUT,
    IdasenDesk,
)
import pytest

from idasen_ha.desk import _HEIGHT_TOLERANCE, ManagedIdasenDesk


def _encode_height_speed(height_m: float, speed_m_s: float) -> bytearray:
    raw_height = int((height_m - IdasenDesk.MIN_HEIGHT) * 10000)
    raw_speed = int(speed_m_s * 10000)
    return bytearray(struct.pack("<Hh", raw_height, raw_speed))


def _make_desk_with_client() -> tuple[ManagedIdasenDesk, MagicMock]:
    desk = ManagedIdasenDesk("AA:BB:CC:DD:EE:FF")
    client = MagicMock()
    client.write_gatt_char = AsyncMock()
    client.read_gatt_char = AsyncMock()
    desk.set_client(client)
    return desk, client


def test_init_with_ble_device():
    """Test that __init__ does not create a BleakClient."""
    ble_device = BLEDevice("AA:BB:CC:DD:EE:FF", None, {"path": ""})
    desk = ManagedIdasenDesk(ble_device, exit_on_fail=False)

    assert desk.mac == "AA:BB:CC:DD:EE:FF"
    assert desk._client is None
    assert not desk._moving
    assert desk._move_task is None
    assert desk._notified_height is None


def test_init_with_mac_string():
    """Test init with a plain MAC address string."""
    desk = ManagedIdasenDesk("AA:BB:CC:DD:EE:FF", exit_on_fail=False)

    assert desk.mac == "AA:BB:CC:DD:EE:FF"
    assert desk._client is None


def test_set_client():
    """Test that set_client replaces the internal client."""
    desk = ManagedIdasenDesk("AA:BB:CC:DD:EE:FF")
    assert desk._client is None

    mock_client = MagicMock()
    desk.set_client(mock_client)
    assert desk._client is mock_client


def test_update_height():
    """Test that update_height stores the notified height."""
    desk = ManagedIdasenDesk("AA:BB:CC:DD:EE:FF")
    assert desk._notified_height is None

    desk.update_height(0.85)
    assert desk._notified_height == 0.85

    desk.update_height(1.00)
    assert desk._notified_height == 1.00


async def test_move_to_target_already_at_target():
    """Test that no movement occurs when already at target height."""
    desk, client = _make_desk_with_client()
    target = 0.80
    client.read_gatt_char.return_value = _encode_height_speed(target, 0.0)

    await desk.move_to_target(target)

    assert client.read_gatt_char.call_count == 1
    write_calls = [
        c
        for c in client.write_gatt_char.call_args_list
        if c.args[0] == _UUID_REFERENCE_INPUT
    ]
    assert len(write_calls) == 0
    assert not desk._moving


async def test_move_to_target_reaches_target():
    """Test normal movement that reaches target via notification."""
    desk, client = _make_desk_with_client()
    target = 1.00

    client.read_gatt_char.return_value = _encode_height_speed(0.80, 0.0)

    async def simulate_height_updates():
        await asyncio.sleep(0.05)
        desk.update_height(0.85)
        await asyncio.sleep(0.05)
        desk.update_height(0.92)
        await asyncio.sleep(0.05)
        desk.update_height(target)

    with patch("idasen_ha.desk._MOVE_WRITE_INTERVAL", 0.02):
        task = asyncio.create_task(simulate_height_updates())
        await desk.move_to_target(target)
        await task

    assert not desk._moving
    assert client.read_gatt_char.call_count == 1


async def test_move_to_target_sends_stop_after_reaching_target():
    """Test that stop commands are sent after the move loop exits."""
    desk, client = _make_desk_with_client()
    target = 1.00

    client.read_gatt_char.return_value = _encode_height_speed(0.80, 0.0)

    async def simulate_arrival():
        await asyncio.sleep(0.05)
        desk.update_height(target)

    with patch("idasen_ha.desk._MOVE_WRITE_INTERVAL", 0.02):
        task = asyncio.create_task(simulate_arrival())
        await desk.move_to_target(target)
        await task

    write_calls = client.write_gatt_char.call_args_list
    stop_calls = [c for c in write_calls if c.args == (_UUID_COMMAND, _COMMAND_STOP)]
    ref_stop_calls = [
        c
        for c in write_calls
        if c.args == (_UUID_REFERENCE_INPUT, _COMMAND_REFERENCE_INPUT_STOP)
    ]
    assert len(stop_calls) >= 2
    assert len(ref_stop_calls) >= 1


async def test_move_to_target_no_gatt_reads_during_loop():
    """Test that no GATT reads happen after the initial height check."""
    desk, client = _make_desk_with_client()
    target = 1.00

    client.read_gatt_char.return_value = _encode_height_speed(0.80, 0.0)

    async def simulate_arrival():
        await asyncio.sleep(0.08)
        desk.update_height(target)

    with patch("idasen_ha.desk._MOVE_WRITE_INTERVAL", 0.02):
        task = asyncio.create_task(simulate_arrival())
        await desk.move_to_target(target)
        await task

    assert client.read_gatt_char.call_count == 1


async def test_move_to_target_times_out():
    """Test that the move loop exits after the timeout."""
    desk, client = _make_desk_with_client()
    target = 1.00

    client.read_gatt_char.return_value = _encode_height_speed(0.80, 0.0)
    desk.update_height(0.80)

    with (
        patch("idasen_ha.desk._MOVE_WRITE_INTERVAL", 0.01),
        patch("idasen_ha.desk._MOVE_TIMEOUT", 0.1),
    ):
        await desk.move_to_target(target)

    assert not desk._moving


async def test_move_to_target_out_of_range():
    """Test that ValueError is raised for out-of-range targets."""
    desk, _ = _make_desk_with_client()

    with pytest.raises(ValueError, match="exceeds maximum"):
        await desk.move_to_target(IdasenDesk.MAX_HEIGHT + 0.01)

    with pytest.raises(ValueError, match="exceeds minimum"):
        await desk.move_to_target(IdasenDesk.MIN_HEIGHT - 0.01)


async def test_move_to_target_already_moving():
    """Test that a second move_to_target is rejected while already moving."""
    desk, client = _make_desk_with_client()
    desk._moving = True

    await desk.move_to_target(1.00)

    client.read_gatt_char.assert_not_called()


async def test_move_to_target_cancelled_resets_moving_flag():
    """Test that _moving is reset when the move task is cancelled."""
    desk, client = _make_desk_with_client()
    target = 1.00

    client.read_gatt_char.return_value = _encode_height_speed(0.80, 0.0)

    with patch("idasen_ha.desk._MOVE_WRITE_INTERVAL", 0.5):
        task = asyncio.create_task(desk.move_to_target(target))
        await asyncio.sleep(0.05)
        assert desk._moving

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert not desk._moving


async def test_move_to_target_within_tolerance():
    """Test that height within tolerance of target is accepted as arrived."""
    desk, client = _make_desk_with_client()
    target = 1.00

    client.read_gatt_char.return_value = _encode_height_speed(0.80, 0.0)

    async def simulate_near_arrival():
        await asyncio.sleep(0.05)
        desk.update_height(target - _HEIGHT_TOLERANCE / 2)

    with patch("idasen_ha.desk._MOVE_WRITE_INTERVAL", 0.02):
        task = asyncio.create_task(simulate_near_arrival())
        await desk.move_to_target(target)
        await task

    assert not desk._moving


async def test_move_to_target_none_client():
    """Test that move_to_target does nothing when client is None."""
    desk = ManagedIdasenDesk("AA:BB:CC:DD:EE:FF")

    await desk.move_to_target(1.00)

    assert not desk._moving
