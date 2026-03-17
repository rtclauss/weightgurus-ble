from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

WEIGHT_GURUS_SCAN_UUIDS = {
    "00007802-0000-1000-8000-00805f9b34fb",
    "20568521-5acd-4c5a-9294-eb2691c8b8bf",
    "0d005750-c36b-11e3-9c1a-0800200c9a66",
    "0000fff0-0000-1000-8000-00805f9b34fb",
}

PROFILE_SCAN_UUIDS = {
    "a3": {
        "00007802-0000-1000-8000-00805f9b34fb",
        "20568521-5acd-4c5a-9294-eb2691c8b8bf",
        "0d005750-c36b-11e3-9c1a-0800200c9a66",
    },
    "a6": {
        "20568521-5acd-4c5a-9294-eb2691c8b8bf",
        "e492c1fb-2466-4749-ab37-69433d2d7846",
        "0000a602-0000-1000-8000-00805f9b34fb",
    },
    "r4": {"0000fff0-0000-1000-8000-00805f9b34fb"},
    "all": WEIGHT_GURUS_SCAN_UUIDS,
}

PROFILE_NOTIFY_UUIDS = {
    "a3": {
        "00008a82-0000-1000-8000-00805f9b34fb",
        "00008a24-0000-1000-8000-00805f9b34fb",
        "00008a22-0000-1000-8000-00805f9b34fb",
    },
    "a6": {
        "0000a620-0000-1000-8000-00805f9b34fb",
        "0000a621-0000-1000-8000-00805f9b34fb",
        "0000a625-0000-1000-8000-00805f9b34fb",
    },
    "r4": {
        "0000fff1-0000-1000-8000-00805f9b34fb",
        "0000fff2-0000-1000-8000-00805f9b34fb",
        "0000fff3-0000-1000-8000-00805f9b34fb",
    },
    "all": {
        "00008a82-0000-1000-8000-00805f9b34fb",
        "00008a24-0000-1000-8000-00805f9b34fb",
        "00008a22-0000-1000-8000-00805f9b34fb",
        "0000a620-0000-1000-8000-00805f9b34fb",
        "0000a621-0000-1000-8000-00805f9b34fb",
        "0000a625-0000-1000-8000-00805f9b34fb",
        "0000fff1-0000-1000-8000-00805f9b34fb",
        "0000fff2-0000-1000-8000-00805f9b34fb",
        "0000fff3-0000-1000-8000-00805f9b34fb",
    },
}


def parse_hex_or_int(value: str) -> int:
    return int(value, 0)


def normalize_hex(value: str | None) -> str | None:
    if value is None:
        return None
    return value.lower().replace(":", "").replace(" ", "")


def normalize_uuid(value: str) -> str:
    return value.strip().lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to a BLE device and log notifications."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Scan timeout before giving up (default: 20).",
    )
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=60.0,
        help="How long to keep notification subscriptions active (default: 60).",
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
        "--profile",
        choices=sorted(PROFILE_SCAN_UUIDS),
        default=None,
        help="Optional Weight Gurus profile preset (a3, r4, or all).",
    )
    parser.add_argument(
        "--notify",
        action="append",
        default=None,
        help="Optional characteristic UUID to subscribe to. Repeat to add more.",
    )
    parser.add_argument(
        "--jsonl",
        default=None,
        help="Optional JSONL output path for notification events.",
    )
    return parser.parse_args()


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

    if manufacturer_id is not None and manufacturer_id not in advertisement.manufacturer_data:
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


def characteristic_matches(
    characteristic: Any, wanted_notify_uuids: set[str] | None
) -> bool:
    properties = {property_name.lower() for property_name in characteristic.properties}
    if "notify" not in properties and "indicate" not in properties:
        return False
    if wanted_notify_uuids is None:
        return True
    return characteristic.uuid.lower() in wanted_notify_uuids


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


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

    jsonl_path = Path(args.jsonl).expanduser() if args.jsonl else None

    async with BleakClient(device) as client:
        handle_to_uuid: dict[int, str] = {}
        matching_characteristics: list[Any] = []
        notifiable_characteristics: list[dict[str, Any]] = []

        for service in client.services:
            for characteristic in service.characteristics:
                handle_to_uuid[characteristic.handle] = characteristic.uuid.lower()
                properties = sorted(
                    property_name.lower() for property_name in characteristic.properties
                )
                if "notify" in properties or "indicate" in properties:
                    snapshot = {
                        "uuid": characteristic.uuid,
                        "handle": characteristic.handle,
                        "properties": properties,
                    }
                    notifiable_characteristics.append(snapshot)
                if characteristic_matches(characteristic, args.notify_uuids):
                    matching_characteristics.append(characteristic)

        if not matching_characteristics:
            print(
                json.dumps(
                    {
                        "error": "No matching notifiable characteristics found.",
                        "notifiable_characteristics": notifiable_characteristics,
                    },
                    sort_keys=True,
                )
            )
            return 1

        print(
            json.dumps(
                {
                    "subscribing": [
                        {
                            "uuid": characteristic.uuid,
                            "handle": characteristic.handle,
                            "properties": sorted(
                                property_name.lower()
                                for property_name in characteristic.properties
                            ),
                        }
                        for characteristic in matching_characteristics
                    ]
                },
                sort_keys=True,
            )
        )

        def notification_handler(sender: Any, data: bytearray) -> None:
            sender_handle = getattr(sender, "handle", sender)
            sender_uuid = getattr(sender, "uuid", handle_to_uuid.get(sender_handle))
            payload = {
                "time": time.time(),
                "characteristic_uuid": sender_uuid,
                "handle": sender_handle,
                "value_hex": bytes(data).hex(),
            }
            print(json.dumps(payload, sort_keys=True))
            if jsonl_path:
                append_jsonl(jsonl_path, payload)

        for characteristic in matching_characteristics:
            await client.start_notify(characteristic, notification_handler)

        try:
            await asyncio.sleep(args.listen_seconds)
        finally:
            for characteristic in matching_characteristics:
                try:
                    await client.stop_notify(characteristic)
                except Exception:  # pragma: no cover - hardware dependent
                    pass

    return 0


def main() -> int:
    args = parse_args()
    args.manufacturer_payload = normalize_hex(args.manufacturer_payload)

    requested_service_uuids = (
        {normalize_uuid(service_uuid) for service_uuid in args.service_uuid}
        if args.service_uuid
        else set()
    )
    if args.profile:
        requested_service_uuids.update(PROFILE_SCAN_UUIDS[args.profile])
    args.service_uuids = requested_service_uuids or None

    if args.notify:
        args.notify_uuids = {normalize_uuid(notify_uuid) for notify_uuid in args.notify}
    elif args.profile:
        args.notify_uuids = PROFILE_NOTIFY_UUIDS[args.profile]
    else:
        args.notify_uuids = None

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
