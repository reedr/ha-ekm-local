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

# CT correction (v0.3.0): one meter over-counts another meter's load (e.g. a
# downstream feeder that also passes through the main meter's CT). The target's
# total power and energy have the source meter's subtracted. Energy stays
# continuous: only source usage since the correction began (CONF_CORRECT_BASE,
# the source's kWh then) is subtracted, and usage from earlier correction
# periods is kept in CONF_CORRECT_FROZEN {target address: kWh} for good.
CONF_CORRECT_METER = "correct_meter"
CONF_CORRECT_BY = "correct_by"
CONF_CORRECT_BASE = "correct_base"
CONF_CORRECT_FROZEN = "correct_frozen"
NO_CORRECTION = "none"

# CT scale (v0.4.0): one meter's CT on a line reads high or low by a known factor
# (for example, a CT with the wrong ratio). That line's current and power are
# multiplied by its factor, and the meter's total power and energy are rebuilt
# from the corrected lines. Energy stays continuous: CONF_SCALE_BASE holds the
# total kWh when the current factors took effect ("kwh") and each line's kWh
# register then ("lines"); usage since is summed line by line, times the factor.
# Turning scaling off moves the difference into CONF_CORRECT_FROZEN.
CONF_SCALE_METER = "scale_meter"
CONF_SCALE = "scale"
CONF_SCALE_BASE = "scale_base"
SCALE_LINES = (1, 2, 3)
MIN_SCALE = 0.1
MAX_SCALE = 5.0

# CT scale auto-detect (v0.5.0): apply a line's scale only while its CT is misreading, judged by
# the line's raw current against the other lines' average. The ratio is averaged over
# CONF_SCALE_DELAY seconds; the scale turns on at >= CONF_SCALE_ON and off at <= CONF_SCALE_OFF.
# Samples where the other lines carry under MIN_REF_AMPS are skipped. Energy then accumulates
# each poll's line kWh times the factor in effect, kept in a Store so restarts don't lose it.
CONF_SCALE_AUTO = "scale_auto"
CONF_SCALE_ON = "scale_on"
CONF_SCALE_OFF = "scale_off"
CONF_SCALE_DELAY = "scale_delay"
DEFAULT_SCALE_ON = 1.15
DEFAULT_SCALE_OFF = 1.05
DEFAULT_SCALE_DELAY = 600
MIN_SCALE_DELAY = 60
MAX_SCALE_DELAY = 3600
MIN_REF_AMPS = 5.0

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
