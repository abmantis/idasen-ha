"""Tests for idasen_ha."""

import asyncio
from unittest import mock
from unittest.mock import MagicMock, Mock

from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError, BleakError
import pytest

from idasen_ha import Desk
from idasen_ha.connection_manager import AuthFailedError

from . import FAKE_BLE_DEVICE


async def test_connect_disconnect(mock_idasen_desk: MagicMock):
    """Test connect and disconnect."""
    update_callback = Mock()
    desk = Desk(update_callback, False)

    await desk.connect(FAKE_BLE_DEVICE)
    assert desk.is_connected
    mock_idasen_desk.connect.assert_awaited()
    mock_idasen_desk.pair.assert_called()
    assert update_callback.call_count == 1

    await desk.disconnect()
    await desk.disconnect()  # double disconnect should be a no-op
    assert not desk.is_connected
    mock_idasen_desk.disconnect.assert_called()
    assert update_callback.call_count == 2


async def test_double_connect_call_with_same_bledevice(mock_idasen_desk: MagicMock):
    """Test connect being called again with the same BLEDevice, while still connecting."""
    update_callback = Mock()
    desk = Desk(update_callback, False)

    default_connect_side_effect = mock_idasen_desk.connect.side_effect

    async def connect_side_effect():
        # call the seccond `connect` while the first is ongoing
        await desk.connect(FAKE_BLE_DEVICE)
        await default_connect_side_effect()

    mock_idasen_desk.connect.side_effect = connect_side_effect

    await desk.connect(FAKE_BLE_DEVICE)
    assert desk.is_connected
    mock_idasen_desk.connect.assert_awaited()
    mock_idasen_desk.pair.assert_called()
    assert update_callback.call_count == 1


async def test_double_connect_call_with_different_bledevice():
    """Test connect being called again with a new BLEDevice, while still connecting."""

    with mock.patch(
        "idasen_ha.connection_manager.IdasenDesk", autospec=True
    ) as patched_idasen_desk:
        mock_idasen_desk = patched_idasen_desk.return_value

        async def connect_side_effect():
            # call the seccond `connect` while the first is ongoing
            mock_idasen_desk.connect.side_effect = MagicMock()
            new_ble_device = BLEDevice("AA:BB:CC:DD:EE:AA", None, None, 0)
            await desk.connect(new_ble_device)

        mock_idasen_desk.is_connected = False
        mock_idasen_desk.connect.side_effect = connect_side_effect

        update_callback = Mock()
        desk = Desk(update_callback, False)
        await desk.connect(FAKE_BLE_DEVICE)

        mock_idasen_desk.connect.assert_awaited()
        mock_idasen_desk.pair.assert_called()
        assert update_callback.call_count == 2
        assert patched_idasen_desk.call_count == 2


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
async def test_connect_called_while_retry_pending(
    sleep_mock,
    mock_idasen_desk: MagicMock,
) -> None:
    """Test connect being called while a retry is pending."""
    retry_maxed_future = asyncio.Future()
    update_callback = Mock()
    desk = Desk(update_callback, False)

    default_connect_side_effect = mock_idasen_desk.connect.side_effect

    async def sleep_side_effect(delay):
        mock_idasen_desk.connect.side_effect = default_connect_side_effect
        await desk.connect(FAKE_BLE_DEVICE)
        retry_maxed_future.set_result(None)

    sleep_mock.side_effect = sleep_side_effect

    mock_idasen_desk.connect.side_effect = TimeoutError()
    await desk.connect(FAKE_BLE_DEVICE)
    assert not desk.is_connected

    await retry_maxed_future
    assert desk.is_connected
    assert mock_idasen_desk.connect.call_count == 2
    assert update_callback.call_count == 1


async def test_connect_raises_without_auto_reconnect(mock_idasen_desk: MagicMock):
    """Test that connect raises if auto_reconnect is False."""
    desk = Desk(Mock(), False)

    mock_idasen_desk.connect.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await desk.connect(FAKE_BLE_DEVICE, retry=False)
    assert not desk.is_connected


@pytest.mark.parametrize(
    ("pair_exception", "raised_exception"),
    [
        (Exception(), Exception),
        (BleakDBusError("org.bluez.Error.AuthenticationFailed", ""), AuthFailedError),
    ],
)
async def test_disconnect_on_pair_failure(
    mock_idasen_desk: MagicMock, pair_exception, raised_exception
):
    """Test that disconnect is called if pair fails."""
    update_callback = Mock()
    desk = Desk(update_callback, False)

    mock_idasen_desk.pair.side_effect = pair_exception
    with pytest.raises(raised_exception):
        await desk.connect(FAKE_BLE_DEVICE, retry=False)
    assert not desk.is_connected
    mock_idasen_desk.disconnect.assert_called()
    assert update_callback.call_count == 0


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
@pytest.mark.parametrize("exception", [TimeoutError(), BleakError()])
@pytest.mark.parametrize("fail_call_name", ["connect", "pair"])
async def test_connect_exception_retry_with_disconnect(
    sleep_mock,
    mock_idasen_desk: MagicMock,
    exception: Exception,
    fail_call_name: str,
) -> None:
    """Test connect retries on connection exception."""
    TEST_RETRIES_MAX = 3
    retry_count = 0
    retry_maxed_future = asyncio.Future()

    async def sleep_handler(delay):
        nonlocal retry_count
        retry_count = retry_count + 1
        if retry_count == TEST_RETRIES_MAX:
            asyncio.get_event_loop().create_task(desk.disconnect())
            retry_maxed_future.set_result(None)

    sleep_mock.side_effect = sleep_handler

    desk = Desk(Mock(), False)

    getattr(mock_idasen_desk, fail_call_name).side_effect = exception
    await desk.connect(FAKE_BLE_DEVICE)

    await retry_maxed_future
    assert mock_idasen_desk.connect.call_count == TEST_RETRIES_MAX + 1


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
@pytest.mark.parametrize(
    "exception",
    [
        TimeoutError(),
        BleakError(),
        BleakDBusError("", []),
        BleakDBusError("org.bluez.Error.AuthenticationFailed", []),
    ],
)
@pytest.mark.parametrize("fail_call_name", ["connect", "pair"])
async def test_connect_exception_retry_success(
    sleep_mock,
    mock_idasen_desk: MagicMock,
    exception: Exception,
    fail_call_name: str,
) -> None:
    """Test connect retries on connection exception."""
    TEST_RETRIES_MAX = 3
    retry_count = 0
    retry_maxed_future = asyncio.Future()

    fail_call = getattr(mock_idasen_desk, fail_call_name)
    default_fail_call_side_effect = fail_call.side_effect

    async def sleep_handler(delay):
        nonlocal retry_count
        if retry_count == TEST_RETRIES_MAX:
            fail_call.side_effect = default_fail_call_side_effect
            retry_maxed_future.set_result(None)
        retry_count = retry_count + 1

    sleep_mock.side_effect = sleep_handler

    desk = Desk(Mock(), False)
    fail_call.side_effect = exception
    await desk.connect(FAKE_BLE_DEVICE)

    await retry_maxed_future
    assert mock_idasen_desk.connect.call_count == TEST_RETRIES_MAX + 2


async def test_reconnect_on_connection_drop(mock_idasen_desk: MagicMock):
    """Test reconnection when the connection drops."""
    update_callback = Mock()
    desk = Desk(update_callback, True)

    await desk.connect(FAKE_BLE_DEVICE)
    assert desk.is_connected
    assert update_callback.call_count == 1

    mock_idasen_desk.reset_mock()
    await mock_idasen_desk.disconnect()
    assert not desk.is_connected
    assert update_callback.call_count == 2

    await asyncio.sleep(0)
    assert desk.is_connected
    mock_idasen_desk.connect.assert_awaited()
    mock_idasen_desk.pair.assert_called()
    assert update_callback.call_count == 3
