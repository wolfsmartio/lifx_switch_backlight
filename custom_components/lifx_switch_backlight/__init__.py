"""LIFX Switch Backlight: control LIFX Switch backlight colors and haptics."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_SERIAL, DOMAIN
from .coordinator import LifxSwitchConfigEntry, LifxSwitchCoordinator
from .protocol import LifxSwitch
from .services import async_setup_services

PLATFORMS = [Platform.LIGHT, Platform.NUMBER, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LifxSwitchConfigEntry) -> bool:
    client = LifxSwitch(entry.data[CONF_HOST], entry.data[CONF_SERIAL])
    coordinator = LifxSwitchCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LifxSwitchConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
