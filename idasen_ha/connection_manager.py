"""Manages the connection state to the desk."""

import asyncio
from collections.abc import Awaitable
import logging
from typing import Callable

from bleak.exc import BleakDBusError, BleakError
from idasen import IdasenDesk

from .errors import AuthFailedError

_LOGGER = logging.getLogger(__name__)


class ConnectionManager:
    """Handles connecting to the desk. Optionally keeps retrying to connect until it succeeds."""

    def __init__(
        self, desk: IdasenDesk, connect_callback: Callable[[], Awaitable[None]]
    ):
        """Init ConnectionManager."""
        self._idasen_desk = desk
        self._connect_callback = connect_callback

        self._connecting: bool = False
        self._retry_pending: bool = False
        self._retry: bool = False

    async def connect(self, retry: bool = True) -> None:
        """Perform the bluetooth connection to the desk."""
        self._retry = retry
        await self._connect(retry=retry)

    async def disconnect(self):
        """Stop the connection manager retry task."""
        self._retry = False
        if self._idasen_desk.is_connected:
            await self._idasen_desk.disconnect()

    async def _connect(self, retry: bool) -> None:
        if self._connecting:
            _LOGGER.info("Connection already in progress.")
            return

        self._connecting = True
        try:
            try:
                _LOGGER.info("Connecting...")
                await self._idasen_desk.connect()
            except (TimeoutError, BleakError) as ex:
                _LOGGER.warning("Connect failed")
                if retry:
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
                if retry:
                    self._schedule_reconnect()
                    return
                else:
                    raise ex

            _LOGGER.info("Connected!")
            self._retry = False
            await self._connect_callback()
        finally:
            self._connecting = False

    def _schedule_reconnect(self):
        RECONNECT_INTERVAL_SEC = 30
        _LOGGER.info("Will try to connect in %ds", RECONNECT_INTERVAL_SEC)

        if self._retry_pending:
            _LOGGER.warning("There is already a reconnect task pending")
            return

        async def _reconnect():
            self._retry_pending = True
            await asyncio.sleep(RECONNECT_INTERVAL_SEC)
            self._retry_pending = False

            if self._retry is False:
                _LOGGER.debug(
                    "Retrying is disalbed (this could be on an older instance for an older BLEDevice)"
                )
                return

            _LOGGER.debug("Retrying to connect now")
            await self._connect(retry=True)

        asyncio.get_event_loop().create_task(_reconnect())
