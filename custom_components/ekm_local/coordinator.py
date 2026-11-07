"""Polling coordinator for one EKM Push3 gateway."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EkmError, EkmLocalClient, MeterReading
from .const import (
    CONF_CORRECT_BASE,
    CONF_CORRECT_BY,
    CONF_CORRECT_FROZEN,
    CONF_CORRECT_METER,
    CONF_SCAN_INTERVAL,
    CONF_STALE_AFTER,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_AFTER,
    DOMAIN,
)

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
        self.stale_after = timedelta(
            seconds=entry.options.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER)
        )
        self.gateway_device_id: str | None = None
        options = entry.options
        self.correct_meter: str | None = options.get(CONF_CORRECT_METER) or None
        self.correct_by: str | None = options.get(CONF_CORRECT_BY) or None
        if not self.correct_meter or not self.correct_by or self.correct_meter == self.correct_by:
            self.correct_meter = self.correct_by = None
        self.correct_base: float | None = options.get(CONF_CORRECT_BASE)
        self.correct_frozen: dict[str, float] = dict(options.get(CONF_CORRECT_FROZEN) or {})
        self._last_source_kwh: float | None = None
        self._last_energy: dict[str, float] = {}

    async def _async_update_data(self) -> dict[str, MeterReading]:
        try:
            return await self.client.async_get_readings()
        except EkmError as err:
            raise UpdateFailed(str(err)) from err

    def source_kwh(self) -> float | None:
        """The correction source meter's total kWh (last good value if missing now)."""
        reading = (self.data or {}).get(self.correct_by) if self.correct_by else None
        value = reading.number("kWh_Tot") if reading else None
        if value is not None:
            self._last_source_kwh = value
        return self._last_source_kwh

    def corrected_power(self, address: str, watts: float | None) -> float | None:
        """Total watts with the source meter's load taken out (target meter only)."""
        if watts is None or address != self.correct_meter:
            return watts
        reading = (self.data or {}).get(self.correct_by)
        source = reading.number("RMS_Watts_Tot") if reading else None
        return watts if source is None else max(0.0, watts - source)

    def corrected_energy(self, address: str, kwh: float | None) -> float | None:
        """Total kWh less source usage while corrected; never steps backwards."""
        if kwh is None:
            return None
        value = kwh - self.correct_frozen.get(address, 0.0)
        if address == self.correct_meter and self.correct_base is not None:
            source = self.source_kwh()
            if source is not None:
                value -= max(0.0, source - self.correct_base)
        if address not in self.correct_frozen and address != self.correct_meter:
            return kwh
        value = round(max(value, self._last_energy.get(address, value)), 3)
        self._last_energy[address] = value
        return value

    def meter_fresh(self, address: str) -> bool:
        """True while the gateway is serving a recent reading for this meter."""
        if not self.last_update_success or not self.data:
            return False
        reading = self.data.get(address)
        if reading is None:
            return False
        stamp = reading.timestamp
        return stamp is None or dt_util.utcnow() - stamp < self.stale_after
