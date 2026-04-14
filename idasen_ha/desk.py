"""Idasen desk helpers for Home Assistant integration."""

import asyncio
import logging
import time
from typing import Optional, Union

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from idasen import (
    _COMMAND_REFERENCE_INPUT_STOP,
    _COMMAND_STOP,
    _COMMAND_WAKEUP,
    _UUID_COMMAND,
    _UUID_REFERENCE_INPUT,
    IdasenDesk,
    _DeskLoggingAdapter,
    _meters_to_bytes,
)

_HEIGHT_TOLERANCE: float = 0.005
_MOVE_WRITE_INTERVAL: float = 0.2
_MOVE_TIMEOUT: float = 30.0


class ManagedIdasenDesk(IdasenDesk):
    """IdasenDesk variant whose BLE client is managed externally.

    The upstream ``IdasenDesk.__init__`` creates its own ``BleakClient``, but in
    Bluetooth proxy flows the connection is established externally via
    ``bleak-retry-connector``.  This subclass skips the unused client creation
    and lets the caller inject one later with :meth:`set_client`.

    It also overrides ``move_to_target`` with a write-only move loop that
    avoids GATT reads during movement, relying on BLE notifications instead.
    """

    def __init__(
        self,
        mac: Union[BLEDevice, str],
        exit_on_fail: bool = False,
    ):
        """Initialize without creating a BleakClient."""
        self._exit_on_fail = exit_on_fail
        self._client: Optional[BleakClient] = None
        self._mac = mac.address if isinstance(mac, BLEDevice) else mac
        self._logger = _DeskLoggingAdapter(
            logger=logging.getLogger(__name__), extra={"mac": self.mac}
        )
        self._moving = False
        self._move_task: Optional[asyncio.Task] = None
        self._notified_height: Optional[float] = None

    @property
    def is_connected(self) -> bool:
        """Return whether the desk is connected."""
        return self._client is not None and self._client.is_connected

    def set_client(self, client: BleakClient) -> None:
        """Adopt an externally-established BLE client."""
        self._client = client

    def update_height(self, height: float) -> None:
        """Store the latest height received via BLE notification."""
        self._notified_height = height

    async def move_to_target(self, target: float) -> None:
        """Move the desk to the target position.

        Sends only GATT writes (no reads) during the move loop to avoid
        blocking the BLE ATT channel, which is especially important over
        Bluetooth proxies.  Arrival is detected via the height reported by
        BLE notifications (see :meth:`update_height`).
        """
        if target > self.MAX_HEIGHT:
            raise ValueError(
                f"target position of {target:.3f} meters exceeds maximum of "
                f"{self.MAX_HEIGHT:.3f}"
            )
        elif target < self.MIN_HEIGHT:
            raise ValueError(
                f"target position of {target:.3f} meters exceeds minimum of "
                f"{self.MIN_HEIGHT:.3f}"
            )

        if self._moving:
            self._logger.error("Already moving")
            return
        self._moving = True

        async def do_move() -> None:
            if self._client is None:
                return

            current_height = await self.get_height()
            if abs(current_height - target) < _HEIGHT_TOLERANCE:
                return

            await self._client.write_gatt_char(_UUID_COMMAND, _COMMAND_WAKEUP)
            await self._client.write_gatt_char(_UUID_COMMAND, _COMMAND_STOP)

            data = _meters_to_bytes(target)
            deadline = time.monotonic() + _MOVE_TIMEOUT
            self._logger.debug(
                "Moving to target=%.3fm from height=%.3fm", target, current_height
            )

            try:
                while self._moving:
                    await self._client.write_gatt_char(
                        _UUID_REFERENCE_INPUT, data, response=True
                    )

                    await asyncio.sleep(_MOVE_WRITE_INTERVAL)

                    height = self._notified_height
                    if height is not None and abs(height - target) < _HEIGHT_TOLERANCE:
                        self._logger.debug("Reached target (height=%.3fm)", height)
                        break

                    if time.monotonic() >= deadline:
                        self._logger.warning(
                            "Move timed out after %.0fs (height=%.3fm target=%.3fm)",
                            _MOVE_TIMEOUT,
                            height if height is not None else -1,
                            target,
                        )
                        break
            finally:
                await self._client.write_gatt_char(
                    _UUID_COMMAND, _COMMAND_STOP, response=False
                )
                await self._client.write_gatt_char(
                    _UUID_REFERENCE_INPUT,
                    _COMMAND_REFERENCE_INPUT_STOP,
                    response=False,
                )

        self._move_task = asyncio.create_task(do_move())
        try:
            await self._move_task
        finally:
            self._moving = False
