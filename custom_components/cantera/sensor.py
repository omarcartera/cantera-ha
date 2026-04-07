"""HA sensor entities for CANtera OBD readings."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_IDENTIFIER,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    UNIT_DEVICE_CLASS_MAP,
    UNIT_STATE_CLASS_MAP,
)
from .coordinator import CanteraCoordinator

_LOGGER = logging.getLogger(__name__)

# Map from string values used in UNIT_DEVICE_CLASS_MAP to HA enum members.
_DEVICE_CLASS_LOOKUP: dict[str, SensorDeviceClass] = {
    "speed": SensorDeviceClass.SPEED,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "voltage": SensorDeviceClass.VOLTAGE,
    "pressure": SensorDeviceClass.PRESSURE,
    "distance": SensorDeviceClass.DISTANCE,
    "volume": SensorDeviceClass.VOLUME,
}

_STATE_CLASS_LOOKUP: dict[str, SensorStateClass] = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CANtera sensors from a config entry."""
    coordinator: CanteraCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_pids: set[str] = set()

    @callback
    def _on_reading(reading: dict) -> None:
        pid = reading.get("pid", "")
        slug = pid.lower().replace(" ", "_")
        if slug and slug not in known_pids:
            known_pids.add(slug)
            async_add_entities([CanteraSensor(coordinator, reading)])

    coordinator.add_reading_listener(_on_reading)


class CanteraSensor(CoordinatorEntity, SensorEntity):
    """A single OBD PID sensor entity."""

    def __init__(
        self, coordinator: CanteraCoordinator, initial_reading: dict
    ) -> None:
        """Initialise from the first reading for this PID."""
        super().__init__(coordinator)
        pid_name: str = initial_reading["pid"]
        unit: str = initial_reading.get("unit", "")
        slug = pid_name.lower().replace(" ", "_")

        self._attr_unique_id = f"{DOMAIN}_{slug}"
        self._attr_name = pid_name
        self._attr_native_unit_of_measurement = unit or None
        self._attr_native_value = initial_reading.get("value")

        dc_str = UNIT_DEVICE_CLASS_MAP.get(unit)
        self._attr_device_class = _DEVICE_CLASS_LOOKUP.get(dc_str) if dc_str else None

        sc_str = UNIT_STATE_CLASS_MAP.get(unit, "measurement")
        self._attr_state_class = (
            _STATE_CLASS_LOOKUP.get(sc_str, SensorStateClass.MEASUREMENT)
            if sc_str
            else SensorStateClass.MEASUREMENT
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name="CANtera Vehicle",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

        self._slug = slug
        coordinator.add_reading_listener(self._handle_reading)

    @callback
    def _handle_reading(self, reading: dict) -> None:
        """Update value when a matching reading arrives."""
        pid_slug = reading.get("pid", "").lower().replace(" ", "_")
        if pid_slug == self._slug:
            self._attr_native_value = reading.get("value")
            self.async_write_ha_state()
