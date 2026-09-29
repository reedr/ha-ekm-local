"""Gateway and per-meter communication sensors."""

from datetime import timedelta

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ekm_local.api import EkmConnectionError, parse_readings
from custom_components.ekm_local.const import DOMAIN

from .conftest import MAIN, TRACE, fresh_payload

MAIN_COMM = "binary_sensor.utility_meter_communicating"
TRACE_COMM = "binary_sensor.heat_trace_meter_communicating"
GATEWAY = "binary_sensor.ekm_push3_gateway_connected"


async def _setup(hass: HomeAssistant, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="EKM Push3", options=options or {},
        data={"host": "10.0.0.7", "api_key": "k",
              "meters": {MAIN: {"name": "Utility Meter"}, TRACE: {"name": "Heat Trace Meter"}}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll(hass, freezer, mock, payload=None, error=None):
    if error:
        mock.side_effect = error
    else:
        mock.side_effect = None
        mock.return_value = parse_readings(payload)
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_all_communicating(hass: HomeAssistant, mock_readings):
    await _setup(hass)
    assert hass.states.get(MAIN_COMM).state == STATE_ON
    assert hass.states.get(TRACE_COMM).state == STATE_ON
    assert hass.states.get(GATEWAY).state == STATE_ON


async def test_meter_loses_power_frozen_reading(hass: HomeAssistant, mock_readings, freezer):
    """Gateway keeps serving the last reading; after the threshold the meter is silent."""
    await _setup(hass)
    frozen = fresh_payload()
    for _ in range(2):  # 2 polls x 61 s > 90 s default
        await _poll(hass, freezer, mock_readings, frozen)
    assert hass.states.get(MAIN_COMM).state == STATE_OFF
    assert hass.states.get("sensor.utility_meter_power").state == STATE_UNAVAILABLE
    assert hass.states.get(GATEWAY).state == STATE_ON


async def test_meter_dropped_from_response(hass: HomeAssistant, mock_readings, freezer):
    await _setup(hass)
    payload = fresh_payload()
    del payload[MAIN]
    await _poll(hass, freezer, mock_readings, payload)
    assert hass.states.get(MAIN_COMM).state == STATE_OFF
    assert hass.states.get(TRACE_COMM).state == STATE_ON


async def test_gateway_down(hass: HomeAssistant, mock_readings, freezer):
    await _setup(hass)
    await _poll(hass, freezer, mock_readings, error=EkmConnectionError("down"))
    assert hass.states.get(GATEWAY).state == STATE_OFF
    # can't tell whether the meter is powered, so no claim either way
    assert hass.states.get(MAIN_COMM).state == STATE_UNAVAILABLE


async def test_custom_stale_threshold(hass: HomeAssistant, mock_readings, freezer):
    await _setup(hass, options={"scan_interval": 60, "stale_after": 30})
    await _poll(hass, freezer, mock_readings, fresh_payload())
    frozen = fresh_payload()
    mock_readings.return_value = parse_readings(frozen)
    freezer.tick(timedelta(seconds=40))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await _poll(hass, freezer, mock_readings, frozen)
    assert hass.states.get(MAIN_COMM).state == STATE_OFF
