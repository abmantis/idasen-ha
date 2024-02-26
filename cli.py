"""Manual testing CLI."""

# ruff: noqa: T201
import argparse
import asyncio
import logging

import aioconsole
from bleak import BleakScanner

from idasen_ha import Desk

logging.basicConfig(format="%(asctime)s [%(name)s %(levelname)s]: %(message)s")
logger = logging.getLogger("idasen_ha")
logger.setLevel(logging.DEBUG)
logging.getLogger("idasen").setLevel(logging.DEBUG)
logging.getLogger("bleak").setLevel(logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument("-a", "--address", help="Desk's bluetooth address")
args = parser.parse_args()


async def getBLEDevice(address: str):
    """Get BLE Device from address."""
    return await BleakScanner.find_device_by_address(
        address
    )  # pyright: ignore[reportGeneralTypeIssues]


def print_menu():
    """Print the menu."""
    print("\n")
    print(30 * "-", "MENU", 30 * "-")
    print("c - Connect")
    print("d - Disconnect")
    print("q - Quit")
    print("h - Print this menu")
    print(67 * "-")


async def start():
    """Start the CLI."""

    if args.address is None:
        logger.error("Desk address argument missing")
        return

    def update_callback(height: int | None):
        pass

    ble_device = await getBLEDevice(args.address)
    if ble_device is None:
        logger.error("Desk not found")
        return

    desk = Desk(update_callback)

    loop = True
    while loop:
        print_menu()
        choice = await aioconsole.ainput("Enter your choice: ")

        if choice == "h":
            print_menu()
        elif choice == "c":
            try:
                await desk.connect(ble_device, True)
            except Exception as ex:
                logger.exception(ex)
        elif choice == "d":
            await desk.disconnect()
        elif choice == "q":
            loop = False
        else:
            print("Wrong option selection. Enter any key to try again..")


asyncio.run(start())
