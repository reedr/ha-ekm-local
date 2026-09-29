"""Client for the EKM Push3 gateway's local readMeter API."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from .const import REQUEST_TIMEOUT


class EkmError(Exception):
    """Base error for EKM Local."""


class EkmConnectionError(EkmError):
    """The gateway could not be reached."""


class EkmAuthError(EkmError):
    """The gateway rejected the request; it answers a wrong key with HTTP 500."""


class EkmResponseError(EkmError):
    """The gateway returned something other than meter readings."""


@dataclass(frozen=True)
class MeterReading:
    """The latest read of one meter."""

    raw: dict[str, Any]

    @property
    def address(self) -> str:
        return str(self.raw["Meter_Address"])

    @property
    def model(self) -> str | None:
        return self.raw.get("Model")

    @property
    def firmware(self) -> str | None:
        return self.raw.get("Firmware")

    @property
    def timestamp(self) -> datetime | None:
        ms = self.number("Time_Stamp_UTC_ms")
        return None if ms is None else dt_util.utc_from_timestamp(ms / 1000)

    def number(self, key: str) -> float | None:
        """Return a numeric field, or None when missing or not a finite number."""
        value = self.raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        return float(value)

    def power_factor(self, key: str) -> float | None:
        """Parse a Cos_Theta field such as ``"0.83 C"`` (C/L = capacitive/inductive)."""
        value = self.raw.get(key)
        if not isinstance(value, str):
            return None
        try:
            return float(value.split()[0])
        except (IndexError, ValueError):
            return None


def parse_readings(payload: Any) -> dict[str, MeterReading]:
    """Validate a readMeter payload: {address: [reading, ...]}."""
    if not isinstance(payload, dict):
        raise EkmResponseError("response is not an object")
    meters: dict[str, MeterReading] = {}
    for address, reads in payload.items():
        if not isinstance(reads, list) or not reads or not isinstance(reads[-1], dict):
            continue
        # note: with cnt=1 there is one read; take the newest if there are more
        latest = max(reads, key=lambda r: r.get("Time_Stamp_UTC_ms") or 0)
        meters[str(address)] = MeterReading({"Meter_Address": address, **latest})
    if not meters:
        raise EkmResponseError("response has no meter readings")
    return meters


class EkmLocalClient:
    """Fetches the latest reading of every meter on a Push3 gateway."""

    def __init__(self, session: aiohttp.ClientSession, host: str, key: str) -> None:
        self._session = session
        self.host = host
        self._key = key

    async def async_get_readings(self) -> dict[str, MeterReading]:
        url = f"http://{self.host}/readMeter"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    url, params={"key": self._key, "cnt": "1"}
                ) as resp:
                    if resp.status in (401, 403, 500):
                        raise EkmAuthError(f"{url}: HTTP {resp.status}")
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            # note: the key is a query parameter, so never log the full URL
            raise EkmConnectionError(f"{url}: {type(err).__name__}") from err
        except ValueError as err:
            raise EkmResponseError(f"{url}: invalid JSON") from err
        return parse_readings(payload)
