from __future__ import annotations

import argparse
import asyncio

from bleak import BleakScanner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan for nearby BLE devices and print advertisement details."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Scan duration in seconds (default: 5.0).",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Optional case-insensitive substring filter for the device name.",
    )
    return parser.parse_args()


def format_manufacturer_data(data: dict[int, bytes]) -> str:
    if not data:
        return "-"
    return ", ".join(
        f"0x{company_id:04X}={payload.hex()}"
        for company_id, payload in sorted(data.items())
    )


def format_service_data(data: dict[str, bytes]) -> str:
    if not data:
        return "-"
    return ", ".join(
        f"{service_uuid}={payload.hex()}"
        for service_uuid, payload in sorted(data.items())
    )


async def scan(timeout: float, name_filter: str | None) -> int:
    results = await BleakScanner.discover(timeout=timeout, return_adv=True)

    matches: list[tuple[str, object, object]] = []
    for device, advertisement in results.values():
        display_name = device.name or advertisement.local_name or "<unknown>"
        if name_filter and name_filter.lower() not in display_name.lower():
            continue
        matches.append((display_name, device, advertisement))

    matches.sort(key=lambda item: item[0].lower())

    if not matches:
        print("No matching BLE devices found.")
        return 1

    for display_name, device, advertisement in matches:
        service_uuids = ", ".join(advertisement.service_uuids or []) or "-"
        print(f"Name: {display_name}")
        print(f"Address: {device.address}")
        print(f"RSSI: {advertisement.rssi}")
        print(f"Service UUIDs: {service_uuids}")
        print(
            "Manufacturer Data: "
            f"{format_manufacturer_data(advertisement.manufacturer_data)}"
        )
        print(f"Service Data: {format_service_data(advertisement.service_data)}")
        print("-" * 60)

    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(scan(args.timeout, args.name))


if __name__ == "__main__":
    raise SystemExit(main())
