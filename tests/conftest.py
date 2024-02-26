"""Generic test fixtures."""

from collections.abc import Awaitable
from typing import Callable, Optional
from unittest import mock
from unittest.mock import AsyncMock

from bleak import BleakClient
from idasen import IdasenDesk
import pytest


@pytest.fixture(autouse=False)
async def mock_idasen_desk():
    """Test height monitoring."""

    with mock.patch(
        "idasen_ha.connection_manager.IdasenDesk", autospec=True
    ) as patched_idasen_desk:
        patched_idasen_desk.MIN_HEIGHT = IdasenDesk.MIN_HEIGHT
        patched_idasen_desk.MAX_HEIGHT = IdasenDesk.MAX_HEIGHT

        mock_desk = patched_idasen_desk.return_value

        def mock_init(
            mac_bledevice,
            exit_on_fail: bool = False,
            disconnected_callback: Optional[Callable[[BleakClient], None]] = None,
        ):
            mock_desk.trigger_disconnected_callback = disconnected_callback
            return mock_desk

        patched_idasen_desk.side_effect = mock_init

        async def mock_connect():
            mock_desk.is_connected = True

        async def mock_disconnect():
            mock_desk.is_connected = False
            mock_desk.trigger_disconnected_callback(None)

        async def mock_monitor(callback: Callable[[float], Awaitable[None]]) -> None:
            mock_desk.trigger_monitor_callback = callback

        mock_desk.connect = AsyncMock(side_effect=mock_connect)
        mock_desk.disconnect = AsyncMock(side_effect=mock_disconnect)
        mock_desk.monitor = AsyncMock(side_effect=mock_monitor)
        mock_desk.is_connected = False
        mock_desk.is_moving = False

        yield mock_desk
