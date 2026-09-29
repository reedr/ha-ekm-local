"""Sensors for EKM Local."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactiveEnergy,
    UnitOfReactivePower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import MeterReading
from .coordinator import EkmConfigEntry, EkmCoordinator
from .entity import EkmEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EkmSensorDescription(SensorEntityDescription):
    """Describes an EKM meter sensor."""

    value_fn: Callable[[MeterReading], float | datetime | None]
    field: str


def _number(field: str) -> Callable[[MeterReading], float | None]:
    return lambda reading: reading.number(field)


def _power_factor(field: str) -> Callable[[MeterReading], float | None]:
    return lambda reading: reading.power_factor(field)


def _sensor(
    key: str,
    field: str,
    *,
    enabled: bool = True,
    reader: Callable[[str], Callable[[MeterReading], float | None]] = _number,
    **kwargs,
) -> EkmSensorDescription:
    return EkmSensorDescription(
        key=key,
        translation_key=kwargs.pop("translation_key", key),
        field=field,
        value_fn=kwargs.pop("value_fn", None) or reader(field),
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def _per_line(
    key: str, field: str, *, enabled_lines: tuple[int, ...] = (1, 2), **kwargs
) -> list[EkmSensorDescription]:
    return [
        _sensor(
            f"{key}_l{line}",
            f"{field}_{line}",
            enabled=line in enabled_lines,
            translation_key=f"{key}_line",
            translation_placeholders={"line": str(line)},
            **kwargs,
        )
        for line in (1, 2, 3)
    ]


_POWER = {
    "device_class": SensorDeviceClass.POWER,
    "native_unit_of_measurement": UnitOfPower.WATT,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 0,
}
_REACTIVE = {
    "device_class": SensorDeviceClass.REACTIVE_POWER,
    "native_unit_of_measurement": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 0,
}
_ENERGY = {
    "device_class": SensorDeviceClass.ENERGY,
    "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    "state_class": SensorStateClass.TOTAL_INCREASING,
    "suggested_display_precision": 1,
}
_CURRENT = {
    "device_class": SensorDeviceClass.CURRENT,
    "native_unit_of_measurement": UnitOfElectricCurrent.AMPERE,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 1,
}
_VOLTAGE = {
    "device_class": SensorDeviceClass.VOLTAGE,
    "native_unit_of_measurement": UnitOfElectricPotential.VOLT,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 1,
}

SENSORS: tuple[EkmSensorDescription, ...] = (
    _sensor("power", "RMS_Watts_Tot", **_POWER),
    *_per_line("power", "RMS_Watts_Ln", **_POWER),
    _sensor("reactive_power", "Reactive_Pwr_Tot", **_REACTIVE),
    *_per_line("reactive_power", "Reactive_Pwr_Ln", enabled_lines=(), **_REACTIVE),
    *_per_line("current", "Amps_Ln", **_CURRENT),
    *_per_line("voltage", "RMS_Volts_Ln", **_VOLTAGE),
    *_per_line(
        "power_factor",
        "Cos_Theta_Ln",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        reader=_power_factor,
    ),
    _sensor(
        "frequency",
        "Line_Freq",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    _sensor("energy", "kWh_Tot", **_ENERGY),
    *_per_line("energy", "kWh_Ln", enabled_lines=(), **_ENERGY),
    *(
        _sensor(f"energy_tariff_{t}", f"kWh_Tariff_{t}", enabled=False,
                translation_key="energy_tariff",
                translation_placeholders={"tariff": str(t)}, **_ENERGY)
        for t in (1, 2, 3, 4)
    ),
    _sensor("reverse_energy", "Rev_kWh_Tot", enabled=False, **_ENERGY),
    _sensor(
        "reactive_energy",
        "Reactive_Energy_Tot",
        enabled=False,
        device_class=SensorDeviceClass.REACTIVE_ENERGY,
        native_unit_of_measurement=UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    _sensor("max_demand", "RMS_Watts_Max_Demand", enabled=False,
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            suggested_display_precision=0),
    *(
        _sensor(f"pulse_count_{n}", f"Pulse_Cnt_{n}", enabled=False,
                state_class=SensorStateClass.TOTAL_INCREASING,
                translation_key="pulse_count",
                translation_placeholders={"input": str(n)})
        for n in (1, 2, 3)
    ),
    _sensor("reliability", "Reliability_Ratio",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC),
    _sensor("last_reading", "Time_Stamp_UTC_ms", enabled=False,
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda reading: reading.timestamp),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EkmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_meters() -> None:
        new = [a for a in coordinator.data if a not in known]
        known.update(new)
        async_add_entities(
            EkmSensor(coordinator, address, description)
            for address in new
            for description in SENSORS
            if description.field in coordinator.data[address].raw
        )

    _add_new_meters()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_meters))


class EkmSensor(EkmEntity, SensorEntity):
    """A value from one meter's reading."""

    entity_description: EkmSensorDescription

    def __init__(
        self, coordinator: EkmCoordinator, address: str, description: EkmSensorDescription
    ) -> None:
        super().__init__(coordinator, address, description)

    @property
    def native_value(self) -> float | datetime | None:
        reading = self.reading
        return None if reading is None else self.entity_description.value_fn(reading)
