"""Repository metadata that HACS and hassfest check before publishing."""

from __future__ import annotations

import json
from pathlib import Path
import re
import struct

from awesomeversion import AwesomeVersion

from custom_components.lifx_switch_backlight.const import DOMAIN

ROOT = Path(__file__).parent.parent
INTEGRATION = ROOT / "custom_components" / DOMAIN
HACS = json.loads((ROOT / "hacs.json").read_text())
MANIFEST = json.loads((INTEGRATION / "manifest.json").read_text())

# Keys allowed by HACS's hacs.json schema (it rejects anything else).
HACS_KEYS = {
    "content_in_root",
    "country",
    "filename",
    "hacs",
    "hide_default_branch",
    "homeassistant",
    "name",
    "persistent_directory",
    "render_readme",
    "zip_release",
}


def test_single_integration_in_custom_components() -> None:
    folders = [p.name for p in (ROOT / "custom_components").iterdir() if p.is_dir() and p.name != "__pycache__"]
    assert folders == [DOMAIN]


def test_hacs_json() -> None:
    assert HACS["name"] == MANIFEST["name"]
    assert set(HACS) <= HACS_KEYS
    assert HACS["country"] == ["US", "CA"]
    assert all(re.fullmatch(r"[A-Z]{2}", code) for code in HACS["country"])
    assert AwesomeVersion(HACS["homeassistant"]).valid


def test_manifest() -> None:
    assert MANIFEST["domain"] == DOMAIN == INTEGRATION.name
    # hassfest wants domain and name first, then the rest sorted.
    keys = list(MANIFEST)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])
    assert re.fullmatch(r"\d+\.\d+\.\d+", MANIFEST["version"])
    assert MANIFEST["codeowners"] == ["@wolfsmartio"]
    repo = "https://github.com/wolfsmartio/lifx_switch_backlight"
    assert MANIFEST["documentation"] == repo
    assert MANIFEST["issue_tracker"] == f"{repo}/issues"


def test_readme_states_minimum_version() -> None:
    readme = (ROOT / "README.md").read_text()
    assert f"**Home Assistant lowest supported version:** {HACS['homeassistant']}" in readme


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    return struct.unpack(">II", data[16:24])


def test_brand_image_sizes() -> None:
    brand = INTEGRATION / "brand"
    for prefix in ("", "dark_"):
        assert _png_size(brand / f"{prefix}icon.png") == (256, 256)
        assert _png_size(brand / f"{prefix}icon@2x.png") == (512, 512)
        assert _png_size(brand / f"{prefix}logo.png")[1] == 128
        assert _png_size(brand / f"{prefix}logo@2x.png")[1] == 256


def test_license_is_mit() -> None:
    license_text = (ROOT / "LICENSE").read_text()
    assert license_text.startswith("MIT License\n")
    assert "WolfSmart.IO LLC" in license_text
