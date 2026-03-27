"""Generic test fixtures."""

from collections.abc import Awaitable
from typing import Callable
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from idasen import IdasenDesk
import pytest


@pytest.fixture(autouse=False)
async def mock_idasen_desk():
    """Test height monitoring."""

    with (
        mock.patch(
            "idasen_ha.connection_manager.IdasenDesk", autospec=True
        ) as patched_idasen_desk,
        mock.patch(
            "idasen_ha.connection_manager.establish_connection"
        ) as mock_establish_connection,
    ):
        patched_idasen_desk.MIN_HEIGHT = IdasenDesk.MIN_HEIGHT
        patched_idasen_desk.MAX_HEIGHT = IdasenDesk.MAX_HEIGHT

        mock_desk = patched_idasen_desk.return_value

        def mock_init(mac_bledevice, exit_on_fail: bool = False):
            return mock_desk

        patched_idasen_desk.side_effect = mock_init

        async def mock_establish_conn(
            client_class, ble_device, address, disconnected_callback=None, **kwargs
        ):
            mock_desk.trigger_disconnected_callback = disconnected_callback
            mock_desk.is_connected = True
            return MagicMock()

        mock_establish_connection.side_effect = mock_establish_conn

        async def mock_disconnect():
            mock_desk.is_connected = False
            if mock_desk.trigger_disconnected_callback:
                mock_desk.trigger_disconnected_callback(None)

        async def mock_monitor(callback: Callable[[float], Awaitable[None]]) -> None:
            mock_desk.trigger_monitor_callback = callback

        # Alias establish_connection for test assertions
        mock_desk.establish_connection = mock_establish_connection
        mock_desk.disconnect = AsyncMock(side_effect=mock_disconnect)
        mock_desk.monitor = AsyncMock(side_effect=mock_monitor)
        mock_desk.wakeup = AsyncMock()
        mock_desk.is_connected = False
        mock_desk.is_moving = False
        mock_desk.trigger_disconnected_callback = None

        yield mock_desk
