"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.lifx_switch_backlight.protocol import ButtonConfig, Hsbk, SwitchInfo

SERIAL = "d0:73:d5:12:34:56"
HOST = "192.168.1.50"
INITIAL = ButtonConfig(30, Hsbk.from_user(240, 100, 100, 3500), Hsbk.from_user(0, 100, 100, 2700))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_switch() -> Generator[AsyncMock]:
    """A fake LifxSwitch that stores the last config it was sent."""
    client = AsyncMock()
    client.host = HOST
    client.serial = SERIAL
    client.state = INITIAL

    async def get_config():
        return client.state

    async def set_config(config):
        client.state = config

    client.get_button_config.side_effect = get_config
    client.set_button_config.side_effect = set_config
    client.identify.return_value = SwitchInfo(HOST, SERIAL, "Kitchen", INITIAL)
    with (
        patch("custom_components.lifx_switch_backlight.LifxSwitch", return_value=client),
        patch("custom_components.lifx_switch_backlight.config_flow.LifxSwitch", return_value=client),
    ):
        yield client
