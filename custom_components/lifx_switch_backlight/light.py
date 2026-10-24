"""Backlight colors as light entities (one for the ON state, one for OFF)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MAX_KELVIN, MIN_KELVIN
from .coordinator import LifxSwitchConfigEntry, LifxSwitchCoordinator
from .entity import LifxSwitchEntity
from .protocol import UINT16_MAX, Hsbk


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifxSwitchConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(BacklightLight(coordinator, side) for side in ("on", "off"))


class BacklightLight(LifxSwitchEntity, LightEntity):
    """The backlight color shown when the button's load is on (or off).

    Turning this entity off sets that backlight's brightness to 0.
    """

    _attr_supported_color_modes = {ColorMode.HS, ColorMode.COLOR_TEMP}
    _attr_min_color_temp_kelvin = MIN_KELVIN
    _attr_max_color_temp_kelvin = MAX_KELVIN

    def __init__(self, coordinator: LifxSwitchCoordinator, side: str) -> None:
        super().__init__(coordinator, f"backlight_{side}")
        self._side = side
        self._last_brightness = UINT16_MAX

    @property
    def _hsbk(self) -> Hsbk:
        return getattr(self.coordinator.data, self._side)

    @property
    def is_on(self) -> bool:
        return self._hsbk.brightness > 0

    @property
    def brightness(self) -> int:
        return round(self._hsbk.brightness * 255 / UINT16_MAX)

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.COLOR_TEMP if self._hsbk.saturation == 0 else ColorMode.HS

    @property
    def hs_color(self) -> tuple[float, float]:
        return (self._hsbk.hue_deg, self._hsbk.saturation_pct)

    @property
    def color_temp_kelvin(self) -> int:
        return self._hsbk.kelvin

    async def async_turn_on(self, **kwargs: Any) -> None:
        hsbk = self._hsbk
        if ATTR_BRIGHTNESS in kwargs:
            brightness = round(kwargs[ATTR_BRIGHTNESS] * UINT16_MAX / 255)
        elif hsbk.brightness == 0:
            brightness = self._last_brightness
        else:
            brightness = hsbk.brightness
        hsbk = replace(hsbk, brightness=brightness)
        if ATTR_HS_COLOR in kwargs:
            hue, saturation = kwargs[ATTR_HS_COLOR]
            hsbk = hsbk.updated(hue_deg=hue, saturation_pct=saturation)
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            hsbk = replace(hsbk.updated(kelvin=kwargs[ATTR_COLOR_TEMP_KELVIN]), saturation=0)
        await self._async_set(hsbk)

    async def async_turn_off(self, **kwargs: Any) -> None:
        hsbk = self._hsbk
        if hsbk.brightness:
            self._last_brightness = hsbk.brightness
        await self._async_set(replace(hsbk, brightness=0))

    async def _async_set(self, hsbk: Hsbk) -> None:
        await self.coordinator.async_apply(
            replace(self.coordinator.data, **{self._side: hsbk})
        )
