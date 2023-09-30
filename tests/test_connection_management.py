"""Tests for idasen_ha."""

import asyncio
from unittest import mock
from unittest.mock import MagicMock, Mock

from bleak.exc import BleakError
import pytest

from idasen_ha import Desk

from . import FAKE_BLE_DEVICE


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


async def test_connect_raises_without_auto_reconnect(mock_idasen_desk: MagicMock):
    """Test that connect raises if auto_reconnect is False."""
    desk = Desk(Mock())

    mock_idasen_desk.connect.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await desk.connect(FAKE_BLE_DEVICE, False, auto_reconnect=False)
    assert not desk.is_connected


async def test_disconnect_on_pair_failure(mock_idasen_desk: MagicMock):
    """Test that disconnect is called if pair fails."""
    update_callback = Mock()
    desk = Desk(update_callback)

    mock_idasen_desk.pair.side_effect = Exception()
    with pytest.raises(Exception):
        await desk.connect(FAKE_BLE_DEVICE, False, auto_reconnect=False)
    assert not desk.is_connected
    mock_idasen_desk.disconnect.assert_called()
    assert update_callback.call_count == 1


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
@pytest.mark.parametrize("exception", [TimeoutError(), BleakError()])
@pytest.mark.parametrize("fail_call", ["connect", "pair"])
async def test_connect_exception_retry_with_disconnect(
    sleep_mock,
    mock_idasen_desk: MagicMock,
    exception: Exception,
    fail_call: str,
) -> None:
    """Test connect retries on connection exception."""
    TEST_RETRIES_MAX = 3
    retry_count = 0
    retry_maxed_future = asyncio.Future()

    async def sleep_handler(delay):
        nonlocal retry_count
        if retry_count == TEST_RETRIES_MAX:
            await desk.disconnect()
            retry_maxed_future.set_result(None)
        retry_count = retry_count + 1

    sleep_mock.side_effect = sleep_handler

    update_callback = Mock()
    desk = Desk(update_callback)

    getattr(mock_idasen_desk, fail_call).side_effect = exception
    await desk.connect(FAKE_BLE_DEVICE, False)

    await retry_maxed_future
    assert mock_idasen_desk.connect.call_count == TEST_RETRIES_MAX + 1


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
@pytest.mark.parametrize("exception", [TimeoutError(), BleakError()])
@pytest.mark.parametrize("fail_call", ["connect", "pair"])
async def test_connect_exception_retry_success(
    sleep_mock,
    mock_idasen_desk: MagicMock,
    exception: Exception,
    fail_call: str,
) -> None:
    """Test connect retries on connection exception."""
    TEST_RETRIES_MAX = 3
    retry_count = 0
    retry_maxed_future = asyncio.Future()

    async def sleep_handler(delay):
        nonlocal retry_count
        if retry_count == TEST_RETRIES_MAX:
            mock_idasen_desk.connect.side_effect = None
            mock_idasen_desk.is_connected = True
            retry_maxed_future.set_result(None)
        retry_count = retry_count + 1

    sleep_mock.side_effect = sleep_handler

    update_callback = Mock()
    desk = Desk(update_callback)

    getattr(mock_idasen_desk, fail_call).side_effect = exception
    await desk.connect(FAKE_BLE_DEVICE, False)

    await retry_maxed_future
    assert mock_idasen_desk.connect.call_count == TEST_RETRIES_MAX + 2
