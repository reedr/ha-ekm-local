"""Base entity for EKM Local."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import MeterReading
from .const import CONF_METERS, DOMAIN, MANUFACTURER
from .coordinator import EkmCoordinator


def entity_unique_id(address: str, key: str) -> str:
    return f"{address}_{key}"


def meter_name(coordinator: EkmCoordinator, address: str) -> str:
    meters = coordinator.config_entry.data.get(CONF_METERS) or {}
    return meters.get(address, {}).get("name") or f"EKM meter {address}"


class EkmEntity(CoordinatorEntity[EkmCoordinator]):
    """An entity backed by one meter's readings."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: EkmCoordinator, address: str, description: EntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._address = address
        reading = coordinator.data[address]
        self._attr_unique_id = entity_unique_id(address, description.key)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=meter_name(coordinator, address),
            manufacturer=MANUFACTURER,
            model=f"Omnimeter (model {reading.model})" if reading.model else "Omnimeter",
            sw_version=reading.firmware,
            serial_number=address,
            via_device_id=coordinator.gateway_device_id,
        )

    @property
    def reading(self) -> MeterReading | None:
        return self.coordinator.data.get(self._address)

    @property
    def available(self) -> bool:
        return self.coordinator.meter_fresh(self._address)
