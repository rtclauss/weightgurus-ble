from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.weightgurus_ble.metrics import (
    A6UserProfile,
    compute_a6_derived_metrics,
)

A6_SCAN_UUIDS = {
    "20568521-5acd-4c5a-9294-eb2691c8b8bf",
    "e492c1fb-2466-4749-ab37-69433d2d7846",
    "0000a602-0000-1000-8000-00805f9b34fb",
}

A6_INDICATE_UUID = "0000a620-0000-1000-8000-00805f9b34fb"
A6_NOTIFY_UUID = "0000a621-0000-1000-8000-00805f9b34fb"
A6_WRITE_ACK_UUID = "0000a622-0000-1000-8000-00805f9b34fb"
A6_WRITE_COMMAND_UUID = "0000a624-0000-1000-8000-00805f9b34fb"
A6_NOTIFY_ACK_UUID = "0000a625-0000-1000-8000-00805f9b34fb"
A6_INFO_VOLTAGE_UUID = "0000a640-0000-1000-8000-00805f9b34fb"
A6_INFO_FEATURE_UUID = "0000a641-0000-1000-8000-00805f9b34fb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive the A6-family BLE session used by Weight Gurus LS212-B."
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
        help="How long to keep the session open (default: 60).",
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
        "--profile-json",
        default=None,
        help="Optional JSON file with height_cm, birthday, sex, and athlete fields.",
    )
    parser.add_argument(
        "--save-profile",
        default=None,
        help="Optional path to write the merged profile JSON before connecting.",
    )
    parser.add_argument(
        "--height-cm",
        type=float,
        default=None,
        help="Profile height in centimeters for derived metrics.",
    )
    parser.add_argument(
        "--birthday",
        default=None,
        help="Profile birthday (YYYY-MM-DD) for derived metrics.",
    )
    parser.add_argument(
        "--sex",
        choices=("male", "female"),
        default=None,
        help="Profile sex for derived metrics.",
    )
    athlete_group = parser.add_mutually_exclusive_group()
    athlete_group.add_argument(
        "--athlete",
        action="store_true",
        default=None,
        help="Mark the profile as athlete mode for derived metrics.",
    )
    athlete_group.add_argument(
        "--not-athlete",
        action="store_true",
        default=None,
        help="Mark the profile as non-athlete for derived metrics.",
    )
    parser.add_argument(
        "--pairing-flag",
        type=int,
        choices=(0, 1),
        default=0,
        help="Value used in the A6 login response (default: 0).",
    )
    parser.add_argument(
        "--send-live",
        action="store_true",
        help="Send the A6 live-data subscribe command after a successful handshake.",
    )
    parser.add_argument(
        "--jsonl",
        default=None,
        help="Optional JSONL output path for notifications and writes.",
    )
    return parser.parse_args()


def local_timezone_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds() // 60)


def a6_timezone_flag() -> int:
    return (local_timezone_minutes() // 15) + 48


def resolve_profile(args: argparse.Namespace) -> A6UserProfile | None:
    profile = A6UserProfile()

    if args.profile_json:
        profile_path = Path(args.profile_json).expanduser()
        with profile_path.open("r", encoding="utf-8") as handle:
            profile = A6UserProfile.from_mapping(json.load(handle))

    athlete_override: bool | None = None
    if args.athlete:
        athlete_override = True
    elif args.not_athlete:
        athlete_override = False

    profile = profile.merged(
        height_cm=args.height_cm,
        birthday=args.birthday,
        sex=args.sex,
        athlete=athlete_override,
    )

    if args.save_profile:
        save_path = Path(args.save_profile).expanduser()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("w", encoding="utf-8") as handle:
            json.dump(profile.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")

    return profile if profile.has_any_value() else None


def matches(
    device: BLEDevice,
    advertisement: AdvertisementData,
    *,
    address: str | None,
    name_filter: str | None,
) -> bool:
    if address and device.address.lower() != address.lower():
        return False

    if name_filter:
        needle = name_filter.lower()
        device_name = (device.name or "").lower()
        local_name = (advertisement.local_name or "").lower()
        if needle not in device_name and needle not in local_name:
            return False

    advertised = {uuid.lower() for uuid in advertisement.service_uuids or []}
    return bool(A6_SCAN_UUIDS.intersection(advertised))


async def find_candidate(args: argparse.Namespace) -> tuple[BLEDevice, AdvertisementData] | None:
    results = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    for device, advertisement in results.values():
        if matches(
            device,
            advertisement,
            address=args.address,
            name_filter=args.name,
        ):
            return device, advertisement
    return None


def append_jsonl(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def emit_record(payload: dict[str, Any], jsonl_path: Path | None) -> None:
    print(json.dumps(payload, sort_keys=True))
    append_jsonl(jsonl_path, payload)


def characteristic_properties(characteristic: Any) -> set[str]:
    return {property_name.lower() for property_name in characteristic.properties}


def command_code(payload: bytes) -> int | None:
    if len(payload) < 4 or payload[0] != 0x10:
        return None
    return int.from_bytes(payload[2:4], "big")


def build_ack_payload() -> bytes:
    return bytes((0x00, 0x01, 0x01))


def build_login_response(token: bytes, pairing_flag: int) -> bytes:
    return bytes((0x10, 0x0B, 0x00, 0x08, 0x01)) + token + bytes((pairing_flag, 0x02))


def build_initialization_response(request_arg: int) -> bytes:
    timestamp = int(time.time())
    return (
        bytes((0x10, 0x08, 0x00, 0x0A, request_arg & 0xFF))
        + timestamp.to_bytes(4, "big")
        + bytes((a6_timezone_flag() & 0xFF,))
    )


def build_subscribe_live() -> bytes:
    return bytes.fromhex("100448010001")


def sdk_impedance(raw_value: int) -> float:
    if raw_value <= 0:
        return 0.0
    if raw_value < 410:
        return 3.0
    return round((raw_value - 400) * 0.3, 2)


def decode_known_frame(payload: bytes) -> dict[str, Any]:
    decoded: dict[str, Any] = {"value_hex": payload.hex()}
    command = command_code(payload)
    if command is None:
        return decoded

    decoded["command"] = f"0x{command:04x}"

    if command == 0x0007:
        decoded["meaning"] = "login_request"
        decoded["challenge_hex"] = payload[4:10].hex() if len(payload) >= 10 else ""
        decoded["tail_hex"] = payload[10:].hex() if len(payload) > 10 else ""
    elif command == 0x0009:
        decoded["meaning"] = "initialization_request"
        decoded["request_arg"] = payload[4] if len(payload) > 4 else None
        decoded["tail_hex"] = payload[5:].hex() if len(payload) > 5 else ""
    elif command == 0x4802:
        decoded["meaning"] = "synchronize_response"
    else:
        decoded["meaning"] = "other_a6_command"

    return decoded


def decode_synchronize_response(
    payload: bytes,
    *,
    uses_a602_service: bool,
    profile: A6UserProfile | None,
) -> dict[str, Any]:
    decoded = decode_known_frame(payload)
    if command_code(payload) != 0x4802 or len(payload) < 18:
        return decoded

    frame_length = payload[1]
    measurement_index = int.from_bytes(payload[4:6], "big")
    flags = int.from_bytes(payload[6:10], "big")
    raw_weight = int.from_bytes(payload[10:12], "big")
    timestamp = int.from_bytes(payload[12:16], "big")
    raw_impedance = int.from_bytes(payload[16:18], "big") if frame_length >= 16 else None

    decimals = 3 if uses_a602_service else 2
    metric_weight = raw_weight / (10 ** decimals)
    unit_code = flags & 0x03

    decoded.update(
        {
            "measurement_index": measurement_index,
            "flags_hex": f"0x{flags:08x}",
            "raw_weight": raw_weight,
            "timestamp_utc": timestamp,
            "timestamp_iso": datetime.fromtimestamp(timestamp).astimezone().isoformat(),
        }
    )

    if unit_code == 1:
        decoded["unit"] = "lb"
        decoded["weight"] = round(metric_weight * 2.20462, 2)
        decoded["weight_metric_basis"] = round(metric_weight, 2)
    elif unit_code == 2:
        decoded["unit"] = "lb_oz"
        decoded["weight_total_oz"] = round(metric_weight * 35.27396, 2)
        decoded["weight_metric_basis"] = round(metric_weight, 2)
    else:
        decoded["unit"] = "kg"
        decoded["weight"] = round(metric_weight, 2)

    if raw_impedance is not None:
        decoded["raw_impedance"] = raw_impedance
        decoded["impedance_ohms"] = round(raw_impedance * 0.01, 2)
        decoded["sdk_impedance_metric"] = sdk_impedance(raw_impedance)
        if profile is not None:
            derived_metrics = compute_a6_derived_metrics(
                weight_kg=metric_weight,
                impedance_metric=decoded["sdk_impedance_metric"],
                profile=profile,
                measured_at=timestamp,
            )
            if derived_metrics:
                decoded["derived_metrics"] = derived_metrics
    elif profile is not None:
        derived_metrics = compute_a6_derived_metrics(
            weight_kg=metric_weight,
            impedance_metric=None,
            profile=profile,
            measured_at=timestamp,
        )
        if derived_metrics:
            decoded["derived_metrics"] = derived_metrics

    return decoded


async def read_if_present(
    client: BleakClient,
    characteristic: Any,
    label: str,
    jsonl_path: Path | None,
) -> None:
    properties = characteristic_properties(characteristic)
    if "read" not in properties:
        return

    try:
        value = await client.read_gatt_char(characteristic)
        emit_record(
            {"read": {"label": label, "uuid": characteristic.uuid, "value_hex": value.hex()}},
            jsonl_path,
        )
    except Exception as exc:  # pragma: no cover - hardware dependent
        emit_record(
            {
                "read_error": {
                    "label": label,
                    "uuid": characteristic.uuid,
                    "error": str(exc),
                }
            },
            jsonl_path,
        )


async def write_characteristic(
    client: BleakClient,
    characteristic: Any,
    payload: bytes,
    label: str,
    jsonl_path: Path | None,
) -> None:
    properties = characteristic_properties(characteristic)
    response = "write-without-response" not in properties
    await client.write_gatt_char(characteristic, payload, response=response)
    emit_record(
        {
            "write": {
                "label": label,
                "uuid": characteristic.uuid,
                "with_response": response,
                "value_hex": payload.hex(),
            }
        },
        jsonl_path,
    )


async def run(args: argparse.Namespace) -> int:
    profile = resolve_profile(args)
    candidate = await find_candidate(args)
    if candidate is None:
        print("No matching A6 BLE device found during scan.")
        return 1

    device, advertisement = candidate
    print(
        json.dumps(
            {
                "match": {
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
            },
            sort_keys=True,
        )
    )

    jsonl_path = Path(args.jsonl).expanduser() if args.jsonl else None

    if profile is not None:
        emit_record(
            {
                "profile": {
                    "value": profile.to_dict(),
                    "complete": profile.is_complete(),
                    "age_years": profile.age_on(),
                }
            },
            jsonl_path,
        )

    async with BleakClient(device) as client:
        characteristic_by_uuid: dict[str, Any] = {}
        for service in client.services:
            for characteristic in service.characteristics:
                characteristic_by_uuid[characteristic.uuid.lower()] = characteristic

        missing = [
            uuid
            for uuid in (
                A6_INDICATE_UUID,
                A6_NOTIFY_UUID,
                A6_WRITE_ACK_UUID,
                A6_WRITE_COMMAND_UUID,
                A6_NOTIFY_ACK_UUID,
            )
            if uuid not in characteristic_by_uuid
        ]
        if missing:
            print(json.dumps({"error": "Missing required A6 characteristics.", "missing": missing}, sort_keys=True))
            return 1

        if A6_INFO_FEATURE_UUID in characteristic_by_uuid:
            await read_if_present(
                client,
                characteristic_by_uuid[A6_INFO_FEATURE_UUID],
                "feature",
                jsonl_path,
            )
        if A6_INFO_VOLTAGE_UUID in characteristic_by_uuid:
            await read_if_present(
                client,
                characteristic_by_uuid[A6_INFO_VOLTAGE_UUID],
                "voltage",
                jsonl_path,
            )

        state = {
            "live_sent": False,
        }
        pending_tasks: set[asyncio.Task[None]] = set()
        protocol_lock = asyncio.Lock()
        uses_a602_service = "0000a602-0000-1000-8000-00805f9b34fb" in {
            uuid.lower() for uuid in advertisement.service_uuids or []
        }

        async def maybe_send_live() -> None:
            if not args.send_live or state["live_sent"]:
                return
            state["live_sent"] = True
            await asyncio.sleep(0.2)
            await write_characteristic(
                client,
                characteristic_by_uuid[A6_WRITE_COMMAND_UUID],
                build_subscribe_live(),
                "subscribe_live",
                jsonl_path,
            )

        async def handle_frame(characteristic_uuid: str, payload: bytes) -> None:
            decoded_payload = (
                decode_synchronize_response(
                    payload,
                    uses_a602_service=uses_a602_service,
                    profile=profile,
                )
                if command_code(payload) == 0x4802
                else decode_known_frame(payload)
            )
            event = {
                "notification": {
                    "time": time.time(),
                    "characteristic_uuid": characteristic_uuid,
                    **decoded_payload,
                }
            }
            emit_record(event, jsonl_path)

            if characteristic_uuid != A6_NOTIFY_UUID:
                return

            async with protocol_lock:
                command = command_code(payload)
                if command == 0x0007:
                    token = payload[4:10]
                    await write_characteristic(
                        client,
                        characteristic_by_uuid[A6_WRITE_ACK_UUID],
                        build_ack_payload(),
                        "ack_login_request",
                        jsonl_path,
                    )
                    if len(token) == 6:
                        await asyncio.sleep(0.2)
                        await write_characteristic(
                            client,
                            characteristic_by_uuid[A6_WRITE_COMMAND_UUID],
                            build_login_response(token, args.pairing_flag),
                            "login_response",
                            jsonl_path,
                        )
                elif command == 0x0009:
                    request_arg = payload[4] if len(payload) > 4 else 0
                    await write_characteristic(
                        client,
                        characteristic_by_uuid[A6_WRITE_ACK_UUID],
                        build_ack_payload(),
                        "ack_initialization_request",
                        jsonl_path,
                    )
                    await asyncio.sleep(0.2)
                    await write_characteristic(
                        client,
                        characteristic_by_uuid[A6_WRITE_COMMAND_UUID],
                        build_initialization_response(request_arg),
                        "initialization_response",
                        jsonl_path,
                    )
                    await maybe_send_live()
                elif command == 0x4802:
                    await write_characteristic(
                        client,
                        characteristic_by_uuid[A6_WRITE_ACK_UUID],
                        build_ack_payload(),
                        "ack_synchronize_response",
                        jsonl_path,
                    )

        def notification_handler(sender: Any, data: bytearray) -> None:
            sender_uuid = getattr(sender, "uuid", None)
            if sender_uuid is None:
                sender_uuid = str(sender)
            task = asyncio.create_task(handle_frame(sender_uuid.lower(), bytes(data)))
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)

        for uuid in (A6_INDICATE_UUID, A6_NOTIFY_UUID, A6_NOTIFY_ACK_UUID):
            characteristic = characteristic_by_uuid[uuid]
            await client.start_notify(characteristic, notification_handler)

        print(
            json.dumps(
                {
                    "subscribing": [
                        {
                            "uuid": characteristic_by_uuid[uuid].uuid,
                            "handle": characteristic_by_uuid[uuid].handle,
                            "properties": sorted(characteristic_properties(characteristic_by_uuid[uuid])),
                        }
                        for uuid in (A6_INDICATE_UUID, A6_NOTIFY_UUID, A6_NOTIFY_ACK_UUID)
                    ]
                },
                sort_keys=True,
            )
        )

        try:
            await asyncio.sleep(args.listen_seconds)
        finally:
            for uuid in (A6_INDICATE_UUID, A6_NOTIFY_UUID, A6_NOTIFY_ACK_UUID):
                try:
                    await client.stop_notify(characteristic_by_uuid[uuid])
                except Exception:  # pragma: no cover - hardware dependent
                    pass
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

    return 0


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
