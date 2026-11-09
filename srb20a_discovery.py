"""Discover nearby Yamaha soundbars; selection does not write to any device."""
from bleak import BleakScanner

SERVICE = '945ca2b0-852c-4ab8-b654-354df41c2795'


async def discover_soundbars(seconds=7):
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    candidates = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ''
        services = [item.lower() for item in (adv.service_uuids or [])]
        if name.lower() == 'yamahaav' or SERVICE in services:
            candidates.append((device.address, name or 'Yamaha soundbar'))
    return sorted(set(candidates))
