"""Config flow for EKM Local."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_NAME
from homeassistant.core import callback, valid_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    EkmAuthError,
    EkmConnectionError,
    EkmLocalClient,
    EkmResponseError,
    MeterReading,
)
from .const import (
    ADOPTABLE_SUFFIXES,
    CONF_ADOPT,
    CONF_LEGACY_PREFIX,
    CONF_METERS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import EkmConfigEntry
from .sensor import SENSORS

_GATEWAY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class EkmLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Push3 gateway, name its meters, optionally take over entities."""

    VERSION = 1

    def __init__(self) -> None:
        self._gateway: dict[str, str] = {}
        self._readings: dict[str, MeterReading] = {}
        self._pending: list[str] = []
        self._address = ""
        self._prefix = ""
        self._meters: dict[str, dict[str, str]] = {}
        self._adopt: dict[str, dict[str, str]] = {}

    async def _async_fetch(
        self, host: str, key: str
    ) -> tuple[dict[str, MeterReading] | None, str | None]:
        client = EkmLocalClient(async_get_clientsession(self.hass), host, key)
        try:
            return await client.async_get_readings(), None
        except EkmAuthError:
            return None, "invalid_key"
        except EkmConnectionError:
            return None, "cannot_connect"
        except EkmResponseError:
            return None, "invalid_response"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            key = user_input[CONF_API_KEY].strip()
            self._async_abort_entries_match({CONF_HOST: host})
            readings, error = await self._async_fetch(host, key)
            if readings is None:
                errors["base"] = error
            else:
                self._gateway = {CONF_HOST: host, CONF_API_KEY: key}
                self._readings = readings
                self._pending = sorted(readings)
                return await self.async_step_meter()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _GATEWAY_SCHEMA,
                {k: v for k, v in (user_input or {}).items() if k != CONF_API_KEY},
            ),
            errors=errors,
        )

    async def async_step_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            prefix = (user_input.get(CONF_LEGACY_PREFIX) or "").strip()
            if prefix and "." not in prefix:
                prefix = f"sensor.{prefix}"
            if prefix and not (prefix.startswith("sensor.") and valid_entity_id(prefix)):
                errors[CONF_LEGACY_PREFIX] = "invalid_entity_id"
            else:
                self._meters[self._address] = {"name": user_input[CONF_NAME].strip()}
                if prefix:
                    self._prefix = prefix
                    return await self.async_step_adopt()
                return await self._async_next_meter()
        elif not self._address:
            self._address = self._pending.pop(0)

        reading = self._readings[self._address]
        return self.async_show_form(
            step_id="meter",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_NAME): str,
                        vol.Optional(CONF_LEGACY_PREFIX): TextSelector(),
                    }
                ),
                user_input or {CONF_NAME: f"EKM meter {self._address}"},
            ),
            description_placeholders={
                "address": self._address,
                "model": reading.model or "unknown",
                "power": f"{reading.number('RMS_Watts_Tot') or 0:.0f}",
                "energy": f"{reading.number('kWh_Tot') or 0:.1f}",
            },
            errors=errors,
        )

    async def _async_next_meter(self) -> ConfigFlowResult:
        if not self._pending:
            data: dict[str, Any] = {**self._gateway, CONF_METERS: self._meters}
            if self._adopt:
                data[CONF_ADOPT] = self._adopt
            return self.async_create_entry(
                title=f"EKM Push3 ({self._gateway[CONF_HOST]})", data=data
            )
        self._address = self._pending.pop(0)
        return await self.async_step_meter()

    def _adoptable_keys(self) -> list[str]:
        raw = self._readings[self._address].raw
        present = {d.key for d in SENSORS if d.field in raw}
        return [key for key in ADOPTABLE_SUFFIXES if key in present]

    async def async_step_adopt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        keys = self._adoptable_keys()
        errors: dict[str, str] = {}
        if user_input is not None:
            adopt = {
                k: v.strip() for k, v in user_input.items() if k in keys and v and v.strip()
            }
            taken = {e for mapping in self._adopt.values() for e in mapping.values()}
            for key, entity_id in adopt.items():
                if not (entity_id.startswith("sensor.") and valid_entity_id(entity_id)):
                    errors[key] = "invalid_entity_id"
                elif list(adopt.values()).count(entity_id) > 1 or entity_id in taken:
                    errors[key] = "duplicate_entity_id"
            if not errors:
                if adopt:
                    self._adopt[self._address] = adopt
                return await self._async_next_meter()

        registry = er.async_get(self.hass)
        suggestions = user_input or {
            key: f"{self._prefix}{ADOPTABLE_SUFFIXES[key]}"
            for key in keys
            if registry.async_get(f"{self._prefix}{ADOPTABLE_SUFFIXES[key]}")
            or self.hass.states.get(f"{self._prefix}{ADOPTABLE_SUFFIXES[key]}")
        }
        return self.async_show_form(
            step_id="adopt",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Optional(key): TextSelector() for key in keys}),
                suggestions,
            ),
            description_placeholders={
                "name": self._meters[self._address]["name"],
                "address": self._address,
            },
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            key = (user_input.get(CONF_API_KEY) or "").strip() or entry.data[CONF_API_KEY]
            readings, error = await self._async_fetch(host, key)
            if readings is None:
                errors["base"] = error
            elif not set(readings) & set(entry.data.get(CONF_METERS) or {}):
                errors["base"] = "wrong_gateway"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host, CONF_API_KEY: key}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_HOST): str,
                        vol.Optional(CONF_API_KEY): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.PASSWORD)
                        ),
                    }
                ),
                {CONF_HOST: (user_input or entry.data)[CONF_HOST]},
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: EkmConfigEntry) -> EkmOptionsFlow:
        return EkmOptionsFlow()


class EkmOptionsFlow(OptionsFlowWithReload):
    """Polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_SCAN_INTERVAL): NumberSelector(
                            NumberSelectorConfig(
                                min=MIN_SCAN_INTERVAL,
                                max=MAX_SCAN_INTERVAL,
                                step=1,
                                unit_of_measurement="s",
                                mode=NumberSelectorMode.BOX,
                            )
                        )
                    }
                ),
                {
                    CONF_SCAN_INTERVAL: self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    )
                },
            ),
        )
