"""Polling coordinator for one EKM Push3 gateway."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EkmError, EkmLocalClient, MeterReading
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

type EkmConfigEntry = ConfigEntry[EkmCoordinator]


class EkmCoordinator(DataUpdateCoordinator[dict[str, MeterReading]]):
    """Polls readMeter for every meter on the gateway.

    Failures surface immediately (no stale-data grace): automations use these
    meters to detect utility outages.
    """

    config_entry: EkmConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: EkmConfigEntry, client: EkmLocalClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.gateway_device_id: str | None = None

    async def _async_update_data(self) -> dict[str, MeterReading]:
        try:
            return await self.client.async_get_readings()
        except EkmError as err:
            raise UpdateFailed(str(err)) from err
