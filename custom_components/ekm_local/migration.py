"""Take over entity IDs (and so their history) from a legacy REST setup."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import entity_sources

from .const import CONF_ADOPT, DOMAIN
from .entity import entity_unique_id

_LOGGER = logging.getLogger(__name__)


def async_adopt_entities(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Move each requested entity ID onto this entry.

    ``entry.data[CONF_ADOPT]`` maps meter address -> {sensor key: entity ID}.
    Recorder history, long-term statistics and Energy dashboard references
    are keyed by entity ID, so an entity that ends up with the legacy ID keeps
    them.  Adopted mappings are dropped from the entry; returns the entity IDs
    still provided by something else.
    """
    requested: dict[str, dict[str, str]] = entry.data.get(CONF_ADOPT) or {}
    if not requested:
        return []

    registry = er.async_get(hass)
    loaded = entity_sources(hass)
    blocked: dict[str, dict[str, str]] = {}

    for address, mapping in requested.items():
        for key, entity_id in mapping.items():
            unique_id = entity_unique_id(address, key)
            own = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, unique_id)
            if own == entity_id:
                continue
            existing = registry.async_get(entity_id)

            if existing is None:
                if hass.states.get(entity_id) is not None:
                    blocked.setdefault(address, {})[key] = entity_id
                elif own is not None:
                    registry.async_update_entity(own, new_entity_id=entity_id)
                else:
                    registry.async_get_or_create(
                        Platform.SENSOR,
                        DOMAIN,
                        unique_id,
                        config_entry=entry,
                        suggested_object_id=entity_id.split(".", 1)[1],
                    )
                continue

            owner_entry = existing.config_entry_id
            if entity_id in loaded or (
                owner_entry not in (None, entry.entry_id)
                and hass.config_entries.async_get_entry(owner_entry) is not None
            ):
                blocked.setdefault(address, {})[key] = entity_id
                continue

            if own is not None:
                registry.async_remove(own)
            registry.async_update_entity_platform(
                entity_id,
                DOMAIN,
                new_config_entry_id=entry.entry_id,
                new_unique_id=unique_id,
                new_device_id=None,
            )
            _LOGGER.info("Took over %s from %s", entity_id, existing.platform)

    data = {k: v for k, v in entry.data.items() if k != CONF_ADOPT}
    if blocked:
        data[CONF_ADOPT] = blocked
    hass.config_entries.async_update_entry(entry, data=data)
    return sorted(e for mapping in blocked.values() for e in mapping.values())
