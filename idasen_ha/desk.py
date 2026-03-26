"""Idasen desk helpers for Home Assistant integration."""

from bleak import BleakClient
from idasen import IdasenDesk


class ManagedIdasenDesk(IdasenDesk):
    """IdasenDesk variant that can adopt an already-established client."""

    def set_client(self, client: BleakClient) -> None:
        """Replace the internally-created client with an external one.

        The upstream ``IdasenDesk.connect()`` creates its own ``BleakClient`` and then
        immediately calls ``wakeup()``. For Bluetooth proxy flows we establish the
        connection externally and delay ``wakeup()`` until after pairing/authentication
        completes, so the manager injects the already-connected client here instead of
        calling ``IdasenDesk.connect()``.
        """
        self._client = client
