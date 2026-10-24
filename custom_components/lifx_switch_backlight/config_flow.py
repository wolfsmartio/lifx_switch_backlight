"""Config flow: discover Switches on the LAN or add one by IP address."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import network
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE, CONF_HOST
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_SERIAL, DOMAIN
from .protocol import (
    LifxError,
    LifxSwitch,
    LifxUnsupportedError,
    SwitchInfo,
    discover_switches,
)


class LifxSwitchConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one LIFX Switch per config entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, SwitchInfo] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        broadcasts = [
            str(address)
            for address in await network.async_get_ipv4_broadcast_addresses(self.hass)
        ]
        try:
            switches = await discover_switches(broadcasts)
        except LifxError:
            switches = []
        configured = self._async_current_ids(include_ignore=False)
        self._discovered = {s.serial: s for s in switches if s.serial not in configured}
        if not self._discovered:
            return await self.async_step_manual()
        return self.async_show_menu(step_id="user", menu_options=["pick", "manual"])

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_create(self._discovered[user_input[CONF_DEVICE]])
        options = [
            SelectOptionDict(
                value=info.serial, label=f"{info.label or info.serial} ({info.host})"
            )
            for info in self._discovered.values()
        ]
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await LifxSwitch(user_input[CONF_HOST]).identify()
            except LifxUnsupportedError:
                errors["base"] = "not_a_switch"
            except LifxError:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_create(info)
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}), user_input
            ),
            errors=errors,
        )

    async def _async_create(self, info: SwitchInfo) -> ConfigFlowResult:
        await self.async_set_unique_id(info.serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: info.host})
        return self.async_create_entry(
            title=info.label or f"LIFX Switch {info.serial[-5:]}",
            data={CONF_HOST: info.host, CONF_SERIAL: info.serial},
        )
