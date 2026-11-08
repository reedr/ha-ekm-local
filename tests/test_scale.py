"""CT scale: one line's CT reads high by a known factor."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ekm_local.api import parse_readings

from .conftest import MAIN, TRACE, fresh_payload
from .test_correction import MAIN_KWH, TRACE_KWH, _f, _setup

L1_KWH, L2_KWH = 101733.0, 116560.0   # fixture line registers


async def _options(hass, entry, scale_meter="none", l1=1.0, l2=1.0, correct=("none", "none")):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 60, "stale_after": 90, "correct_meter": correct[0], "correct_by": correct[1],
         "scale_meter": scale_meter, "scale_l1": l1, "scale_l2": l2, "scale_l3": 1.0},
    )
    await hass.async_block_till_done()
    return result


async def _poll(hass, mock_readings, freezer, d1, d2, trace_kwh=TRACE_KWH, trace_watts=0):
    """Lines 1 and 2 use d1 / d2 kWh more than the fixture; the total register follows."""
    payload = fresh_payload()
    main = payload[MAIN][0]
    main["kWh_Ln_1"], main["kWh_Ln_2"] = L1_KWH + d1, L2_KWH + d2
    main["kWh_Tot"] = MAIN_KWH + d1 + d2
    payload[TRACE][0]["kWh_Tot"] = trace_kwh
    payload[TRACE][0]["RMS_Watts_Tot"] = trace_watts
    mock_readings.return_value = parse_readings(payload)
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_scale_lifecycle(hass: HomeAssistant, mock_readings, freezer):
    entry = await _setup(hass)
    result = await _options(hass, entry, MAIN, l1=0.5)
    assert result["type"] == "create_entry"
    assert entry.options["scale"] == {"1": 0.5}
    assert entry.options["scale_base"]["kwh"] == MAIN_KWH
    # line 1 halved; the total loses half of line 1's 4,320 W; energy continuous
    assert _f(hass, "sensor.utility_meter_current_l1") == 22.5
    assert _f(hass, "sensor.utility_meter_current_l2") == 67.5
    assert _f(hass, "sensor.utility_meter_power_l1") == 2160
    assert _f(hass, "sensor.utility_meter_power") == 12105 - 2160
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH
    attrs = hass.states.get("sensor.utility_meter_power").attributes
    assert attrs["ct_scale"] == "L1 x0.5"
    assert hass.states.get("sensor.utility_meter_current_l1").attributes["ct_scale"] == 0.5
    assert "ct_scale" not in hass.states.get("sensor.utility_meter_current_l2").attributes
    assert _f(hass, "sensor.heat_trace_meter_power") == 0   # other meter untouched

    # 20 kWh on line 1 counts as 10
    await _poll(hass, mock_readings, freezer, 20, 10)
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 20

    # new factor: continues from the scaled value
    await _options(hass, entry, MAIN, l1=0.25)
    assert entry.options["scale_base"]["kwh"] == MAIN_KWH + 20
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 20
    await _poll(hass, mock_readings, freezer, 28, 14)
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 26

    # off: back to raw registers, the 16 kWh removed so far stays removed
    await _options(hass, entry)
    assert "scale_meter" not in entry.options
    assert entry.options["correct_frozen"] == {MAIN: 16.0}
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 26
    assert _f(hass, "sensor.utility_meter_current_l1") == 45.0
    await _poll(hass, mock_readings, freezer, 30, 17)
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 31


async def test_scale_survives_reload(hass: HomeAssistant, mock_readings, freezer):
    entry = await _setup(hass)
    await _options(hass, entry, MAIN, l1=0.5)
    await _poll(hass, mock_readings, freezer, 20, 10)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _f(hass, "sensor.utility_meter_energy") == MAIN_KWH + 20


async def test_switch_from_subtraction_to_scale(hass: HomeAssistant, mock_readings, freezer):
    """Heat-trace subtraction off and CT scale on in one step: energy doesn't jump."""
    entry = await _setup(hass)
    await _options(hass, entry, correct=(MAIN, TRACE))
    await _poll(hass, mock_readings, freezer, 20, 10, trace_kwh=TRACE_KWH + 8)
    before = _f(hass, "sensor.utility_meter_energy")
    assert before == MAIN_KWH + 30 - 8
    await _options(hass, entry, MAIN, l1=0.5)
    assert "correct_meter" not in entry.options
    assert entry.options["correct_frozen"] == {MAIN: 8.0}
    assert _f(hass, "sensor.utility_meter_energy") == pytest.approx(before)
    await _poll(hass, mock_readings, freezer, 40, 20, trace_kwh=TRACE_KWH + 20)
    # +20 on line 1 (counts 10) and +10 on line 2; trace usage no longer subtracted
    assert _f(hass, "sensor.utility_meter_energy") == pytest.approx(before + 20)


async def test_all_ones_means_off(hass: HomeAssistant, mock_readings):
    entry = await _setup(hass)
    await _options(hass, entry, MAIN)
    assert "scale_meter" not in entry.options
    assert _f(hass, "sensor.utility_meter_current_l1") == 45.0
