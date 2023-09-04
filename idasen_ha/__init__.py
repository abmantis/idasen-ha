"""Helper for Home Assistant Idasen Desk integration."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from idasen import IdasenDesk

_LOGGER = logging.getLogger(__name__)


class Desk:
    """Wrapper around the IdasenDesk from the idasen library."""

    def __init__(
        self,
        update_callback: Callable[[int | None], None] | None,
    ) -> None:
        """Initialize the wrapper."""
        self._idasen_desk: IdasenDesk = None
        self._height: float | None = None

        if update_callback:
            self._update_callback = update_callback
        else:

            def empty_update_callback(height: int | None) -> None:
                pass

            self._update_callback = empty_update_callback

    async def connect(self, ble_device: BLEDevice, monitor_height: bool = True) -> None:
        """Perform the bluetooth connection to the desk."""
        _LOGGER.debug("Connecting")

        def disconnect_callback(client: BleakClient) -> None:
            """Handle bluetooth disconnection."""
            _LOGGER.debug("Disconnect callback called")
            self._update_callback(self.height_percent)

        self._idasen_desk = IdasenDesk(
            ble_device, exit_on_fail=False, disconnected_callback=disconnect_callback
        )

        await self._idasen_desk.connect()
        try:
            await self._idasen_desk.pair()
        except Exception as ex:
            await self._idasen_desk.disconnect()
            self._idasen_desk = None
            raise ex

        if monitor_height:
            self._height = await self._idasen_desk.get_height()
            await self._start_monitoring()
        self._update_callback(self.height_percent)

    async def disconnect(self) -> None:
        """Disconnect from the desk."""
        _LOGGER.debug("Disconnecting")
        if not self.is_connected:
            _LOGGER.warning("Already disconnected")
            return
        await self._idasen_desk.disconnect()
        self._idasen_desk = None

    async def move_to(self, heigh_percent: int) -> None:
        """Move the desk to a specific position."""
        _LOGGER.debug("Moving to %s", heigh_percent)
        if self._idasen_desk.is_moving:
            await self._idasen_desk.stop()
            # Let it settle before requesting new move
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
        await self._idasen_desk.stop()

    async def _start_monitoring(self) -> None:
        """Start monitoring for height changes."""

        async def update_height(height: float) -> None:
            self._height = height
            self._update_callback(self.height_percent)

        await self._idasen_desk.monitor(update_height)

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
