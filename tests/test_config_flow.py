"""Config, reconfigure and options flows."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ekm_local.api import EkmAuthError
from custom_components.ekm_local.const import DOMAIN

from .conftest import MAIN, TRACE


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "10.0.0.7", "api_key": "k"}
    )


def _suggested(result) -> dict:
    return {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }


async def test_flow_without_adoption(hass: HomeAssistant, mock_readings):
    result = await _start(hass)
    assert result["step_id"] == "meter"
    assert result["description_placeholders"]["address"] == TRACE  # sorted
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Heat Trace Meter"})
    assert result["description_placeholders"]["address"] == MAIN
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Utility Meter"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "host": "10.0.0.7",
        "api_key": "k",
        "meters": {TRACE: {"name": "Heat Trace Meter"}, MAIN: {"name": "Utility Meter"}},
    }


async def test_flow_with_adoption(hass: HomeAssistant, mock_readings):
    registry = er.async_get(hass)
    for uid in ("rmr_power_total_watts", "rmr_power_reactive_watts", "rmr_power_total_energy",
                "rmr_power_l1_amps", "rmr_power_l2_amps",
                "heat_trace_power_total_watts", "heat_trace_power_reactive_watts",
                "heat_trace_power_total_energy"):
        registry.async_get_or_create("sensor", "rest", uid, suggested_object_id=uid)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Heat Trace Meter", "legacy_prefix": "heat_trace_power"}
    )
    assert result["step_id"] == "adopt"
    # v3 meter: no reactive power to map onto
    assert _suggested(result) == {
        "power": "sensor.heat_trace_power_total_watts",
        "energy": "sensor.heat_trace_power_total_energy",
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _suggested(result))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Utility Meter", "legacy_prefix": "sensor.rmr_power"}
    )
    main = _suggested(result)
    assert main == {
        "power": "sensor.rmr_power_total_watts",
        "reactive_power": "sensor.rmr_power_reactive_watts",
        "energy": "sensor.rmr_power_total_energy",
        "current_l1": "sensor.rmr_power_l1_amps",
        "current_l2": "sensor.rmr_power_l2_amps",
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], main)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["adopt"] == {
        TRACE: {"power": "sensor.heat_trace_power_total_watts", "energy": "sensor.heat_trace_power_total_energy"},
        MAIN: main,
    }


async def test_adopt_rejects_id_used_by_other_meter(hass: HomeAssistant, mock_readings):
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "A", "legacy_prefix": "sensor.x"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"power": "sensor.x_total_watts"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "B", "legacy_prefix": "sensor.x"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"power": "sensor.x_total_watts"})
    assert result["errors"] == {"power": "duplicate_entity_id"}


async def test_invalid_key(hass: HomeAssistant, mock_readings):
    mock_readings.side_effect = EkmAuthError("500")
    result = await _start(hass)
    assert result["errors"] == {"base": "invalid_key"}


async def test_already_configured(hass: HomeAssistant, mock_readings):
    MockConfigEntry(domain=DOMAIN, data={"host": "10.0.0.7", "api_key": "k"}).add_to_hass(hass)
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT


async def test_reconfigure_keeps_key(hass: HomeAssistant, mock_readings):
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "10.0.0.9", "api_key": "old",
                                                 "meters": {MAIN: {"name": "U"}}})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "10.0.0.7"})
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "10.0.0.7"
    assert entry.data["api_key"] == "old"
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_wrong_gateway(hass: HomeAssistant, mock_readings):
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "10.0.0.9", "api_key": "k",
                                                 "meters": {"999": {"name": "U"}}})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "10.0.0.7"})
    assert result["errors"] == {"base": "wrong_gateway"}
