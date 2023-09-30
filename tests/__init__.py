"""Tests for idasen_ha."""
from bleak.backends.device import BLEDevice
from idasen import IdasenDesk

FAKE_BLE_DEVICE = BLEDevice("AA:BB:CC:DD:EE:FF", None, None, 0)


def height_percent_to_meters(percent: float):
    """Convert height from percentage to meters."""
    return IdasenDesk.MIN_HEIGHT + (IdasenDesk.MAX_HEIGHT - IdasenDesk.MIN_HEIGHT) * (
        percent / 100
    )
