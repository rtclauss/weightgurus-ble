from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


@dataclass
class AdvertisementEvent:
    event_time: float
    address: str
    name: str
    local_name: str | None
    rssi: int
    connectable: bool | None
    tx_power: int | None
    manufacturer_data: dict[str, str]
    service_data: dict[str, str]
    service_uuids: list[str]


def parse_hex_or_int(value: str) -> int:
    return int(value, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuously watch BLE advertisements and log matching events."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="How long to watch in seconds (default: 30).",
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
        "--emit-duplicates",
        action="store_true",
        help="Emit every matching advertisement instead of only changes.",
    )
    parser.add_argument(
        "--jsonl",
        default=None,
        help="Optional JSONL output path for captured events.",
    )
    return parser.parse_args()


def normalize_hex(value: str | None) -> str | None:
    if value is None:
        return None
    return value.lower().replace(":", "").replace(" ", "")


def normalize_uuid(value: str) -> str:
    return value.strip().lower()


def event_from(device: BLEDevice, advertisement: AdvertisementData) -> AdvertisementEvent:
    manufacturer_data = {
        f"0x{company_id:04x}": payload.hex()
        for company_id, payload in sorted(advertisement.manufacturer_data.items())
    }
    service_data = {
        service_uuid: payload.hex()
        for service_uuid, payload in sorted(advertisement.service_data.items())
    }
    return AdvertisementEvent(
        event_time=time.time(),
        address=device.address,
        name=device.name or "",
        local_name=advertisement.local_name,
        rssi=advertisement.rssi,
        connectable=getattr(advertisement, "connectable", None),
        tx_power=advertisement.tx_power,
        manufacturer_data=manufacturer_data,
        service_data=service_data,
        service_uuids=sorted(advertisement.service_uuids or []),
    )


def matches(
    event: AdvertisementEvent,
    *,
    address: str | None,
    name_filter: str | None,
    manufacturer_id: int | None,
    manufacturer_payload: str | None,
    service_uuids: set[str] | None,
) -> bool:
    if address and event.address.lower() != address.lower():
        return False

    if name_filter:
        haystacks = [event.name, event.local_name or ""]
        if not any(name_filter.lower() in haystack.lower() for haystack in haystacks):
            return False

    if manufacturer_id is not None:
        key = f"0x{manufacturer_id:04x}"
        if key not in event.manufacturer_data:
            return False

    if manufacturer_payload is not None:
        wanted = normalize_hex(manufacturer_payload)
        if wanted not in event.manufacturer_data.values():
            return False

    if service_uuids is not None and not service_uuids.intersection(event.service_uuids):
        return False

    return True


def event_signature(event: AdvertisementEvent) -> tuple[Any, ...]:
    return (
        event.address,
        event.name,
        event.local_name,
        event.rssi,
        event.connectable,
        event.tx_power,
        tuple(sorted(event.manufacturer_data.items())),
        tuple(sorted(event.service_data.items())),
        tuple(event.service_uuids),
    )


def print_event(event: AdvertisementEvent) -> None:
    print(
        json.dumps(
            {
                "time": event.event_time,
                "address": event.address,
                "name": event.name,
                "local_name": event.local_name,
                "rssi": event.rssi,
                "connectable": event.connectable,
                "tx_power": event.tx_power,
                "manufacturer_data": event.manufacturer_data,
                "service_data": event.service_data,
                "service_uuids": event.service_uuids,
            },
            sort_keys=True,
        )
    )


def append_jsonl(path: Path, event: AdvertisementEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(event), sort_keys=True))
        handle.write("\n")


async def watch(args: argparse.Namespace) -> int:
    jsonl_path = Path(args.jsonl).expanduser() if args.jsonl else None
    last_seen: dict[str, tuple[Any, ...]] = {}
    matched_events = 0

    def detection_callback(device: BLEDevice, advertisement: AdvertisementData) -> None:
        nonlocal matched_events

        event = event_from(device, advertisement)
        if not matches(
            event,
            address=args.address,
            name_filter=args.name,
            manufacturer_id=args.manufacturer_id,
            manufacturer_payload=args.manufacturer_payload,
            service_uuids=args.service_uuids,
        ):
            return

        signature = event_signature(event)
        previous = last_seen.get(event.address)
        if previous == signature and not args.emit_duplicates:
            return

        last_seen[event.address] = signature
        matched_events += 1
        print_event(event)
        if jsonl_path:
            append_jsonl(jsonl_path, event)

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    try:
        await asyncio.sleep(args.timeout)
    finally:
        await scanner.stop()

    if matched_events == 0:
        print("No matching BLE advertisements captured.")
        return 1

    return 0


def main() -> int:
    args = parse_args()
    args.manufacturer_payload = normalize_hex(args.manufacturer_payload)
    args.service_uuids = (
        {normalize_uuid(service_uuid) for service_uuid in args.service_uuid}
        if args.service_uuid
        else None
    )
    return asyncio.run(watch(args))


if __name__ == "__main__":
    raise SystemExit(main())
