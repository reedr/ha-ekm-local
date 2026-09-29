"""Diagnostics for EKM Local."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import EkmConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EkmConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), {CONF_API_KEY}),
            "options": dict(entry.options),
        },
        "meters": {address: reading.raw for address, reading in coordinator.data.items()},
    }
