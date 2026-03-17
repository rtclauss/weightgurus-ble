"""Weight Gurus BLE Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .const import DOMAIN, PLATFORMS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from .coordinator import WeightGurusDataUpdateCoordinator


@dataclass(slots=True)
class WeightGurusRuntimeData:
    """Runtime state kept per config entry."""

    address: str
    name: str
    coordinator: WeightGurusDataUpdateCoordinator


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload an entry after its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration from YAML (unused)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    from homeassistant.components import bluetooth
    from homeassistant.exceptions import ConfigEntryNotReady
    from .coordinator import (
        WeightGurusDataUpdateCoordinator,
        address_from_entry,
        name_from_entry,
        profile_from_entry,
    )

    if bluetooth.async_scanner_count(hass, connectable=True) == 0:
        raise ConfigEntryNotReady(
            "No connectable Bluetooth adapters are available for Weight Gurus BLE"
        )

    address = address_from_entry(entry)
    coordinator = WeightGurusDataUpdateCoordinator(
        hass,
        entry,
        address=address,
        name=name_from_entry(entry),
        profile=profile_from_entry(entry),
    )
    runtime_data = WeightGurusRuntimeData(
        address=address,
        name=coordinator.name,
        coordinator=coordinator,
    )
    entry.runtime_data = runtime_data
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime_data

    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is not None:
        runtime_data.coordinator.async_stop()

    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None:
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            hass.data.pop(DOMAIN, None)
    return True
