"""Taking over entity IDs from REST sensors."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ekm_local.const import DOMAIN

from .conftest import MAIN, TRACE


def _entry(hass, adopt) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "10.0.0.7", "api_key": "k", "adopt": adopt,
              "meters": {MAIN: {"name": "Utility Meter"}, TRACE: {"name": "Heat Trace Meter"}}},
    )
    entry.add_to_hass(hass)
    return entry


async def test_takes_over_rest_entities(hass: HomeAssistant, mock_readings):
    registry = er.async_get(hass)
    for uid in ("rmr_power_total_watts", "rmr_power_total_energy", "heat_trace_power_total_energy"):
        registry.async_get_or_create("sensor", "rest", uid, suggested_object_id=uid)
    entry = _entry(hass, {
        MAIN: {"power": "sensor.rmr_power_total_watts", "energy": "sensor.rmr_power_total_energy"},
        TRACE: {"energy": "sensor.heat_trace_power_total_energy"},
    })
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    moved = registry.async_get("sensor.rmr_power_total_energy")
    assert moved.platform == DOMAIN and moved.unique_id == f"{MAIN}_energy"
    assert float(hass.states.get("sensor.rmr_power_total_watts").state) == 12105
    assert float(hass.states.get("sensor.heat_trace_power_total_energy").state) == 62889.4
    assert "adopt" not in entry.data


async def test_waits_while_rest_still_loaded(hass: HomeAssistant, mock_readings):
    hass.states.async_set("sensor.rmr_power_total_watts", "12000")
    entry = _entry(hass, {MAIN: {"power": "sensor.rmr_power_total_watts"}})
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert "sensor.rmr_power_total_watts" in entry.reason

    hass.states.async_remove("sensor.rmr_power_total_watts")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert float(hass.states.get("sensor.rmr_power_total_watts").state) == 12105
