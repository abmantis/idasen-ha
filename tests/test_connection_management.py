"""Tests for idasen_ha."""

import asyncio
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, Mock

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
    mock_idasen_desk._client.connect.assert_awaited()
    mock_idasen_desk.pair.assert_called()
    mock_idasen_desk.wakeup.assert_awaited_once()
    assert update_callback.call_count == 1

    await desk.disconnect()
    await desk.disconnect()  # double disconnect should be a no-op
    assert not desk.is_connected
    mock_idasen_desk.disconnect.assert_called()
    assert update_callback.call_count == 2


async def test_connect_skipped_when_already_connected(mock_idasen_desk: MagicMock):
    """Test that connect is skipped when the desk is already connected."""
    update_callback = Mock()
    desk = Desk(update_callback, False)

    mock_idasen_desk.is_connected = True

    await desk.connect(FAKE_BLE_DEVICE)
    mock_idasen_desk._client.connect.assert_not_awaited()
    mock_idasen_desk.pair.assert_not_called()
    mock_idasen_desk.wakeup.assert_not_called()
    assert update_callback.call_count == 0


async def test_double_connect_call_with_same_bledevice(mock_idasen_desk: MagicMock):
    """Test connect being called again with the same BLEDevice, while still connecting."""
    update_callback = Mock()
    desk = Desk(update_callback, False)

    default_connect_side_effect = mock_idasen_desk._client.connect.side_effect

    async def connect_side_effect():
        # call the seccond `connect` while the first is ongoing
        await desk.connect(FAKE_BLE_DEVICE)
        await default_connect_side_effect()

    mock_idasen_desk._client.connect.side_effect = connect_side_effect

    await desk.connect(FAKE_BLE_DEVICE)
    assert desk.is_connected
    mock_idasen_desk._client.connect.assert_awaited()
    mock_idasen_desk.pair.assert_called()
    mock_idasen_desk.wakeup.assert_awaited_once()
    assert update_callback.call_count == 1


async def test_double_connect_call_with_different_bledevice():
    """Test connect being called again with a new BLEDevice, while still connecting."""

    with mock.patch(
        "idasen_ha.connection_manager.IdasenDesk", autospec=True
    ) as patched_idasen_desk:
        mock_idasen_desk = patched_idasen_desk.return_value

        async def connect_side_effect():
            # call the seccond `connect` while the first is ongoing
            mock_idasen_desk._client.connect.side_effect = MagicMock()
            new_ble_device = BLEDevice("AA:BB:CC:DD:EE:AA", None, None)
            await desk.connect(new_ble_device)

        mock_idasen_desk.is_connected = False
        mock_idasen_desk._client = AsyncMock()
        mock_idasen_desk._client.connect.side_effect = connect_side_effect
        mock_idasen_desk.wakeup = AsyncMock()

        update_callback = Mock()
        desk = Desk(update_callback, False)
        await desk.connect(FAKE_BLE_DEVICE)

        mock_idasen_desk._client.connect.assert_awaited()
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

    default_connect_side_effect = mock_idasen_desk._client.connect.side_effect

    async def sleep_side_effect(delay):
        mock_idasen_desk._client.connect.side_effect = default_connect_side_effect
        await desk.connect(FAKE_BLE_DEVICE)
        retry_maxed_future.set_result(None)

    sleep_mock.side_effect = sleep_side_effect

    mock_idasen_desk._client.connect.side_effect = TimeoutError()
    await desk.connect(FAKE_BLE_DEVICE)
    assert not desk.is_connected

    await retry_maxed_future
    assert desk.is_connected
    assert mock_idasen_desk._client.connect.call_count == 2
    assert update_callback.call_count == 1


async def test_connect_raises_without_auto_reconnect(mock_idasen_desk: MagicMock):
    """Test that connect raises if auto_reconnect is False."""
    desk = Desk(Mock(), False)

    mock_idasen_desk._client.connect.side_effect = TimeoutError()
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
    mock_idasen_desk.wakeup.assert_not_called()
    assert update_callback.call_count == 0


async def test_wakeup_happens_after_pair(mock_idasen_desk: MagicMock):
    """Test that wakeup is awaited after pairing succeeds."""
    update_callback = Mock()
    desk = Desk(update_callback, False)
    steps: list[str] = []

    async def pair_side_effect():
        steps.append("pair")

    async def wakeup_side_effect():
        steps.append("wakeup")

    mock_idasen_desk.pair.side_effect = pair_side_effect
    mock_idasen_desk.wakeup.side_effect = wakeup_side_effect

    await desk.connect(FAKE_BLE_DEVICE)

    assert steps == ["pair", "wakeup"]


async def test_disconnect_on_wakeup_failure(mock_idasen_desk: MagicMock):
    """Test that disconnect is called if wakeup fails."""
    update_callback = Mock()
    desk = Desk(update_callback, False)

    mock_idasen_desk.wakeup.side_effect = BleakError()

    with pytest.raises(BleakError):
        await desk.connect(FAKE_BLE_DEVICE, retry=False)

    mock_idasen_desk.pair.assert_called_once()
    mock_idasen_desk.disconnect.assert_called()
    assert update_callback.call_count == 0


async def test_pair_failure_non_auth_dbus_error(mock_idasen_desk: MagicMock):
    """Test that a non-auth BleakDBusError from pair is re-raised."""
    desk = Desk(Mock(), False)

    mock_idasen_desk.pair.side_effect = BleakDBusError("org.bluez.Error.Failed", "")
    with pytest.raises(BleakDBusError):
        await desk.connect(FAKE_BLE_DEVICE, retry=False)

    mock_idasen_desk.disconnect.assert_called()


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
async def test_wakeup_failure_with_retry(
    sleep_mock,
    mock_idasen_desk: MagicMock,
) -> None:
    """Test that wakeup failure triggers retry when retry=True."""
    retry_future = asyncio.Future()

    async def sleep_handler(delay):
        mock_idasen_desk.wakeup.side_effect = None
        retry_future.set_result(None)

    sleep_mock.side_effect = sleep_handler

    desk = Desk(Mock(), False)
    mock_idasen_desk.wakeup.side_effect = BleakError()
    await desk.connect(FAKE_BLE_DEVICE)

    await retry_future
    assert desk.is_connected


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
async def test_schedule_reconnect_skipped_when_already_pending(
    sleep_mock,
    mock_idasen_desk: MagicMock,
) -> None:
    """Test that a second reconnect is not scheduled when one is already pending."""
    call_count = 0
    retry_future = asyncio.Future()

    default_connect_side_effect = mock_idasen_desk._client.connect.side_effect

    async def sleep_handler(delay):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            mock_idasen_desk._client.connect.side_effect = default_connect_side_effect
            retry_future.set_result(None)

    sleep_mock.side_effect = sleep_handler

    desk = Desk(Mock(), False)
    mock_idasen_desk._client.connect.side_effect = TimeoutError()

    await desk.connect(FAKE_BLE_DEVICE)
    await desk.connect(FAKE_BLE_DEVICE)

    await retry_future
    assert sleep_mock.call_count == 2


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
async def test_reconnect_aborted_when_not_keep_connected(
    sleep_mock,
    mock_idasen_desk: MagicMock,
) -> None:
    """Test that a pending reconnect is aborted when keep_connected is False."""
    retry_future = asyncio.Future()

    async def sleep_handler(delay):
        await desk.disconnect()
        retry_future.set_result(None)

    sleep_mock.side_effect = sleep_handler

    desk = Desk(Mock(), False)
    mock_idasen_desk._client.connect.side_effect = TimeoutError()
    await desk.connect(FAKE_BLE_DEVICE)

    await retry_future
    assert not desk.is_connected
    assert mock_idasen_desk._client.connect.call_count == 1


@mock.patch("idasen_ha.connection_manager.asyncio.sleep")
@pytest.mark.parametrize("exception", [TimeoutError(), BleakError()])
@pytest.mark.parametrize("fail_call_name", ["_client.connect", "pair"])
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

    fail_target = mock_idasen_desk
    for attr in fail_call_name.split("."):
        fail_target = getattr(fail_target, attr)
    fail_target.side_effect = exception
    await desk.connect(FAKE_BLE_DEVICE)

    await retry_maxed_future
    assert mock_idasen_desk._client.connect.call_count == TEST_RETRIES_MAX + 1


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
@pytest.mark.parametrize("fail_call_name", ["_client.connect", "pair"])
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

    fail_target = mock_idasen_desk
    for attr in fail_call_name.split("."):
        fail_target = getattr(fail_target, attr)
    default_fail_call_side_effect = fail_target.side_effect

    async def sleep_handler(delay):
        nonlocal retry_count
        if retry_count == TEST_RETRIES_MAX:
            fail_target.side_effect = default_fail_call_side_effect
            retry_maxed_future.set_result(None)
        retry_count = retry_count + 1

    sleep_mock.side_effect = sleep_handler

    desk = Desk(Mock(), False)
    fail_target.side_effect = exception
    await desk.connect(FAKE_BLE_DEVICE)

    await retry_maxed_future
    assert mock_idasen_desk._client.connect.call_count == TEST_RETRIES_MAX + 2


async def test_reconnect_on_connection_drop(mock_idasen_desk: MagicMock):
    """Test reconnection when the connection drops."""
    update_callback = Mock()
    desk = Desk(update_callback, True)

    await desk.connect(FAKE_BLE_DEVICE)
    assert desk.is_connected
    assert update_callback.call_count == 1

    mock_idasen_desk.reset_mock()
    mock_idasen_desk._client.connect.reset_mock()
    await mock_idasen_desk.disconnect()
    assert not desk.is_connected
    assert update_callback.call_count == 2

    await asyncio.sleep(0)
    assert desk.is_connected
    mock_idasen_desk._client.connect.assert_awaited()
    mock_idasen_desk.pair.assert_called()
    assert update_callback.call_count == 3
