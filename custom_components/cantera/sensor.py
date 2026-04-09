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
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    MODE01_PIDS,
    MODE09_PIDS,
    SYNC_STATUS_API_OFFLINE,
    SYNC_STATUS_CAR_OFF,
    SYNC_STATUS_LIVE,
    SYNC_STATUS_SYNCING,
    UNIT_DEVICE_CLASS_MAP,
    UNIT_PRECISION_MAP,
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
    """Set up CANtera sensors from a config entry.

    All Mode 01 and Mode 09 PID sensors are created immediately at setup with
    a ``None`` initial value.  Values are populated as SSE readings arrive.
    Pre-creating every sensor means the user sees the full sensor list in HA
    right after installation, regardless of which PIDs the vehicle supports.
    """
    coordinator: CanteraCoordinator = entry.runtime_data

    pid_sensors = [
        CanteraSensor(coordinator, name, unit, entry)
        for name, unit in (MODE01_PIDS + MODE09_PIDS)
    ]
    async_add_entities([CanteraSyncStatusSensor(coordinator, entry), *pid_sensors])


class CanteraSensor(RestoreSensor):
    """A single OBD PID sensor entity.

    Created upfront for every known Mode 01 and Mode 09 PID.  The initial
    ``native_value`` is ``None`` and is populated when an SSE reading with a
    matching PID name arrives, or restored from HA storage on restart.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CanteraCoordinator,
        name: str,
        unit: str | None = None,
        entry: ConfigEntry | None = None,
    ) -> None:
        """Initialise sensor for the given PID name and unit."""
        super().__init__()
        self._coordinator = coordinator
        slug = name.lower().replace(" ", "_")

        entry_id = entry.entry_id if entry is not None else "default"
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{slug}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_native_value = None

        dc_str = UNIT_DEVICE_CLASS_MAP.get(unit) if unit else None
        self._attr_device_class = _DEVICE_CLASS_LOOKUP.get(dc_str) if dc_str else None

        sc_str = UNIT_STATE_CLASS_MAP.get(unit, "measurement") if unit else "measurement"
        self._attr_state_class = (
            _STATE_CLASS_LOOKUP.get(sc_str, SensorStateClass.MEASUREMENT)
            if sc_str
            else SensorStateClass.MEASUREMENT
        )

        self._attr_suggested_display_precision = UNIT_PRECISION_MAP.get(unit) if unit else None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"cantera_vehicle_{entry_id}")},
            name="CANtera Vehicle",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

        self._slug = slug
        self._restored = False

    async def async_added_to_hass(self) -> None:
        """Register callbacks and restore state when added to HA."""
        await super().async_added_to_hass()
        self._coordinator.add_reading_listener(self._handle_reading)
        self._coordinator.add_health_listener(self._handle_health_update)
        if (last_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_data.native_value
            if last_data.native_unit_of_measurement:
                self._attr_native_unit_of_measurement = (
                    last_data.native_unit_of_measurement
                )
            self._restored = True

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when entity is removed from HA."""
        self._coordinator.remove_reading_listener(self._handle_reading)
        self._coordinator.remove_health_listener(self._handle_health_update)

    @property
    def available(self) -> bool:
        """Sensor is available while live data flows, or while holding restored state.

        If state was restored from HA storage and a live reading has not yet
        arrived, the restored value is shown as available so the user sees data
        immediately after restart.  Once a live reading clears the flag the
        normal coordinator-based check takes over.
        """
        if self._restored and self._attr_native_value is not None:
            return True
        return self._coordinator.sync_status == SYNC_STATUS_LIVE

    @property
    def should_poll(self) -> bool:
        """Disable polling — updates arrive via SSE callbacks."""
        return False

    @callback
    def _handle_reading(self, reading: dict) -> None:
        """Update value when a matching reading arrives."""
        pid_slug = reading.get("pid", "").lower().replace(" ", "_")
        if pid_slug == self._slug:
            self._restored = False
            self._attr_native_value = reading.get("value")
            self.async_write_ha_state()

    @callback
    def _handle_health_update(self, _health_data: dict) -> None:
        """Re-evaluate availability whenever the health state changes."""
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

    def __init__(self, coordinator: CanteraCoordinator, entry: ConfigEntry | None = None) -> None:
        """Initialise from coordinator."""
        self._coordinator = coordinator
        entry_id = entry.entry_id if entry is not None else "default"
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_sync_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"cantera_vehicle_{entry_id}")},
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

