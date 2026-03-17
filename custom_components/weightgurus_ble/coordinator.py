"""Bluetooth-backed coordinator for Weight Gurus A6 scales."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
import time
from typing import TYPE_CHECKING, Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ADDRESS,
    CONF_NAME,
    DOMAIN,
)
from .metrics import A6UserProfile, compute_a6_derived_metrics

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.components.bluetooth import BluetoothChange, BluetoothServiceInfoBleak

_LOGGER = logging.getLogger(__name__)

_A6_NOTIFY_UUID = "0000a621-0000-1000-8000-00805f9b34fb"
_A6_INDICATE_UUID = "0000a620-0000-1000-8000-00805f9b34fb"
_A6_NOTIFY_ACK_UUID = "0000a625-0000-1000-8000-00805f9b34fb"
_A6_WRITE_ACK_UUID = "0000a622-0000-1000-8000-00805f9b34fb"
_A6_WRITE_COMMAND_UUID = "0000a624-0000-1000-8000-00805f9b34fb"
_A6_INFO_VOLTAGE_UUID = "0000a640-0000-1000-8000-00805f9b34fb"
_A6_INFO_FEATURE_UUID = "0000a641-0000-1000-8000-00805f9b34fb"
_CONNECT_TIMEOUT = 12.0
_MEASUREMENT_TIMEOUT = 15.0
_POLL_COOLDOWN_SECONDS = 20.0


def _local_timezone_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds() // 60)


def _a6_timezone_flag() -> int:
    return (_local_timezone_minutes() // 15) + 48


def _command_code(payload: bytes) -> int | None:
    if len(payload) < 4 or payload[0] != 0x10:
        return None
    return int.from_bytes(payload[2:4], "big")


def _build_ack_payload() -> bytes:
    return bytes((0x00, 0x01, 0x01))


def _build_login_response(token: bytes, pairing_flag: int = 0) -> bytes:
    return bytes((0x10, 0x0B, 0x00, 0x08, 0x01)) + token + bytes((pairing_flag, 0x02))


def _build_initialization_response(request_arg: int) -> bytes:
    timestamp = int(time.time())
    return (
        bytes((0x10, 0x08, 0x00, 0x0A, request_arg & 0xFF))
        + timestamp.to_bytes(4, "big")
        + bytes((_a6_timezone_flag() & 0xFF,))
    )


def _build_subscribe_live() -> bytes:
    return bytes.fromhex("100448010001")


def _sdk_impedance(raw_value: int) -> float:
    if raw_value <= 0:
        return 0.0
    if raw_value < 410:
        return 3.0
    return round((raw_value - 400) * 0.3, 2)


@dataclass(frozen=True, slots=True)
class WeightGurusMeasurement:
    """Parsed measurement payload for the A6 session."""

    weight: float
    unit: str
    weight_kg: float
    measured_at: datetime
    battery_percent: int | None = None
    feature_flags: int | None = None
    raw_weight: int | None = None
    raw_impedance: int | None = None
    sdk_impedance_metric: float | None = None
    derived_metrics: dict[str, float] = field(default_factory=dict)


class WeightGurusDataUpdateCoordinator(DataUpdateCoordinator[WeightGurusMeasurement | None]):
    """Coordinate short-lived A6 Bluetooth sessions driven by advertisements."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        address: str,
        name: str,
        profile: A6UserProfile | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{address}",
            update_interval=None,
            always_update=False,
        )
        self.entry = entry
        self.address = address
        self.name = name
        self.profile = profile
        self.last_service_info: BluetoothServiceInfoBleak | None = None
        self._last_poll_monotonic = 0.0
        self._cancel_discovery: Callable[[], None] | None = None

    @callback
    def async_start(self) -> Callable[[], None]:
        """Register Bluetooth discovery callbacks."""
        if self._cancel_discovery is not None:
            return self._cancel_discovery

        self.last_service_info = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=True
        )
        self._cancel_discovery = bluetooth.async_register_callback(
            self.hass,
            self._async_handle_discovery,
            {"address": self.address, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        return self._cancel_discovery

    @callback
    def async_stop(self) -> None:
        """Cancel Bluetooth callbacks."""
        if self._cancel_discovery is not None:
            self._cancel_discovery()
            self._cancel_discovery = None

    @callback
    def _async_handle_discovery(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """React to the scale becoming available."""
        del change
        self.last_service_info = service_info

        now = time.monotonic()
        if now - self._last_poll_monotonic < _POLL_COOLDOWN_SECONDS:
            return
        if self.hass.is_stopping:
            return

        self.hass.async_create_task(
            self.async_request_refresh(),
        )

    async def _async_update_data(self) -> WeightGurusMeasurement | None:
        """Run an A6 session and return the newest measurement."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass,
            self.address,
            connectable=True,
        )
        if ble_device is None:
            if self.data is not None:
                return self.data
            raise UpdateFailed(
                f"No connectable Bluetooth adapter can reach {self.address}"
            )

        try:
            measurement = await self._async_collect_measurement(ble_device)
        except Exception as err:
            if self.data is not None:
                _LOGGER.debug(
                    "A6 session failed for %s; keeping the last good measurement",
                    self.address,
                    exc_info=err,
                )
                return self.data
            raise UpdateFailed(str(err)) from err

        self._last_poll_monotonic = time.monotonic()
        return measurement

    async def _async_collect_measurement(
        self,
        ble_device: BLEDevice,
    ) -> WeightGurusMeasurement:
        """Connect to the scale, complete the handshake, and read one measurement."""
        measurement_future: asyncio.Future[WeightGurusMeasurement] = (
            asyncio.get_running_loop().create_future()
        )
        protocol_lock = asyncio.Lock()
        state = {"live_sent": False}

        async with BleakClient(ble_device, timeout=_CONNECT_TIMEOUT) as client:
            characteristic_by_uuid: dict[str, Any] = {}
            for service in client.services:
                for characteristic in service.characteristics:
                    characteristic_by_uuid[characteristic.uuid.lower()] = characteristic

            missing = [
                uuid
                for uuid in (
                    _A6_INDICATE_UUID,
                    _A6_NOTIFY_UUID,
                    _A6_NOTIFY_ACK_UUID,
                    _A6_WRITE_ACK_UUID,
                    _A6_WRITE_COMMAND_UUID,
                )
                if uuid not in characteristic_by_uuid
            ]
            if missing:
                raise UpdateFailed(
                    f"Missing required A6 characteristics for {self.address}: {', '.join(missing)}"
                )

            battery_percent = await self._async_read_percent(
                client, characteristic_by_uuid.get(_A6_INFO_VOLTAGE_UUID)
            )
            feature_flags = await self._async_read_uint(
                client, characteristic_by_uuid.get(_A6_INFO_FEATURE_UUID)
            )

            async def _write(uuid: str, payload: bytes) -> None:
                characteristic = characteristic_by_uuid[uuid]
                properties = {prop.lower() for prop in characteristic.properties}
                response = "write-without-response" not in properties
                await client.write_gatt_char(characteristic, payload, response=response)

            async def _maybe_send_live() -> None:
                if state["live_sent"]:
                    return
                state["live_sent"] = True
                await asyncio.sleep(0.2)
                await _write(_A6_WRITE_COMMAND_UUID, _build_subscribe_live())

            async def _handle_frame(characteristic_uuid: str, payload: bytes) -> None:
                if characteristic_uuid != _A6_NOTIFY_UUID:
                    return

                async with protocol_lock:
                    command = _command_code(payload)
                    if command == 0x0007:
                        token = payload[4:10]
                        await _write(_A6_WRITE_ACK_UUID, _build_ack_payload())
                        if len(token) == 6:
                            await asyncio.sleep(0.2)
                            await _write(
                                _A6_WRITE_COMMAND_UUID,
                                _build_login_response(token),
                            )
                    elif command == 0x0009:
                        request_arg = payload[4] if len(payload) > 4 else 0
                        await _write(_A6_WRITE_ACK_UUID, _build_ack_payload())
                        await asyncio.sleep(0.2)
                        await _write(
                            _A6_WRITE_COMMAND_UUID,
                            _build_initialization_response(request_arg),
                        )
                        await _maybe_send_live()
                    elif command == 0x4802:
                        await _write(_A6_WRITE_ACK_UUID, _build_ack_payload())
                        if not measurement_future.done():
                            measurement_future.set_result(
                                self._decode_measurement(
                                    payload,
                                    battery_percent=battery_percent,
                                    feature_flags=feature_flags,
                                )
                            )

            def _notification_handler(sender: Any, data: bytearray) -> None:
                sender_uuid = getattr(sender, "uuid", None)
                if sender_uuid is None:
                    sender_uuid = str(sender)
                self.hass.async_create_task(
                    _handle_frame(sender_uuid.lower(), bytes(data)),
                )

            for uuid in (_A6_INDICATE_UUID, _A6_NOTIFY_UUID, _A6_NOTIFY_ACK_UUID):
                await client.start_notify(characteristic_by_uuid[uuid], _notification_handler)

            try:
                return await asyncio.wait_for(measurement_future, timeout=_MEASUREMENT_TIMEOUT)
            finally:
                for uuid in (_A6_INDICATE_UUID, _A6_NOTIFY_UUID, _A6_NOTIFY_ACK_UUID):
                    try:
                        await client.stop_notify(characteristic_by_uuid[uuid])
                    except Exception:
                        pass

    async def _async_read_percent(
        self,
        client: BleakClient,
        characteristic: Any | None,
    ) -> int | None:
        """Read a single-byte percent value."""
        if characteristic is None:
            return None
        properties = {prop.lower() for prop in characteristic.properties}
        if "read" not in properties:
            return None

        try:
            payload = await client.read_gatt_char(characteristic)
        except Exception:
            return None

        return payload[0] if payload else None

    async def _async_read_uint(
        self,
        client: BleakClient,
        characteristic: Any | None,
    ) -> int | None:
        """Read a big-endian unsigned integer."""
        if characteristic is None:
            return None
        properties = {prop.lower() for prop in characteristic.properties}
        if "read" not in properties:
            return None

        try:
            payload = await client.read_gatt_char(characteristic)
        except Exception:
            return None

        return int.from_bytes(payload, "big") if payload else None

    def _decode_measurement(
        self,
        payload: bytes,
        *,
        battery_percent: int | None,
        feature_flags: int | None,
    ) -> WeightGurusMeasurement:
        """Parse a 0x4802 measurement payload."""
        if _command_code(payload) != 0x4802 or len(payload) < 18:
            raise UpdateFailed(f"Unexpected A6 measurement payload: {payload.hex()}")

        flags = int.from_bytes(payload[6:10], "big")
        raw_weight = int.from_bytes(payload[10:12], "big")
        timestamp = int.from_bytes(payload[12:16], "big")
        raw_impedance = int.from_bytes(payload[16:18], "big")
        measured_at = datetime.fromtimestamp(timestamp).astimezone()

        weight_kg = raw_weight / 100.0
        unit_code = flags & 0x03
        if unit_code == 1:
            unit = "lb"
            weight = round(weight_kg * 2.20462, 2)
        elif unit_code == 2:
            unit = "oz"
            weight = round(weight_kg * 35.27396, 2)
        else:
            unit = "kg"
            weight = round(weight_kg, 2)

        sdk_impedance_metric = _sdk_impedance(raw_impedance)
        derived_metrics: dict[str, float] = {}
        if self.profile is not None:
            derived_metrics = compute_a6_derived_metrics(
                weight_kg=weight_kg,
                impedance_metric=sdk_impedance_metric,
                profile=self.profile,
                measured_at=measured_at,
            )

        return WeightGurusMeasurement(
            weight=weight,
            unit=unit,
            weight_kg=round(weight_kg, 2),
            measured_at=measured_at,
            battery_percent=battery_percent,
            feature_flags=feature_flags,
            raw_weight=raw_weight,
            raw_impedance=raw_impedance,
            sdk_impedance_metric=sdk_impedance_metric,
            derived_metrics=derived_metrics,
        )


def profile_from_entry(entry: ConfigEntry) -> A6UserProfile | None:
    """Parse the saved profile options for a config entry."""
    if not entry.options:
        return None

    try:
        profile = A6UserProfile.from_mapping(entry.options)
    except ValueError:
        return None
    return profile if profile.has_any_value() else None


def address_from_entry(entry: ConfigEntry) -> str:
    """Return the configured Bluetooth address."""
    return str(entry.unique_id or entry.data[CONF_ADDRESS])


def name_from_entry(entry: ConfigEntry) -> str:
    """Return the configured display name."""
    return str(entry.data.get(CONF_NAME) or address_from_entry(entry))
