"""Helper for Home Assistant Idasen Desk integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from idasen import IdasenDesk

from .connection_manager import ConnectionManager

_LOGGER = logging.getLogger(__name__)


class Desk:
    """Wrapper around the IdasenDesk from the idasen library."""

    def __init__(
        self,
        update_callback: Callable[[int | None], None] | None,
        monitor_height: bool = True,
    ) -> None:
        """Initialize the wrapper."""
        self._idasen_desk: IdasenDesk | None = None
        self._ble_device: BLEDevice | None = None
        self._connection_manager: ConnectionManager | None = None
        self._height: float | None = None
        self._monitor_height: bool = monitor_height

        if update_callback:
            self._update_callback = update_callback
        else:

            def empty_update_callback(height: int | None) -> None:
                pass

            self._update_callback = empty_update_callback

    async def connect(self, ble_device: BLEDevice, retry: bool = True) -> None:
        """Perform the bluetooth connection to the desk."""
        _LOGGER.debug("Connecting")

        if (
            self._connection_manager is None
            or self._ble_device is None
            or ble_device.address != self._ble_device.address
        ):
            _LOGGER.debug("Initializing idasen desk")
            await self.disconnect()
            self._ble_device = ble_device
            self._idasen_desk = self._create_idasen_desk(self._ble_device)
            self._connection_manager = self._create_connection_manager(
                self._idasen_desk
            )

        await self._connection_manager.connect(retry=retry)

    async def disconnect(self) -> None:
        """Disconnect from the desk."""
        if self._connection_manager:
            _LOGGER.debug("Disconnecting")
            await self._connection_manager.disconnect()

    async def move_to(self, heigh_percent: int) -> None:
        """Move the desk to a specific position."""
        _LOGGER.debug("Moving to %s", heigh_percent)
        if not self.is_connected or self._idasen_desk is None:
            _LOGGER.warning("Not connected")
            return

        if self._idasen_desk.is_moving:
            await self._idasen_desk.stop()
            # Let it settle before requesting a new move
            await asyncio.sleep(0.5)

        height = IdasenDesk.MIN_HEIGHT + (
            IdasenDesk.MAX_HEIGHT - IdasenDesk.MIN_HEIGHT
        ) * (heigh_percent / 100)

        await self._idasen_desk.move_to_target(height)

    async def move_up(self) -> None:
        """Move the desk up."""
        _LOGGER.debug("Moving up")
        await self.move_to(100)

    async def move_down(self) -> None:
        """Move the desk down."""
        _LOGGER.debug("Moving down")
        await self.move_to(0)

    async def stop(self) -> None:
        """Stop moving the desk."""
        _LOGGER.debug("Stopping")
        if not self.is_connected or self._idasen_desk is None:
            _LOGGER.warning("Not connected")
            return
        await self._idasen_desk.stop()

    async def _start_monitoring(self) -> None:
        """Start monitoring for height changes."""
        if not self.is_connected or self._idasen_desk is None:
            _LOGGER.warning("Not connected")
            return

        async def update_height(height: float) -> None:
            self._height = height
            self._update_callback(self.height_percent)

        await self._idasen_desk.monitor(update_height)

    @property
    def height(self) -> float | None:
        """The current height in meters."""
        return self._height

    @property
    def height_percent(self) -> int | None:
        """The current height in percentage."""
        if self._height is None:
            return None

        return int(
            round(
                100
                * (self._height - IdasenDesk.MIN_HEIGHT)
                / (IdasenDesk.MAX_HEIGHT - IdasenDesk.MIN_HEIGHT)
            )
        )

    @property
    def is_connected(self) -> bool:
        """True if the bluetooth connection is currently established."""
        if self._idasen_desk is None:
            return False
        # bleak `is_connected` method returns a `_DeprecatedIsConnectedReturn`,
        # so we properly cast it to bool otherwise `is_connected == True`
        # will always be False.
        return bool(self._idasen_desk.is_connected)

    def _create_idasen_desk(self, ble_device: BLEDevice) -> IdasenDesk:
        def disconnect_callback(client: BleakClient) -> None:
            """Handle bluetooth disconnection."""
            _LOGGER.debug("Disconnect callback called")
            self._update_callback(self.height_percent)

        return IdasenDesk(
            ble_device, exit_on_fail=False, disconnected_callback=disconnect_callback
        )

    def _create_connection_manager(self, desk: IdasenDesk) -> ConnectionManager:
        async def connect_callback() -> None:
            _LOGGER.debug("Connect callback called")
            if self._idasen_desk is None:
                _LOGGER.error("Desk is None after connecting")
                return

            if self._monitor_height:
                self._height = await self._idasen_desk.get_height()
                await self._start_monitoring()

            self._update_callback(self.height_percent)

        return ConnectionManager(
            desk,
            connect_callback=connect_callback,
        )
