from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


def parse_hex_or_int(value: str) -> int:
    return int(value, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find a BLE device, connect, and dump its GATT services."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Scan timeout before giving up (default: 20).",
    )
    parser.add_argument(
        "--address",
        default=None,
        help="Optional exact device address filter.",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Optional case-insensitive substring filter for device or local name.",
    )
    parser.add_argument(
        "--manufacturer-id",
        type=parse_hex_or_int,
        default=None,
        help="Optional manufacturer company ID filter, e.g. 76 or 0x004c.",
    )
    parser.add_argument(
        "--manufacturer-payload",
        default=None,
        help="Optional exact hex payload filter for manufacturer data.",
    )
    parser.add_argument(
        "--service-uuid",
        action="append",
        default=None,
        help="Optional service UUID filter. Repeat to match any of multiple UUIDs.",
    )
    parser.add_argument(
        "--read",
        action="store_true",
        help="Attempt to read readable characteristics after discovery.",
    )
    return parser.parse_args()


def normalize_hex(value: str | None) -> str | None:
    if value is None:
        return None
    return value.lower().replace(":", "").replace(" ", "")


def normalize_uuid(value: str) -> str:
    return value.strip().lower()


def matches(
    device: BLEDevice,
    advertisement: AdvertisementData,
    *,
    address: str | None,
    name_filter: str | None,
    manufacturer_id: int | None,
    manufacturer_payload: str | None,
    service_uuids: set[str] | None,
) -> bool:
    if address and device.address.lower() != address.lower():
        return False

    if name_filter:
        device_name = device.name or ""
        local_name = advertisement.local_name or ""
        needle = name_filter.lower()
        if needle not in device_name.lower() and needle not in local_name.lower():
            return False

    if manufacturer_id is not None:
        if manufacturer_id not in advertisement.manufacturer_data:
            return False

    if manufacturer_payload is not None:
        payloads = {payload.hex() for payload in advertisement.manufacturer_data.values()}
        if manufacturer_payload not in payloads:
            return False

    if service_uuids is not None:
        advertised = {uuid.lower() for uuid in advertisement.service_uuids or []}
        if not service_uuids.intersection(advertised):
            return False

    return True


async def find_candidate(args: argparse.Namespace) -> tuple[BLEDevice, AdvertisementData] | None:
    results = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    for device, advertisement in results.values():
        if matches(
            device,
            advertisement,
            address=args.address,
            name_filter=args.name,
            manufacturer_id=args.manufacturer_id,
            manufacturer_payload=args.manufacturer_payload,
            service_uuids=args.service_uuids,
        ):
            return device, advertisement
    return None


def characteristic_snapshot(characteristic: Any) -> dict[str, Any]:
    properties = sorted(
        property_name.lower() for property_name in getattr(characteristic, "properties", [])
    )
    descriptors = [
        {"uuid": descriptor.uuid, "handle": descriptor.handle}
        for descriptor in getattr(characteristic, "descriptors", [])
    ]
    return {
        "uuid": characteristic.uuid,
        "handle": characteristic.handle,
        "properties": properties,
        "descriptors": descriptors,
    }


async def dump_services(client: BleakClient, read_values: bool) -> dict[str, Any]:
    services_payload: list[dict[str, Any]] = []
    for service in client.services:
        characteristics_payload: list[dict[str, Any]] = []
        for characteristic in service.characteristics:
            snapshot = characteristic_snapshot(characteristic)
            if read_values and "read" in snapshot["properties"]:
                try:
                    value = await client.read_gatt_char(characteristic.uuid)
                    snapshot["value_hex"] = value.hex()
                except Exception as exc:  # pragma: no cover - hardware dependent
                    snapshot["read_error"] = str(exc)
            characteristics_payload.append(snapshot)
        services_payload.append(
            {
                "uuid": service.uuid,
                "handle": service.handle,
                "characteristics": characteristics_payload,
            }
        )
    return {"services": services_payload}


async def run(args: argparse.Namespace) -> int:
    candidate = await find_candidate(args)
    if candidate is None:
        print("No matching BLE device found during scan.")
        return 1

    device, advertisement = candidate
    header = {
        "address": device.address,
        "name": device.name,
        "local_name": advertisement.local_name,
        "rssi": advertisement.rssi,
        "service_uuids": sorted(advertisement.service_uuids or []),
        "manufacturer_data": {
            f"0x{company_id:04x}": payload.hex()
            for company_id, payload in sorted(advertisement.manufacturer_data.items())
        },
    }

    print(json.dumps({"match": header}, sort_keys=True))

    async with BleakClient(device) as client:
        payload = await dump_services(client, args.read)
        print(json.dumps(payload, sort_keys=True))

    return 0


def main() -> int:
    args = parse_args()
    args.manufacturer_payload = normalize_hex(args.manufacturer_payload)
    args.service_uuids = (
        {normalize_uuid(service_uuid) for service_uuid in args.service_uuid}
        if args.service_uuid
        else None
    )
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
