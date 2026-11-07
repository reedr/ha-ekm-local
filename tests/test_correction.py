"""CT correction: one meter's total power / energy less another meter's."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ekm_local.api import parse_readings
from custom_components.ekm_local.const import DOMAIN

from .conftest import MAIN, TRACE, fresh_payload

MAIN_KWH, TRACE_KWH = 218322.0, 62889.4


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "10.0.0.7", "api_key": "k",
              "meters": {MAIN: {"name": "Utility Meter"}, TRACE: {"name": "Heat Trace Meter"}}},
        options={"scan_interval": 60, "stale_after": 90},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _options(hass, entry, target, source):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 60, "stale_after": 90, "correct_meter": target, "correct_by": source},
    )
    await hass.async_block_till_done()
    return result


async def _poll(hass, mock_readings, freezer, trace_watts, main_kwh, trace_kwh):
    payload = fresh_payload()
    payload[TRACE][0]["RMS_Watts_Tot"] = trace_watts
    payload[MAIN][0]["kWh_Tot"] = main_kwh
    payload[TRACE][0]["kWh_Tot"] = trace_kwh
    mock_readings.return_value = parse_readings(payload)
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _f(hass, entity_id) -> float:
    return float(hass.states.get(entity_id).state)


async def test_correction_lifecycle(hass: HomeAssistant, mock_readings, freezer):
    entry = await _setup(hass)
    result = await _options(hass, entry, MAIN, TRACE)
    assert result["type"] == "create_entry"
    assert entry.options["correct_base"] == TRACE_KWH
    # energy is continuous at the switch
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH

    # heat trace draws 3 kW and uses 10 kWh; the main meter counts it twice
    await _poll(hass, mock_readings, freezer, 3000, MAIN_KWH + 25, TRACE_KWH + 10)
    assert _f(hass, "sensor.utility_meter_power") == 12105 - 3000
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 15
    assert hass.states.get("sensor.utility_meter_energy").attributes["corrected_by"] == "Heat Trace Meter"
    assert _f(hass, "sensor.heat_trace_meter_power") == 3000   # source untouched

    # turn it off: the 10 kWh stays subtracted, power goes back to raw
    await _options(hass, entry, "none", "none")
    assert entry.options["correct_frozen"] == {MAIN: 10.0}
    assert "correct_meter" not in entry.options
    await _poll(hass, mock_readings, freezer, 3000, MAIN_KWH + 30, TRACE_KWH + 12)
    assert _f(hass, "sensor.utility_meter_power") == 12105
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 20

    # back on: base restarts from the trace meter's current reading
    await _options(hass, entry, MAIN, TRACE)
    assert entry.options["correct_base"] == TRACE_KWH + 12
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 20


async def test_energy_never_steps_back(hass: HomeAssistant, mock_readings, freezer):
    entry = await _setup(hass)
    await _options(hass, entry, MAIN, TRACE)
    await _poll(hass, mock_readings, freezer, 0, MAIN_KWH + 0.1, TRACE_KWH + 0.3)
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH


async def test_power_not_negative(hass: HomeAssistant, mock_readings, freezer):
    entry = await _setup(hass)
    await _options(hass, entry, MAIN, TRACE)
    await _poll(hass, mock_readings, freezer, 20000, MAIN_KWH, TRACE_KWH)
    assert _f(hass, "sensor.utility_meter_power") == 0


async def test_same_meter_rejected(hass: HomeAssistant, mock_readings):
    entry = await _setup(hass)
    result = await _options(hass, entry, MAIN, MAIN)
    assert result["errors"] == {"base": "correct_by_invalid"}
