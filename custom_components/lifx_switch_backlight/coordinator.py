"""Polls a Switch's button config and keeps the saved settings applied."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SERIAL, DOMAIN, LOGGER, OPT_DESIRED, OPT_KEEP_APPLIED, SCAN_INTERVAL
from .protocol import ButtonConfig, LifxError, LifxSwitch, discover_hosts

type LifxSwitchConfigEntry = ConfigEntry[LifxSwitchCoordinator]


class LifxSwitchCoordinator(DataUpdateCoordinator[ButtonConfig]):
    """Reads the Switch's button config and re-applies saved settings on drift.

    The settings the user last chose are stored in the config entry options,
    so they survive restarts and can be pushed back after the Switch reboots
    or is changed from the LIFX app.
    """

    config_entry: LifxSwitchConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: LifxSwitchConfigEntry, client: LifxSwitch
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_SERIAL]}",
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._lock = asyncio.Lock()

    @property
    def desired(self) -> ButtonConfig | None:
        if data := self.config_entry.options.get(OPT_DESIRED):
            return ButtonConfig.from_dict(data)
        return None

    @property
    def keep_applied(self) -> bool:
        return self.config_entry.options.get(OPT_KEEP_APPLIED, True)

    def _save_options(self, **changes: Any) -> None:
        self.hass.config_entries.async_update_entry(
            self.config_entry, options={**self.config_entry.options, **changes}
        )

    async def _async_update_data(self) -> ButtonConfig:
        async with self._lock:
            try:
                current = await self.client.get_button_config()
            except LifxError as err:
                if not await self._async_rediscover():
                    raise UpdateFailed(f"Cannot reach {self.client.host}: {err}") from err
                try:
                    current = await self.client.get_button_config()
                except LifxError as err2:
                    raise UpdateFailed(f"Cannot reach {self.client.host}: {err2}") from err2

            desired = self.desired
            if desired is None:
                # First run: adopt whatever the Switch has now.
                self._save_options(**{OPT_DESIRED: current.as_dict()})
            elif self.keep_applied and current != desired:
                LOGGER.info(
                    "%s button config differs from saved settings; re-applying",
                    self.config_entry.title,
                )
                try:
                    await self.client.set_button_config(desired)
                except LifxError as err:
                    raise UpdateFailed(f"Cannot update {self.client.host}: {err}") from err
                current = desired
            return current

    async def _async_rediscover(self) -> bool:
        """Look for the Switch on a new IP address (e.g. after a DHCP change)."""
        broadcasts = [
            str(address)
            for address in await network.async_get_ipv4_broadcast_addresses(self.hass)
        ]
        try:
            hosts = await discover_hosts(broadcasts)
        except LifxError:
            return False
        host = hosts.get(self.config_entry.data[CONF_SERIAL])
        if host is None or host == self.client.host:
            return False
        LOGGER.info("%s moved to %s", self.config_entry.title, host)
        self.client.host = host
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, CONF_HOST: host}
        )
        return True

    async def async_apply(self, config: ButtonConfig) -> None:
        """Send new settings to the Switch and remember them."""
        async with self._lock:
            try:
                await self.client.set_button_config(config)
            except LifxError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="communication_error",
                    translation_placeholders={"host": self.client.host},
                ) from err
        self._save_options(**{OPT_DESIRED: config.as_dict()})
        self.async_set_updated_data(config)

    async def async_set_keep_applied(self, enabled: bool) -> None:
        self._save_options(**{OPT_KEEP_APPLIED: enabled})
        if enabled:
            await self.async_request_refresh()
        else:
            self.async_update_listeners()
