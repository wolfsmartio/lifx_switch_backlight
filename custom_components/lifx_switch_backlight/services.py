"""The set_backlight action, a drop-in for the old lifx_control_trigger event."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN, MAX_HAPTIC_MS, MAX_KELVIN, MIN_KELVIN
from .coordinator import LifxSwitchCoordinator
from .protocol import ButtonConfig

SERVICE_SET_BACKLIGHT = "set_backlight"
ATTR_HAPTIC_DURATION_MS = "haptic_duration_ms"

_PERCENT = vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
_COLOR_FIELDS = {
    "hue": vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
    "saturation": _PERCENT,
    "brightness": _PERCENT,
    "kelvin": vol.All(vol.Coerce(int), vol.Range(min=MIN_KELVIN, max=MAX_KELVIN)),
}

SET_BACKLIGHT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_HAPTIC_DURATION_MS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_HAPTIC_MS)
        ),
        **{
            vol.Optional(f"{side}_{field}"): validator
            for side in ("on", "off")
            for field, validator in _COLOR_FIELDS.items()
        },
    }
)


def _coordinator_for_device(hass: HomeAssistant, device_id: str) -> LifxSwitchCoordinator:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if (
                entry is not None
                and entry.domain == DOMAIN
                and entry.state is ConfigEntryState.LOADED
            ):
                return entry.runtime_data
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="device_not_found",
        translation_placeholders={"device_id": device_id},
    )


def _merge(config: ButtonConfig, data: dict) -> ButtonConfig:
    """Apply only the fields given in the action call."""
    colors = {}
    for side in ("on", "off"):
        colors[side] = getattr(config, side).updated(
            hue_deg=data.get(f"{side}_hue"),
            saturation_pct=data.get(f"{side}_saturation"),
            brightness_pct=data.get(f"{side}_brightness"),
            kelvin=data.get(f"{side}_kelvin"),
        )
    return ButtonConfig(
        data.get(ATTR_HAPTIC_DURATION_MS, config.haptic_duration_ms), colors["on"], colors["off"]
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def async_set_backlight(call: ServiceCall) -> None:
        coordinators = [
            _coordinator_for_device(hass, device_id) for device_id in call.data[ATTR_DEVICE_ID]
        ]
        await asyncio.gather(
            *(c.async_apply(_merge(c.data, call.data)) for c in coordinators)
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_BACKLIGHT, async_set_backlight, schema=SET_BACKLIGHT_SCHEMA
    )
