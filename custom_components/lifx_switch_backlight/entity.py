"""Base entity for LIFX Switch Backlight."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, DOMAIN
from .coordinator import LifxSwitchCoordinator


class LifxSwitchEntity(CoordinatorEntity[LifxSwitchCoordinator]):
    """An entity tied to one LIFX Switch."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LifxSwitchCoordinator, key: str) -> None:
        super().__init__(coordinator)
        serial = coordinator.config_entry.data[CONF_SERIAL]
        self._attr_translation_key = key
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            connections={(CONNECTION_NETWORK_MAC, serial)},
            manufacturer="LIFX",
            model="Switch",
            name=coordinator.config_entry.title,
        )
