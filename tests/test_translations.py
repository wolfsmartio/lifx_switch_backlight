"""Every translation matches strings.json and loads in Home Assistant."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component

from custom_components.lifx_switch_backlight.const import DOMAIN

INTEGRATION = Path(__file__).parent.parent / "custom_components" / DOMAIN
TRANSLATIONS = sorted((INTEGRATION / "translations").glob("*.json"))


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


SOURCE = _flatten(json.loads((INTEGRATION / "strings.json").read_text()))


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda p: p.name)
def test_same_keys_and_placeholders(path: Path) -> None:
    translated = _flatten(json.loads(path.read_text()))
    assert translated.keys() == SOURCE.keys()
    for key, text in SOURCE.items():
        assert set(re.findall(r"{\w+}", translated[key])) == set(re.findall(r"{\w+}", text)), key


async def test_spanish_loads(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    strings = await async_get_translations(hass, "es", "entity", [DOMAIN])
    assert strings[f"component.{DOMAIN}.entity.switch.keep_applied.name"] == "Mantener ajustes aplicados"
