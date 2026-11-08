"""Polling coordinator for one EKM Push3 gateway."""

from __future__ import annotations

import logging
from collections import deque
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EkmError, EkmLocalClient, MeterReading
from .const import (
    CONF_CORRECT_BASE,
    CONF_CORRECT_BY,
    CONF_CORRECT_FROZEN,
    CONF_CORRECT_METER,
    CONF_SCALE,
    CONF_SCALE_AUTO,
    CONF_SCALE_BASE,
    CONF_SCALE_DELAY,
    CONF_SCALE_METER,
    CONF_SCALE_OFF,
    CONF_SCALE_ON,
    CONF_SCAN_INTERVAL,
    CONF_STALE_AFTER,
    DEFAULT_SCALE_DELAY,
    DEFAULT_SCALE_OFF,
    DEFAULT_SCALE_ON,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_AFTER,
    DOMAIN,
    MIN_REF_AMPS,
)

_LOGGER = logging.getLogger(__name__)

type EkmConfigEntry = ConfigEntry[EkmCoordinator]


def scaled_kwh(
    reading: MeterReading, factors: dict[str, float], base: dict
) -> float | None:
    """Total kWh rebuilt from the line registers: base + sum(factor x line kWh since)."""
    total = float(base["kwh"])
    for line, start in base["lines"].items():
        now = reading.number(f"kWh_Ln_{line}")
        if now is None:
            return None
        total += factors.get(str(line), 1.0) * (now - start)
    return total


def line_kwh(reading: MeterReading) -> dict[str, float] | None:
    """Each line's kWh register, keyed "1".."3" (lines the meter doesn't report are skipped)."""
    lines = {}
    for line in (1, 2, 3):
        value = reading.number(f"kWh_Ln_{line}")
        if value is not None:
            lines[str(line)] = value
    return lines or None


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
        self.scale_meter: str | None = options.get(CONF_SCALE_METER) or None
        self.scale: dict[str, float] = {
            str(k): float(v) for k, v in (options.get(CONF_SCALE) or {}).items()
        }
        self.scale_base: dict | None = options.get(CONF_SCALE_BASE)
        if not self.scale_meter or not self.scale_base:
            self.scale_meter = self.scale_base = None
        self.scale_auto: bool = bool(options.get(CONF_SCALE_AUTO))
        self.scale_on: float = float(options.get(CONF_SCALE_ON, DEFAULT_SCALE_ON))
        self.scale_off: float = float(options.get(CONF_SCALE_OFF, DEFAULT_SCALE_OFF))
        self.scale_delay: float = float(options.get(CONF_SCALE_DELAY, DEFAULT_SCALE_DELAY))
        # per scaled line: applied now? (auto-detect; always True without it), averaged ratio
        self.scale_active: dict[str, bool] = {line: True for line in self.scale}
        self.scale_ratio: dict[str, float] = {}
        self._samples: dict[str, deque] = {}
        # energy accumulator {"base": options base it started from, "kwh", "lines": {line: kWh register}}
        self._acc: dict | None = None
        self._store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.scale")
        self._last_source_kwh: float | None = None
        self._last_energy: dict[str, float] = {}

    async def async_load_scale_state(self) -> None:
        """Restore the energy accumulator and auto-detect state saved before a restart."""
        if not self.scale_meter:
            return
        saved = await self._store.async_load() or {}
        if saved.get("meter") == self.scale_meter:
            for line, on in (saved.get("active") or {}).items():
                if line in self.scale_active:
                    self.scale_active[line] = bool(on)
            acc = saved.get("acc")
            if acc and acc.get("base") == self.scale_base:
                self._acc = acc

    def _save_scale_state(self) -> None:
        self._store.async_delay_save(
            lambda: {"meter": self.scale_meter, "active": self.scale_active, "acc": self._acc}, 30
        )

    async def _async_update_data(self) -> dict[str, MeterReading]:
        try:
            readings = await self.client.async_get_readings()
        except EkmError as err:
            raise UpdateFailed(str(err)) from err
        if self.scale_meter and (reading := readings.get(self.scale_meter)) is not None:
            self._accumulate(reading)   # with the factors in effect since the last poll
            if self.scale_auto:
                self._detect(reading, dt_util.utcnow().timestamp())
            self._save_scale_state()
        return readings

    def _accumulate(self, reading: MeterReading) -> None:
        """Add each line's kWh since the last poll, times the factor in effect."""
        lines = line_kwh(reading)
        if lines is None:
            return
        if self._acc is None:
            # first poll after the scale was set (or after upgrading from a constant-factor
            # version): the base formula is exact because the factor was constant until now
            kwh = scaled_kwh(reading, self.scale, self.scale_base)
            if kwh is None:
                return
            self._acc = {"base": self.scale_base, "kwh": kwh, "lines": lines}
            return
        total = self._acc["kwh"]
        for line, now in lines.items():
            before = self._acc["lines"].get(line, now)
            total += self.line_scale(self.scale_meter, line) * max(0.0, now - before)
        self._acc = {"base": self.scale_base, "kwh": round(total, 4), "lines": lines}

    def _detect(self, reading: MeterReading, now: float) -> None:
        """Auto-detect: a line's scale applies while its raw current runs high against the others."""
        amps = {
            str(line): abs(reading.number(f"Amps_Ln_{line}") or 0.0) for line in (1, 2, 3)
        }
        for line in self.scale:
            others = [a for n, a in amps.items() if n != line and a > 1.0]
            if not others or sum(others) / len(others) < MIN_REF_AMPS:
                continue
            samples = self._samples.setdefault(line, deque())
            samples.append((now, amps.get(line, 0.0) / (sum(others) / len(others))))
            while samples and now - samples[0][0] > self.scale_delay:
                samples.popleft()
            if now - samples[0][0] < 0.8 * self.scale_delay:
                continue   # not a full window yet
            mean = sum(r for _, r in samples) / len(samples)
            self.scale_ratio[line] = round(mean, 3)
            active = self.scale_active.get(line, True)
            if not active and mean >= self.scale_on:
                self.scale_active[line] = True
                _LOGGER.info("CT scale for line %s applied (ratio %.2f)", line, mean)
            elif active and mean <= self.scale_off:
                self.scale_active[line] = False
                _LOGGER.info("CT scale for line %s released (ratio %.2f)", line, mean)

    def accumulated_kwh(self) -> float | None:
        """The scaled meter's corrected total kWh so far (None before the first reading)."""
        return self._acc["kwh"] if self._acc else None

    def source_kwh(self) -> float | None:
        """The correction source meter's total kWh (last good value if missing now)."""
        reading = (self.data or {}).get(self.correct_by) if self.correct_by else None
        value = reading.number("kWh_Tot") if reading else None
        if value is not None:
            self._last_source_kwh = value
        return self._last_source_kwh

    def line_scale(self, address: str, line: int | str) -> float:
        """The CT scale factor in effect for one line (1 when not scaled or auto-released)."""
        if address != self.scale_meter or not self.scale_active.get(str(line), True):
            return 1.0
        return self.scale.get(str(line), 1.0)

    def scaled_power(
        self, address: str, reading: MeterReading, watts: float | None
    ) -> float | None:
        """Total watts with each scaled line's share corrected (lines count by magnitude)."""
        if watts is None or address != self.scale_meter:
            return watts
        for line in (1, 2, 3):
            line_watts = reading.number(f"RMS_Watts_Ln_{line}")
            if line_watts is not None:
                watts -= (1.0 - self.line_scale(address, line)) * abs(line_watts)
        return max(0.0, watts)

    def scaled_energy(
        self, address: str, reading: MeterReading, kwh: float | None
    ) -> float | None:
        """Total kWh rebuilt from the scaled lines (last good value if a register is missing)."""
        if kwh is None or address != self.scale_meter:
            return kwh
        return self.accumulated_kwh()

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
        if (
            address not in self.correct_frozen
            and address != self.correct_meter
            and address != self.scale_meter
        ):
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
