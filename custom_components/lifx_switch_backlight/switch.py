"""Toggle for re-applying saved settings when the Switch drifts."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LifxSwitchConfigEntry, LifxSwitchCoordinator
from .entity import LifxSwitchEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifxSwitchConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([KeepAppliedSwitch(entry.runtime_data)])


class KeepAppliedSwitch(LifxSwitchEntity, SwitchEntity):
    """When on, settings changed outside Home Assistant are put back."""

    def __init__(self, coordinator: LifxSwitchCoordinator) -> None:
        super().__init__(coordinator, "keep_applied")

    @property
    def is_on(self) -> bool:
        return self.coordinator.keep_applied

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_keep_applied(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_keep_applied(False)
