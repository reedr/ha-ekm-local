"""Constants for EKM Local."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "ekm_local"
MANUFACTURER = "EKM Metering"

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONF_ADOPT = "adopt"
CONF_LEGACY_PREFIX = "legacy_prefix"
CONF_METERS = "meters"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 600

REQUEST_TIMEOUT = 15

# note: the gateway keeps serving a meter's last reading after it stops
#       answering; older than this and the meter's entities go unavailable.
STALE_READING = timedelta(minutes=5)

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
