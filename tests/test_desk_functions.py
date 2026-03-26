"""Tests for idasen_ha."""

from unittest import mock
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from bleak.exc import BleakError

from idasen_ha import Desk

from . import FAKE_BLE_DEVICE, height_percent_to_meters


async def test_monitor_height(mock_idasen_desk: MagicMock):
    """Test height monitoring."""
    update_callback = Mock()
    desk = Desk(update_callback, True)

    HEIGHT_PCT_1 = 50
    HEIGHT_MTS_1 = height_percent_to_meters(HEIGHT_PCT_1)
    mock_idasen_desk.get_height.return_value = HEIGHT_MTS_1

    await desk.connect(FAKE_BLE_DEVICE)
    mock_idasen_desk.establish_connection.assert_called()
    mock_idasen_desk.pair.assert_called()
    mock_idasen_desk.get_height.assert_called()
    update_callback.assert_called_with(HEIGHT_PCT_1)
    assert desk.height == HEIGHT_MTS_1
    assert desk.height_percent == HEIGHT_PCT_1

    HEIGHT_PCT_2 = 80
    HEIGHT_MTS_2 = height_percent_to_meters(HEIGHT_PCT_2)
    await mock_idasen_desk.trigger_monitor_callback(HEIGHT_MTS_2)
    update_callback.assert_called_with(HEIGHT_PCT_2)
    assert desk.height == HEIGHT_MTS_2
    assert desk.height_percent == HEIGHT_PCT_2


async def test_moves(mock_idasen_desk: MagicMock):
    """Test movement calls."""
    desk = Desk(None, True)
    await desk.connect(FAKE_BLE_DEVICE)

    mock_idasen_desk.is_moving = False

    HEIGHT_1 = 50
    await desk.move_to(HEIGHT_1)
    mock_idasen_desk.move_to_target.assert_called_with(
        height_percent_to_meters(HEIGHT_1)
    )

    HEIGHT_MAX = 100
    await desk.move_up()
    mock_idasen_desk.move_to_target.assert_called_with(
        height_percent_to_meters(HEIGHT_MAX)
    )

    HEIGHT_MIN = 0
    await desk.move_down()
    mock_idasen_desk.move_to_target.assert_called_with(
        height_percent_to_meters(HEIGHT_MIN)
    )


async def test_stop_before_move(mock_idasen_desk: MagicMock):
    """Test that movement is stoped before new movement starts."""
    desk = Desk(None, True)
    await desk.connect(FAKE_BLE_DEVICE)

    mock_idasen_desk.is_moving = True

    HEIGHT_1 = 50
    await desk.move_to(HEIGHT_1)
    # ensure stop() is called, then wakeup(), then move_to_target()
    mock_idasen_desk.assert_has_calls(
        [
            mock.call.stop(),
            mock.call.wakeup(),
            mock.call.move_to_target(height_percent_to_meters(HEIGHT_1)),
        ]
    )


async def test_stop_failure_before_move(mock_idasen_desk: MagicMock):
    """Test that move_to returns early when stop raises before moving."""
    desk = Desk(None, False)
    await desk.connect(FAKE_BLE_DEVICE)

    mock_idasen_desk.is_moving = True
    mock_idasen_desk.stop = AsyncMock(side_effect=BleakError())

    await desk.move_to(50)
    mock_idasen_desk.move_to_target.assert_not_called()


async def test_move_to_failure(mock_idasen_desk: MagicMock):
    """Test that move_to swallows BleakError from move_to_target."""
    desk = Desk(None, False)
    await desk.connect(FAKE_BLE_DEVICE)

    mock_idasen_desk.is_moving = False
    mock_idasen_desk.move_to_target = AsyncMock(side_effect=BleakError())

    await desk.move_to(50)  # should not raise


async def test_monitoring_skipped_if_disconnected_during_get_height(
    mock_idasen_desk: MagicMock,
):
    """Test that monitoring is skipped if the desk disconnects during get_height."""

    async def get_height_and_disconnect():
        # Simulate a BLE disconnect occurring while get_height is in progress
        mock_idasen_desk.is_connected = False
        return height_percent_to_meters(50)

    mock_idasen_desk.get_height.side_effect = get_height_and_disconnect

    desk = Desk(Mock(), True)
    await desk.connect(FAKE_BLE_DEVICE)

    mock_idasen_desk.monitor.assert_not_called()


async def test_stop(mock_idasen_desk: MagicMock):
    """Test stop call."""
    desk = Desk(None, False)
    await desk.connect(FAKE_BLE_DEVICE)

    await desk.stop()
    mock_idasen_desk.stop.assert_called()


@pytest.mark.parametrize("connect_first", [True, False])
async def test_no_ops_if_not_connected(
    mock_idasen_desk: MagicMock, connect_first: bool
):
    """Test that disconnect is called if pair fails."""
    desk = Desk(Mock(), False)

    if connect_first:
        await desk.connect(FAKE_BLE_DEVICE)
        mock_idasen_desk.is_connected = False

    assert not desk.is_connected
    await desk.move_to(100)
    await desk.stop()

    mock_idasen_desk.move_to_target.assert_not_called()
    mock_idasen_desk.stop.assert_not_called()
