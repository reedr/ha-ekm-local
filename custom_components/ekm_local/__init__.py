"""EKM Local: read EKM Omnimeters through a Push3 gateway on the LAN."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EkmLocalClient
from .const import DOMAIN, MANUFACTURER, PLATFORMS
from .coordinator import EkmConfigEntry, EkmCoordinator
from .migration import async_adopt_entities


async def async_setup_entry(hass: HomeAssistant, entry: EkmConfigEntry) -> bool:
    client = EkmLocalClient(
        async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_API_KEY]
    )
    coordinator = EkmCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    if blocked := async_adopt_entities(hass, entry):
        raise ConfigEntryNotReady(
            f"Waiting to take over {', '.join(blocked)}: remove the REST sensors "
            "or other integration that still provides them"
        )

    gateway = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="EKM Push3 gateway",
        manufacturer=MANUFACTURER,
        model="Push3",
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
    coordinator.gateway_device_id = gateway.id
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EkmConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
