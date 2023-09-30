"""Manages the connection state to the desk."""
import asyncio
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from idasen import IdasenDesk

_LOGGER = logging.getLogger(__name__)


class ConnectionManager:
    """Manages the connection state to the desk.

    This retries to reconnect when the connection is lost.
    """

    async def connect(
        self, ble_device: BLEDevice, disconnect_callback=Callable[[], None]
    ) -> IdasenDesk:
        """Perform the bluetooth connection to the desk."""

        def internal_disconnect_callback(client: BleakClient) -> None:
            """Handle bluetooth disconnection."""
            _LOGGER.debug("Disconnect callback called")
            disconnect_callback()

        self._idasen_desk = IdasenDesk(
            ble_device,
            exit_on_fail=False,
            disconnected_callback=internal_disconnect_callback,
        )

        await self._connect()
        return self._idasen_desk

    async def _connect(self):
        if self._idasen_desk is None:
            _LOGGER.info("Not connecting since desk is None.")
            return
        try:
            _LOGGER.info("Connecting...")
            await self._idasen_desk.connect()
            _LOGGER.info("Connected!")
        except (TimeoutError, BleakError):
            self._schedule_reconnect()

    async def disconnect(self) -> None:
        """Disconnect from the desk."""
        _LOGGER.info("Disconnecting")
        try:
            if self._idasen_desk is None or not self._idasen_desk.is_connected:
                _LOGGER.warning("Already disconnected")
                return
            await self._idasen_desk.disconnect()
        finally:
            self._idasen_desk = None

    def _schedule_reconnect(self):
        RECONNECT_INTERVAL_SEC = 3
        _LOGGER.info("Will try to connect in %ds", RECONNECT_INTERVAL_SEC)

        async def _reconnect():
            await asyncio.sleep(RECONNECT_INTERVAL_SEC)
            await self._connect()

        asyncio.get_event_loop().create_task(_reconnect())
        pass
