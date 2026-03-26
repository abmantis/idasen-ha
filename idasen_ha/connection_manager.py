"""Manages the connection state to the desk."""

import asyncio
from collections.abc import Awaitable
import logging
from typing import Callable

from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError, BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    close_stale_connections_by_address,
    establish_connection,
)

from .desk import ManagedIdasenDesk
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
        self._ble_device = ble_device

        self._idasen_desk: ManagedIdasenDesk = self._create_idasen_desk(ble_device)

        self._connect_callback = connect_callback
        self._disconnect_callback = disconnect_callback

    @property
    def idasen_desk(self) -> ManagedIdasenDesk:
        """The IdasenDesk instance."""
        return self._idasen_desk

    async def connect(self, ble_device: BLEDevice, retry: bool) -> None:
        """Perform the bluetooth connection to the desk."""
        if ble_device.address != self._ble_device.address:
            self._ble_device = ble_device
            self._idasen_desk = self._create_idasen_desk(ble_device)
        self._keep_connected = True
        await self._connect(retry)

    async def disconnect(self):
        """Stop the connection manager retry task."""
        self._keep_connected = False
        if self._idasen_desk.is_connected:
            await self._idasen_desk.disconnect()

    def _create_idasen_desk(self, ble_device: BLEDevice) -> ManagedIdasenDesk:
        return ManagedIdasenDesk(ble_device, exit_on_fail=False)

    async def _connect(self, retry: bool) -> None:
        if self._idasen_desk.is_connected:
            _LOGGER.debug("Desk already connected, skipping connect")
            return

        if self._connecting:
            _LOGGER.debug("Connection already in progress")
            return

        self._connecting = True
        try:
            try:
                _LOGGER.info("Connecting via bleak-retry-connector...")
                await close_stale_connections_by_address(self._ble_device.address)
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    self._ble_device,
                    self._ble_device.address,
                    disconnected_callback=lambda _client: self._handle_disconnect(),
                )
                self._idasen_desk.set_client(client)
            except (TimeoutError, BleakError) as ex:
                _LOGGER.exception("Connect failed")
                if retry:
                    self._schedule_reconnect()
                    return
                raise ex

            try:
                _LOGGER.info("Pairing...")
                await self._idasen_desk.pair()
            except BleakDBusError as ex:
                _LOGGER.exception("Pair failed")
                await self._idasen_desk.disconnect()
                if retry:
                    self._schedule_reconnect()
                    return
                if ex.dbus_error == "org.bluez.Error.AuthenticationFailed":
                    raise AuthFailedError() from ex
                raise ex
            except Exception as ex:
                _LOGGER.exception("Pair failed")
                await self._idasen_desk.disconnect()
                if retry:
                    self._schedule_reconnect()
                    return
                raise ex

            try:
                # Wakeup after pair so BLE authentication completes before
                # writing to GATT characteristics. IdasenDesk.connect()
                # normally does this immediately, which fails through
                # Bluetooth proxies that require bonding first.
                await self._idasen_desk.wakeup()
            except (TimeoutError, BleakError) as ex:
                _LOGGER.exception("Wakeup failed")
                await self._idasen_desk.disconnect()
                if retry:
                    self._schedule_reconnect()
                    return
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
            asyncio.get_event_loop().create_task(self.connect(self._ble_device, True))
