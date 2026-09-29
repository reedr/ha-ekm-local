"""Fixtures for EKM Local tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.ekm_local.api import parse_readings

pytest_plugins = ("pytest_homeassistant_custom_component",)

FIXTURES = Path(__file__).parent / "fixtures"
MAIN = "000300000001"  # v4 meter
TRACE = "000000000002"  # v3 meter


def fresh_payload() -> dict:
    """The fixture with reading timestamps moved to now."""
    payload = json.loads((FIXTURES / "gateway.json").read_text())
    now_ms = int(time.time() * 1000)
    for reads in payload.values():
        for read in reads:
            read["Time_Stamp_UTC_ms"] = now_ms
    return payload


@pytest.fixture(autouse=True)
def enable_ekm_integration(enable_custom_integrations):
    """Allow Home Assistant to load the custom integration under test."""


@pytest.fixture(autouse=True)
def us_customary_units(hass):
    hass.config.units = US_CUSTOMARY_SYSTEM


@pytest.fixture
def payload() -> dict:
    return fresh_payload()


@pytest.fixture
def mock_readings(payload):
    """Patch the client; tests set ``mock.return_value`` or ``side_effect``."""
    with patch(
        "custom_components.ekm_local.api.EkmLocalClient.async_get_readings",
        new_callable=AsyncMock,
        return_value=parse_readings(payload),
    ) as mock:
        yield mock
