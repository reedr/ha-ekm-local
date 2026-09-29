"""Binary sensors for EKM Local: gateway and per-meter communication."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EkmConfigEntry, EkmCoordinator
from .entity import EkmEntity

PARALLEL_UPDATES = 0

COMMUNICATING = BinarySensorEntityDescription(
    key="communicating",
    translation_key="communicating",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)
GATEWAY = BinarySensorEntityDescription(
    key="gateway_connected",
    translation_key="gateway_connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EkmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([EkmGatewayConnected(coordinator)])
    known: set[str] = set()

    @callback
    def _add_new_meters() -> None:
        new = [a for a in (coordinator.data or {}) if a not in known]
        known.update(new)
        async_add_entities(EkmMeterCommunicating(coordinator, a, COMMUNICATING) for a in new)

    _add_new_meters()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_meters))


class EkmMeterCommunicating(EkmEntity, BinarySensorEntity):
    """On while the gateway has a recent reading for this meter.

    Off while the gateway answers but the meter's reading is missing or stale
    (e.g. the meter lost power); unavailable only if the gateway is down, so
    "gateway up, meter silent" is distinguishable from "gateway down".
    """

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.meter_fresh(self._address)


class EkmGatewayConnected(CoordinatorEntity[EkmCoordinator], BinarySensorEntity):
    """On while the last readMeter poll succeeded; never unavailable."""

    _attr_has_entity_name = True
    entity_description = GATEWAY

    def __init__(self, coordinator: EkmCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_gateway_connected"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)})

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success
