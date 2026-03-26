"""Idasen desk helpers for Home Assistant integration."""

import asyncio
import logging
from typing import Optional, Union

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from idasen import IdasenDesk, _DeskLoggingAdapter


class ManagedIdasenDesk(IdasenDesk):
    """IdasenDesk variant whose BLE client is managed externally.

    The upstream ``IdasenDesk.__init__`` creates its own ``BleakClient``, but in
    Bluetooth proxy flows the connection is established externally via
    ``bleak-retry-connector``.  This subclass skips the unused client creation
    and lets the caller inject one later with :meth:`set_client`.
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

    def set_client(self, client: BleakClient) -> None:
        """Adopt an externally-established BLE client."""
        self._client = client
