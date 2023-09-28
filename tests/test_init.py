"""Tests for idasen_ha."""

from unittest import mock
from unittest.mock import MagicMock, Mock

from bleak.backends.device import BLEDevice
from idasen import IdasenDesk
import pytest

from idasen_ha import Desk

FAKE_BLE_DEVICE = BLEDevice("AA:BB:CC:DD:EE:FF", None, None, 0)


def height_percent_to_meters(percent: float):
    """Convert height from percentage to meters."""
    return IdasenDesk.MIN_HEIGHT + (IdasenDesk.MAX_HEIGHT - IdasenDesk.MIN_HEIGHT) * (
        percent / 100
    )


async def test_connect_disconnect(mock_idasen_desk: MagicMock):
    """Test connect and disconnect."""
    update_callback = Mock()
    desk = Desk(update_callback)

    await desk.connect(FAKE_BLE_DEVICE, False)
    assert desk.is_connected
    mock_idasen_desk.connect.assert_awaited()
    mock_idasen_desk.pair.assert_called()
    assert update_callback.call_count == 1

    await desk.disconnect()
    assert not desk.is_connected
    mock_idasen_desk.disconnect.assert_called()
    assert update_callback.call_count == 2


async def test_disconnect_on_pair_failure(mock_idasen_desk: MagicMock):
    """Test that disconnect is called if pair fails."""
    update_callback = Mock()
    desk = Desk(update_callback)

    mock_idasen_desk.pair.side_effect = Exception()
    with pytest.raises(Exception):
        await desk.connect(FAKE_BLE_DEVICE, False)
    assert not desk.is_connected
    mock_idasen_desk.disconnect.assert_called()
    assert update_callback.call_count == 1


async def test_monitor_height(mock_idasen_desk: MagicMock):
    """Test height monitoring."""
    update_callback = Mock()
    desk = Desk(update_callback)

    HEIGHT_1 = 50
    mock_idasen_desk.get_height.return_value = height_percent_to_meters(HEIGHT_1)

    await desk.connect(FAKE_BLE_DEVICE, True)
    mock_idasen_desk.connect.assert_called()
    mock_idasen_desk.pair.assert_called()
    mock_idasen_desk.get_height.assert_called()
    update_callback.assert_called_with(HEIGHT_1)
    assert desk.height_percent == HEIGHT_1

    HEIGHT_2 = 80
    await mock_idasen_desk.trigger_monitor_callback(height_percent_to_meters(HEIGHT_2))
    update_callback.assert_called_with(HEIGHT_2)
    assert desk.height_percent == HEIGHT_2


async def test_moves(mock_idasen_desk: MagicMock):
    """Test movement calls."""
    desk = Desk(None)
    await desk.connect(FAKE_BLE_DEVICE, True)

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
    desk = Desk(None)
    await desk.connect(FAKE_BLE_DEVICE, True)

    mock_idasen_desk.is_moving = True

    HEIGHT_1 = 50
    await desk.move_to(HEIGHT_1)
    # ensure stop() is called before move_to_target()
    mock_idasen_desk.assert_has_calls(
        [mock.call.stop(), mock.call.move_to_target(height_percent_to_meters(HEIGHT_1))]
    )


async def test_stop(mock_idasen_desk: MagicMock):
    """Test stop call."""
    desk = Desk(None)
    await desk.connect(FAKE_BLE_DEVICE, False)

    await desk.stop()
    mock_idasen_desk.stop.assert_called()


@pytest.mark.parametrize("connect_first", [True, False])
async def test_no_ops_if_not_connected(
    mock_idasen_desk: MagicMock, connect_first: bool
):
    """Test that disconnect is called if pair fails."""
    desk = Desk(Mock())

    if connect_first:
        await desk.connect(FAKE_BLE_DEVICE, True)
        mock_idasen_desk.is_connected = False

    assert not desk.is_connected
    await desk.move_to(100)
    await desk.stop()
    await desk.disconnect()

    mock_idasen_desk.move_to_target.assert_not_called()
    mock_idasen_desk.stop.assert_not_called()
    mock_idasen_desk.disconnect.assert_not_called()
