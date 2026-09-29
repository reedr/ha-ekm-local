"""Entities created per meter."""

from datetime import timedelta

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ekm_local.api import EkmConnectionError, parse_readings
from custom_components.ekm_local.const import DOMAIN

from .conftest import MAIN, TRACE, fresh_payload


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="EKM Push3",
        data={"host": "10.0.0.7", "api_key": "k",
              "meters": {MAIN: {"name": "Utility Meter"}, TRACE: {"name": "Heat Trace Meter"}}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _f(hass, entity_id) -> float:
    return float(hass.states.get(entity_id).state)


async def test_v4_meter(hass: HomeAssistant, mock_readings):
    await _setup(hass)
    assert _f(hass, "sensor.utility_meter_power") == 12105
    assert _f(hass, "sensor.utility_meter_power_l1") == 4320
    assert _f(hass, "sensor.utility_meter_reactive_power") == 4965
    assert _f(hass, "sensor.utility_meter_current_l2") == 67.5
    assert _f(hass, "sensor.utility_meter_voltage_l1") == 123.8
    assert _f(hass, "sensor.utility_meter_power_factor_l1") == 0.83
    assert _f(hass, "sensor.utility_meter_frequency") == 60.05
    energy = hass.states.get("sensor.utility_meter_energy")
    assert float(energy.state) == 218322.0
    assert energy.attributes["state_class"] == "total_increasing"
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert hass.states.get("sensor.utility_meter_read_reliability").state == "100.0"


async def test_v3_meter_has_no_reactive_or_frequency(hass: HomeAssistant, mock_readings):
    await _setup(hass)
    assert _f(hass, "sensor.heat_trace_meter_energy") == 62889.4
    registry = er.async_get(hass)
    assert registry.async_get("sensor.heat_trace_meter_reactive_power") is None
    assert registry.async_get("sensor.heat_trace_meter_frequency") is None


async def test_line3_and_extras_disabled(hass: HomeAssistant, mock_readings):
    await _setup(hass)
    registry = er.async_get(hass)
    for entity_id in (
        "sensor.utility_meter_power_l3",
        "sensor.utility_meter_current_l3",
        "sensor.utility_meter_energy_tariff_1",
        "sensor.utility_meter_reactive_energy",
        "sensor.utility_meter_pulse_count_1",
        "sensor.utility_meter_last_reading",
    ):
        entry = registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION, entity_id


async def test_devices(hass: HomeAssistant, mock_readings):
    entry = await _setup(hass)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    by_name = {d.name: d for d in devices}
    assert set(by_name) == {"EKM Push3 gateway", "Utility Meter", "Heat Trace Meter"}
    assert by_name["Utility Meter"].via_device_id == by_name["EKM Push3 gateway"].id
    assert by_name["Utility Meter"].serial_number == MAIN


async def test_failure_is_immediately_unavailable(hass: HomeAssistant, mock_readings, freezer):
    await _setup(hass)
    mock_readings.side_effect = EkmConnectionError("down")
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.utility_meter_power").state == STATE_UNAVAILABLE


async def test_stale_meter_goes_unavailable(hass: HomeAssistant, mock_readings, payload):
    payload[TRACE][0]["Time_Stamp_UTC_ms"] -= 2 * 60 * 1000
    mock_readings.return_value = parse_readings(payload)
    await _setup(hass)
    assert hass.states.get("sensor.heat_trace_meter_power").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.utility_meter_power").state != STATE_UNAVAILABLE


async def test_meter_added_later(hass: HomeAssistant, mock_readings, freezer):
    only_main = fresh_payload()
    del only_main[TRACE]
    mock_readings.return_value = parse_readings(only_main)
    await _setup(hass)
    assert hass.states.get("sensor.heat_trace_meter_power") is None
    mock_readings.return_value = parse_readings(fresh_payload())
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.heat_trace_meter_power") is not None
