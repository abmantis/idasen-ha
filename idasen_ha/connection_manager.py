"""Manages the connection state to the desk."""

import asyncio
from collections.abc import Awaitable
import logging
from typing import Callable

from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError, BleakError
from idasen import IdasenDesk

from .errors import AuthFailedError

_LOGGER = logging.getLogger(__name__)


class ConnectionManager:
    """Handles connecting to the desk. Optionally keeps retrying to connect until it succeeds."""

    def __init__(
        self,
        ble_device: BLEDevice,
        connect_callback: Callable[[], Awaitable[None]],
        disconnect_callback: Callable[[], None],
    ):
        """Init ConnectionManager."""
        self._keep_connected: bool = False
        self._connecting: bool = False
        self._retry_pending: bool = False

        self._idasen_desk: IdasenDesk = self._create_idasen_desk(ble_device)

        self._connect_callback = connect_callback
        self._disconnect_callback = disconnect_callback

    @property
    def idasen_desk(self) -> IdasenDesk:
        """The IdasenDesk instance."""
        return self._idasen_desk

    async def connect(self, retry: bool) -> None:
        """Perform the bluetooth connection to the desk."""
        self._keep_connected = True
        await self._connect(retry)

    async def disconnect(self):
        """Stop the connection manager retry task."""
        self._keep_connected = False
        if self._idasen_desk.is_connected:
            await self._idasen_desk.disconnect()

    def _create_idasen_desk(self, ble_device: BLEDevice) -> IdasenDesk:
        return IdasenDesk(
            ble_device,
            exit_on_fail=False,
            disconnected_callback=lambda bledevice: self._handle_disconnect(),
        )

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
                _LOGGER.exception("Connect failed")
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
                _LOGGER.exception("Pair failed")
                await self._idasen_desk.disconnect()
                if retry:
                    self._schedule_reconnect()
                    return
                else:
                    raise ex

            await self._handle_connect()
        finally:
            self._connecting = False

    def _schedule_reconnect(self):
        RECONNECT_INTERVAL_SEC = 30
        _LOGGER.info("Will try to reconnect in %ds", RECONNECT_INTERVAL_SEC)

        if self._retry_pending:
            _LOGGER.warning("There is already a reconnect task pending")
            return
        self._retry_pending = True

        async def _reconnect():
            await asyncio.sleep(RECONNECT_INTERVAL_SEC)
            self._retry_pending = False

            if not self._keep_connected:
                _LOGGER.debug(
                    "Reconnect aborted since it should not be connected"
                    "(this could be on an older instance for an older BLEDevice)"
                )
                return

            if self.idasen_desk.is_connected:
                _LOGGER.debug("Already connected")
                return

            _LOGGER.debug("Reconnecting now")
            await self._connect(True)

        asyncio.get_event_loop().create_task(_reconnect())

    async def _handle_connect(self) -> None:
        _LOGGER.debug("Connected")
        await self._connect_callback()
        if not self._keep_connected:
            _LOGGER.info("Disconnecting since it should not be connected")
            asyncio.get_event_loop().create_task(self.disconnect())

    def _handle_disconnect(self) -> None:
        """Handle bluetooth disconnection."""
        _LOGGER.debug("Disconnected")
        if self._connecting:
            _LOGGER.debug(
                "Disconnected during connection process. No callback triggered."
            )
            return

        self._disconnect_callback()
        if self._keep_connected and not self._retry_pending:
            _LOGGER.info("Reconnecting since it should not be disconnected")
            asyncio.get_event_loop().create_task(self.connect(True))
