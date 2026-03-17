"""Sensor platform for Weight Gurus BLE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL_A6
from .coordinator import WeightGurusDataUpdateCoordinator, WeightGurusMeasurement

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WeightGurusSensorDescription(SensorEntityDescription):
    """Describe a Weight Gurus sensor."""

    value_fn: Callable[[WeightGurusMeasurement], object | None]


SENSORS: tuple[WeightGurusSensorDescription, ...] = (
    WeightGurusSensorDescription(
        key="weight",
        translation_key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.weight,
    ),
    WeightGurusSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.battery_percent,
    ),
    WeightGurusSensorDescription(
        key="bmi",
        translation_key="bmi",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.derived_metrics.get("bmi"),
    ),
    WeightGurusSensorDescription(
        key="body_fat_percent",
        translation_key="body_fat_percent",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.derived_metrics.get("body_fat_percent"),
    ),
    WeightGurusSensorDescription(
        key="muscle_percent",
        translation_key="muscle_percent",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.derived_metrics.get("muscle_percent"),
    ),
    WeightGurusSensorDescription(
        key="body_water_percent",
        translation_key="body_water_percent",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.derived_metrics.get("body_water_percent"),
    ),
    WeightGurusSensorDescription(
        key="impedance_metric",
        translation_key="impedance_metric",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.sdk_impedance_metric,
    ),
    WeightGurusSensorDescription(
        key="measured_at",
        translation_key="measured_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.measured_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Weight Gurus sensors."""
    del hass
    coordinator: WeightGurusDataUpdateCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        WeightGurusSensorEntity(coordinator, entry, description) for description in SENSORS
    )


class WeightGurusSensorEntity(
    CoordinatorEntity[WeightGurusDataUpdateCoordinator],
    SensorEntity,
):
    """Representation of a Weight Gurus sensor."""

    entity_description: WeightGurusSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WeightGurusDataUpdateCoordinator,
        entry: ConfigEntry,
        description: WeightGurusSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> object | None:
        """Return the sensor value."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the sensor unit."""
        if self.entity_description.key == "weight":
            data = self.coordinator.data
            return None if data is None else data.unit
        return self.entity_description.native_unit_of_measurement

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return self.coordinator.data is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the shared scale device."""
        coordinator = self.coordinator
        return DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            manufacturer=MANUFACTURER,
            model=MODEL_A6,
            name=coordinator.name,
        )

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Expose raw values on the primary weight sensor."""
        if self.entity_description.key != "weight":
            return None

        data = self.coordinator.data
        if data is None:
            return None

        return {
            "weight_kg": data.weight_kg,
            "raw_weight": data.raw_weight,
            "raw_impedance": data.raw_impedance,
            "feature_flags": data.feature_flags,
        }
