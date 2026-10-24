"""Constants for LIFX Switch Backlight."""

from datetime import timedelta
import logging

DOMAIN = "lifx_switch_backlight"
LOGGER = logging.getLogger(__package__)

CONF_SERIAL = "serial"

# Config entry options
OPT_DESIRED = "desired"
OPT_KEEP_APPLIED = "keep_applied"

SCAN_INTERVAL = timedelta(seconds=60)

MIN_KELVIN = 1500
MAX_KELVIN = 9000
MAX_HAPTIC_MS = 500
