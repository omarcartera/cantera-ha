"""HA sensor entities for CANtera OBD readings."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_IDENTIFIER,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SYNC_STATUS_API_OFFLINE,
    SYNC_STATUS_CAR_OFF,
    SYNC_STATUS_LIVE,
    SYNC_STATUS_SYNCING,
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

    # Register the static sync-status sensor immediately.
    async_add_entities([CanteraSyncStatusSensor(coordinator)])

    @callback
    def _on_reading(reading: dict) -> None:
        pid = reading.get("pid", "")
        slug = pid.lower().replace(" ", "_")
        if slug and slug not in known_pids:
            known_pids.add(slug)
            async_add_entities([CanteraSensor(coordinator, reading)])

    coordinator.add_reading_listener(_on_reading)
    entry.async_on_unload(lambda: coordinator.remove_reading_listener(_on_reading))


class CanteraSensor(RestoreSensor):
    """A single OBD PID sensor entity."""

    def __init__(
        self, coordinator: CanteraCoordinator, initial_reading: dict
    ) -> None:
        """Initialise from the first reading for this PID."""
        super().__init__()
        self._coordinator = coordinator
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

    async def async_added_to_hass(self) -> None:
        """Register callback and restore state when added to HA."""
        await super().async_added_to_hass()
        self._coordinator.add_reading_listener(self._handle_reading)
        if (last_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_data.native_value
            if last_data.native_unit_of_measurement:
                self._attr_native_unit_of_measurement = (
                    last_data.native_unit_of_measurement
                )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed from HA."""
        self._coordinator.remove_reading_listener(self._handle_reading)

    @property
    def should_poll(self) -> bool:
        """Disable polling — updates arrive via SSE callbacks."""
        return False

    @callback
    def _handle_reading(self, reading: dict) -> None:
        """Update value when a matching reading arrives."""
        pid_slug = reading.get("pid", "").lower().replace(" ", "_")
        if pid_slug == self._slug:
            self._attr_native_value = reading.get("value")
            self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Sync-status sensor
# ---------------------------------------------------------------------------

_SYNC_STATUS_ICON: dict[str, str] = {
    SYNC_STATUS_LIVE: "mdi:check-circle",
    SYNC_STATUS_CAR_OFF: "mdi:car-off",
    SYNC_STATUS_SYNCING: "mdi:sync",
    SYNC_STATUS_API_OFFLINE: "mdi:wifi-off",
}


class CanteraSyncStatusSensor(SensorEntity):
    """Sensor reporting the current data-update status of the CANtera integration.

    States:
    - ``live``:        API reachable, CAN connected, reading < 30 s old.
    - ``car_off``:     API reachable but no recent CAN data.
    - ``syncing``:     Connected to API; history backfill is in progress.
    - ``api_offline``: /api/health is unreachable.
    """

    _attr_has_entity_name = True
    _attr_name = "Data Sync Status"
    _attr_should_poll = False

    def __init__(self, coordinator: CanteraCoordinator) -> None:
        """Initialise from coordinator."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_sync_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name="CANtera Vehicle",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    async def async_added_to_hass(self) -> None:
        """Register health listener when added to HA."""
        await super().async_added_to_hass()
        self._coordinator.add_health_listener(self._handle_health_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister health listener."""
        self._coordinator.remove_health_listener(self._handle_health_update)

    @property
    def native_value(self) -> str:
        """Return the current sync-status string."""
        return self._coordinator.sync_status

    @property
    def icon(self) -> str:
        """Return an icon matching the current state."""
        return _SYNC_STATUS_ICON.get(self._coordinator.sync_status, "mdi:help-circle")

    @callback
    def _handle_health_update(self, _health_data: dict) -> None:
        """Refresh state whenever the health poll fires."""
        self.async_write_ha_state()

