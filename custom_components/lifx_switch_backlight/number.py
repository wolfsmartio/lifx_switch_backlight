"""Haptic feedback duration."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MAX_HAPTIC_MS
from .coordinator import LifxSwitchConfigEntry, LifxSwitchCoordinator
from .entity import LifxSwitchEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifxSwitchConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([HapticDurationNumber(entry.runtime_data)])


class HapticDurationNumber(LifxSwitchEntity, NumberEntity):
    """How long the button vibrates when pressed (0 disables haptics)."""

    _attr_native_min_value = 0
    _attr_native_max_value = MAX_HAPTIC_MS
    _attr_native_step = 10
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: LifxSwitchCoordinator) -> None:
        super().__init__(coordinator, "haptic_duration")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.haptic_duration_ms

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_apply(
            replace(self.coordinator.data, haptic_duration_ms=int(value))
        )
