"""Constants for EKM Local."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ekm_local"
MANUFACTURER = "EKM Metering"

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONF_ADOPT = "adopt"
CONF_LEGACY_PREFIX = "legacy_prefix"
CONF_METERS = "meters"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STALE_AFTER = "stale_after"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 600

REQUEST_TIMEOUT = 15

# note: the gateway keeps serving a meter's last reading after it stops
#       answering (e.g. the meter lost power); older than this and the meter
#       counts as not communicating and its entities go unavailable.
DEFAULT_STALE_AFTER = 90
MIN_STALE_AFTER = 15
MAX_STALE_AFTER = 900

# Legacy-entity adoption: sensor key -> suffix appended to the legacy prefix
# (matches REST setups like sensor.x_total_watts, sensor.x_l1_amps, ...).
ADOPTABLE_SUFFIXES: dict[str, str] = {
    "power": "_total_watts",
    "reactive_power": "_reactive_watts",
    "energy": "_total_energy",
    "current_l1": "_l1_amps",
    "current_l2": "_l2_amps",
    "current_l3": "_l3_amps",
    "voltage_l1": "_l1_volts",
    "voltage_l2": "_l2_volts",
    "frequency": "_frequency",
}
