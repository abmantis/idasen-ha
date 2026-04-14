"""Tests for ManagedIdasenDesk."""

from unittest.mock import MagicMock

from bleak.backends.device import BLEDevice

from idasen_ha.desk import ManagedIdasenDesk


def test_init_with_ble_device():
    """Test that __init__ does not create a BleakClient."""
    ble_device = BLEDevice("AA:BB:CC:DD:EE:FF", None, {"path": ""})
    desk = ManagedIdasenDesk(ble_device, exit_on_fail=False)

    assert desk.mac == "AA:BB:CC:DD:EE:FF"
    assert desk._client is None
    assert not desk._moving
    assert desk._move_task is None


def test_init_with_mac_string():
    """Test init with a plain MAC address string."""
    desk = ManagedIdasenDesk("AA:BB:CC:DD:EE:FF", exit_on_fail=False)

    assert desk.mac == "AA:BB:CC:DD:EE:FF"
    assert desk._client is None


def test_set_client():
    """Test that set_client replaces the internal client."""
    desk = ManagedIdasenDesk("AA:BB:CC:DD:EE:FF")
    assert desk._client is None

    mock_client = MagicMock()
    desk.set_client(mock_client)
    assert desk._client is mock_client
