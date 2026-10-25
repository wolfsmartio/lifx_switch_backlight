"""Integration tests with a mocked Switch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from custom_components.lifx_switch_backlight.const import (
    CONF_SERIAL,
    DOMAIN,
    OPT_DESIRED,
    SCAN_INTERVAL,
)
from custom_components.lifx_switch_backlight.protocol import (
    ButtonConfig,
    Hsbk,
    LifxTimeoutError,
    LifxUnsupportedError,
    SwitchInfo,
)

from .conftest import HOST, INITIAL, SERIAL

ON_LIGHT = "light.kitchen_backlight_when_on"
OFF_LIGHT = "light.kitchen_backlight_when_off"
HAPTIC = "number.kitchen_haptic_feedback"
KEEP = "switch.kitchen_keep_settings_applied"


async def _setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen",
        unique_id=SERIAL,
        data={CONF_HOST: HOST, CONF_SERIAL: SERIAL},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_flow_discovered(hass: HomeAssistant, mock_switch: AsyncMock) -> None:
    info = SwitchInfo(HOST, SERIAL, "Kitchen", INITIAL)
    with (
        patch(
            "custom_components.lifx_switch_backlight.config_flow.discover_switches",
            return_value=[info],
        ),
        patch("custom_components.lifx_switch_backlight.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.MENU
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "pick"}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device": SERIAL}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen"
    assert result["data"] == {CONF_HOST: HOST, CONF_SERIAL: SERIAL}


@pytest.mark.parametrize(
    ("error", "key"),
    [(LifxUnsupportedError("light"), "not_a_switch"), (LifxTimeoutError("t"), "cannot_connect")],
)
async def test_flow_manual(
    hass: HomeAssistant, mock_switch: AsyncMock, error: Exception, key: str
) -> None:
    with (
        patch(
            "custom_components.lifx_switch_backlight.config_flow.discover_switches",
            return_value=[],
        ),
        patch("custom_components.lifx_switch_backlight.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["step_id"] == "manual"
        mock_switch.identify.side_effect = error
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST}
        )
        assert result["errors"] == {"base": key}
        mock_switch.identify.side_effect = None
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_entities_reflect_switch(hass: HomeAssistant, mock_switch: AsyncMock) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    # First refresh adopts the Switch's current settings.
    assert entry.options[OPT_DESIRED] == INITIAL.as_dict()

    on = hass.states.get(ON_LIGHT)
    assert on.state == "on"
    assert on.attributes["color_mode"] == "hs"
    assert round(on.attributes["hs_color"][0]) == 240
    assert hass.states.get(HAPTIC).state == "30"
    assert hass.states.get(KEEP).state == "on"


async def test_light_and_number_write(hass: HomeAssistant, mock_switch: AsyncMock) -> None:
    entry = await _setup(hass)

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": OFF_LIGHT, "color_temp_kelvin": 4000, "brightness": 128},
        blocking=True,
    )
    off = mock_switch.state.off
    assert (off.saturation, off.kelvin, off.brightness) == (0, 4000, round(128 * 65535 / 255))
    assert hass.states.get(OFF_LIGHT).attributes["color_mode"] == "color_temp"

    await hass.services.async_call("light", "turn_off", {"entity_id": ON_LIGHT}, blocking=True)
    assert mock_switch.state.on.brightness == 0
    assert hass.states.get(ON_LIGHT).state == "off"
    await hass.services.async_call("light", "turn_on", {"entity_id": ON_LIGHT}, blocking=True)
    assert mock_switch.state.on == INITIAL.on  # previous brightness restored

    await hass.services.async_call(
        "number", "set_value", {"entity_id": HAPTIC, "value": 60}, blocking=True
    )
    assert mock_switch.state.haptic_duration_ms == 60
    assert ButtonConfig.from_dict(entry.options[OPT_DESIRED]) == mock_switch.state


async def test_set_backlight_action(hass: HomeAssistant, mock_switch: AsyncMock) -> None:
    entry = await _setup(hass)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, SERIAL), entry.entry_id)
    await hass.services.async_call(
        DOMAIN,
        "set_backlight",
        {"device_id": device.id, "haptic_duration_ms": 0, "on_hue": 120, "off_brightness": 10},
        blocking=True,
    )
    state = mock_switch.state
    assert state.haptic_duration_ms == 0
    assert state.on == INITIAL.on.updated(hue_deg=120)
    assert state.off == INITIAL.off.updated(brightness_pct=10)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "set_backlight", {"device_id": "nope", "on_hue": 1}, blocking=True
        )

async def test_set_backlight_color_picker_and_white(
    hass: HomeAssistant, mock_switch: AsyncMock
) -> None:
    entry = await _setup(hass)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, SERIAL), entry.entry_id)
    await hass.services.async_call(
        DOMAIN,
        "set_backlight",
        {
            "device_id": device.id,
            "on_rgb_color": [0, 0, 255],
            "off_color_temp_kelvin": 2700,
        },
        blocking=True,
    )
    state = mock_switch.state
    assert state.on == INITIAL.on.updated(hue_deg=240, saturation_pct=100)
    assert state.off == INITIAL.off.updated(saturation_pct=0, kelvin=2700)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_backlight",
            {"device_id": device.id, "on_rgb_color": [0, 0, 255], "on_color_temp_kelvin": 2700},
            blocking=True,
        )



async def test_drift_is_reapplied(
    hass: HomeAssistant, mock_switch: AsyncMock, freezer: FrozenDateTimeFactory
) -> None:
    await _setup(hass)
    mock_switch.state = ButtonConfig(30, Hsbk(0, 0, 0, 3500), Hsbk(0, 0, 0, 3500))  # e.g. reset
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_switch.state == INITIAL

    await hass.services.async_call("switch", "turn_off", {"entity_id": KEEP}, blocking=True)
    drifted = ButtonConfig(30, Hsbk(0, 0, 0, 3500), Hsbk(0, 0, 0, 3500))
    mock_switch.state = drifted
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_switch.state == drifted
    assert hass.states.get(ON_LIGHT).state == "off"


async def test_unreachable_then_moved(hass: HomeAssistant, mock_switch: AsyncMock) -> None:
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LifxTimeoutError("gone")
        return mock_switch.state

    mock_switch.get_button_config.side_effect = flaky
    with patch(
        "custom_components.lifx_switch_backlight.coordinator.discover_hosts",
        return_value={SERIAL: "192.168.1.77"},
    ):
        entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_HOST] == "192.168.1.77"
    assert mock_switch.host == "192.168.1.77"
