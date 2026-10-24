"""Brand images ship with the integration and are served by Home Assistant."""

from __future__ import annotations

from pathlib import Path

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.lifx_switch_backlight.const import DOMAIN

BRAND_DIR = Path(__file__).parent.parent / "custom_components" / DOMAIN / "brand"


@pytest.mark.parametrize(
    "image",
    [
        "icon.png",
        "icon@2x.png",
        "logo.png",
        "logo@2x.png",
        "dark_icon.png",
        "dark_icon@2x.png",
        "dark_logo.png",
        "dark_logo@2x.png",
    ],
)
async def test_brand_image_served_locally(hass: HomeAssistant, hass_client, image: str) -> None:
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    resp = await client.get(f"/api/brands/integration/{DOMAIN}/{image}?placeholder=no")
    assert resp.status == 200
    assert resp.content_type == "image/png"
    assert await resp.read() == (BRAND_DIR / image).read_bytes()
