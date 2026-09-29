"""readMeter client and parsing."""

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.ekm_local.api import (
    EkmAuthError,
    EkmConnectionError,
    EkmLocalClient,
    EkmResponseError,
    MeterReading,
    parse_readings,
)

from .conftest import MAIN, TRACE


async def test_get_readings(hass, aioclient_mock, payload):
    aioclient_mock.get("http://10.0.0.7/readMeter", json=payload)
    readings = await EkmLocalClient(async_get_clientsession(hass), "10.0.0.7", "k").async_get_readings()
    assert set(readings) == {MAIN, TRACE}
    assert readings[MAIN].number("RMS_Watts_Tot") == 12105
    assert aioclient_mock.mock_calls[0][1].query == {"key": "k", "cnt": "1"}


async def test_wrong_key_is_http_500(hass, aioclient_mock):
    aioclient_mock.get("http://10.0.0.7/readMeter", status=500, text="<html>")
    with pytest.raises(EkmAuthError):
        await EkmLocalClient(async_get_clientsession(hass), "10.0.0.7", "k").async_get_readings()


async def test_connection_error_hides_key(hass, aioclient_mock):
    aioclient_mock.get("http://10.0.0.7/readMeter", exc=TimeoutError)
    with pytest.raises(EkmConnectionError) as err:
        await EkmLocalClient(async_get_clientsession(hass), "10.0.0.7", "s3cret").async_get_readings()
    assert "s3cret" not in str(err.value)


def test_parse_rejects_empty():
    with pytest.raises(EkmResponseError):
        parse_readings({})
    with pytest.raises(EkmResponseError):
        parse_readings([1, 2])


def test_parse_takes_newest_read():
    readings = parse_readings(
        {"1": [{"Time_Stamp_UTC_ms": 2, "RMS_Watts_Tot": 5}, {"Time_Stamp_UTC_ms": 1, "RMS_Watts_Tot": 9}]}
    )
    assert readings["1"].number("RMS_Watts_Tot") == 5
    assert readings["1"].address == "1"


def test_power_factor_parsing():
    reading = MeterReading({"a": "0.83 C", "b": "1.00 L", "c": "bad", "d": 3})
    assert reading.power_factor("a") == 0.83
    assert reading.power_factor("b") == 1.0
    assert reading.power_factor("c") is None
    assert reading.power_factor("d") is None
