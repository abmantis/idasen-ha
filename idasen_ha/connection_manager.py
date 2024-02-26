"""Manages the connection state to the desk."""

import asyncio
from collections.abc import Awaitable
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError, BleakError
from idasen import IdasenDesk

from .errors import AuthFailedError

_LOGGER = logging.getLogger(__name__)


class ConnectionManager:
    """Manages the connection state to the desk.

    This retries to reconnect when the connection is lost.
    """

    def __init__(
        self,
        connect_callback: Callable[[IdasenDesk], Awaitable[None]],
        disconnect_callback: Callable[[], None],
    ):
        """Init ConnectionManager."""
        self._connect_callback = connect_callback
        self._disconnect_callback = disconnect_callback
        self._idasen_desk: IdasenDesk | None = None
        self._connecting: bool = False
        self._pending_reconnet: bool = False

    async def connect(
        self,
        ble_device: BLEDevice,
        auto_reconnect: bool = True,
    ):
        """Perform the bluetooth connection to the desk."""

        if self._idasen_desk and self._connecting:
            _LOGGER.debug("Connection in progress already")
            return self._idasen_desk

        def internal_disconnect_callback(client: BleakClient) -> None:
            """Handle bluetooth disconnection."""
            _LOGGER.debug("Disconnect callback called")
            self._disconnect_callback()

        self._idasen_desk = IdasenDesk(
            ble_device,
            exit_on_fail=False,
            disconnected_callback=internal_disconnect_callback,
        )

        await self._connect(auto_reconnect=auto_reconnect)

    async def _connect(self, auto_reconnect: bool = True):
        if self._idasen_desk is None:
            _LOGGER.info("Not connecting since desk is None (disconnect called?).")
            return

        self._connecting = True
        try:
            try:
                _LOGGER.info("Connecting...")
                await self._idasen_desk.connect()
            except (TimeoutError, BleakError) as ex:
                _LOGGER.warning("Connect failed")
                if auto_reconnect:
                    self._schedule_reconnect()
                    return
                else:
                    raise ex

            try:
                _LOGGER.info("Pairing...")
                await self._idasen_desk.pair()
            except BleakDBusError as ex:
                await self._idasen_desk.disconnect()
                if ex.dbus_error == "org.bluez.Error.AuthenticationFailed":
                    raise AuthFailedError() from ex
                raise ex
            except Exception as ex:
                _LOGGER.warning("Pair failed")
                await self._idasen_desk.disconnect()
                if auto_reconnect:
                    self._schedule_reconnect()
                    return
                else:
                    raise ex

            _LOGGER.info("Connected!")
            await self._connect_callback(self._idasen_desk)
        finally:
            self._connecting = False

    async def disconnect(self) -> None:
        """Disconnect from the desk."""
        _LOGGER.info("Disconnecting")
        try:
            if self._idasen_desk is None:
                _LOGGER.warning("Already disconnected")
                return
            await self._idasen_desk.disconnect()
        finally:
            self._idasen_desk = None

    def _schedule_reconnect(self):
        RECONNECT_INTERVAL_SEC = 30
        _LOGGER.info("Will try to connect in %ds", RECONNECT_INTERVAL_SEC)

        if self._pending_reconnet:
            _LOGGER.warning("There is already a reconnect task pending")
            return

        async def _reconnect():
            self._pending_reconnet = True
            await asyncio.sleep(RECONNECT_INTERVAL_SEC)
            self._pending_reconnet = False
            _LOGGER.debug("Retrying to connect now")
            if self._idasen_desk is not None and self._idasen_desk.is_connected:
                _LOGGER.debug("Already connected")
                return
            await self._connect()

        asyncio.get_event_loop().create_task(_reconnect())
