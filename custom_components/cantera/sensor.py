"""HA sensor entities for CANtera OBD readings."""
from __future__ import annotations

import logging
import time

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    EXPECTED_API_VERSION_MAJOR,
    MIN_API_VERSION_MINOR,
    MODE01_PIDS,
    MODE09_PIDS,
    PERSISTENT_MODE01_PIDS,
    SENSOR_API_OFFLINE_GRACE_S,
    SYNC_STATUS_API_OFFLINE,
    SYNC_STATUS_CAR_OFF,
    SYNC_STATUS_INCOMPATIBLE,
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
        CanteraSensor(coordinator, name, unit, entry, is_persistent=(name in PERSISTENT_MODE01_PIDS))
        for name, unit in MODE01_PIDS
    ] + [
        CanteraSensor(coordinator, name, unit, entry, is_diagnostic=True)
        for name, unit in MODE09_PIDS
    ]
    entities = [
        CanteraSyncStatusSensor(coordinator, entry),
        CanteraFirmwareVersionSensor(coordinator, entry),
        CanteraPiApiVersionSensor(coordinator, entry),
        CanteraExpectedApiVersionSensor(coordinator, entry),
        *pid_sensors,
    ]
    async_add_entities(entities)

    # Report our unique_ids so __init__.py can prune stale registry entries.
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if "current_unique_ids" in entry_data:
        entry_data["current_unique_ids"].update(
            e.unique_id for e in entities if e.unique_id
        )


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
        *,
        is_diagnostic: bool = False,
        is_persistent: bool = False,
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

        self._is_diagnostic = is_diagnostic
        self._is_persistent = is_persistent
        if is_diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        dc_str = UNIT_DEVICE_CLASS_MAP.get(unit) if unit else None
        self._attr_device_class = _DEVICE_CLASS_LOOKUP.get(dc_str) if dc_str else None

        if is_diagnostic:
            # Mode 09 sensors are text/string values — no state class or precision.
            self._attr_state_class = None
            self._attr_suggested_display_precision = None
        else:
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
        # Monotonic timestamp of the last SSE reading received while live.
        # Used to determine how long the API has been offline so we can show
        # the last-known value during brief outages instead of jumping to 0.
        self._last_live_at: float = 0.0

    async def async_added_to_hass(self) -> None:
        """Register callbacks and restore state when added to HA."""
        await super().async_added_to_hass()
        self._coordinator.add_reading_listener(self._slug, self._handle_reading)
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
        self._coordinator.remove_reading_listener(self._slug, self._handle_reading)
        self._coordinator.remove_health_listener(self._handle_health_update)

    @property
    def available(self) -> bool:
        """Always True — car_off and api_offline show 0 instead of unavailable.

        Keeping sensors available prevents Lovelace cards from disappearing or
        showing an error banner.  State is communicated via ``native_value``
        (0 when car is off, last-known value / 0 when API is offline) and via
        the dedicated sync-status sensor.
        """
        return True

    @property
    def native_value(self):
        """Return sensor reading, or a graceful fallback when data is absent.

        - ``live`` / ``syncing``: last SSE reading (or None before first read).
        - ``car_off``: Mode 01 live sensors return 0 (car is parked, all
          measurements are effectively 0). Mode 09 diagnostic sensors (VIN,
          calibration IDs, ECU names) persist their last-known value — they
          are static vehicle identifiers that should never be zeroed.
        - ``api_offline``: last-known value for up to SENSOR_API_OFFLINE_GRACE_S,
          then 0.  This masks brief Pi reboots without permanently freezing values.
          Diagnostic sensors always persist — they never need the grace window.
        """
        if self._is_diagnostic:
            # Static vehicle metadata — always return the last-known value as a
            # string regardless of connection or car state.  Mode 09 values (VIN,
            # ECU name, CVN, IUPR…) are always presented as text in HA.
            v = self._attr_native_value
            return str(v) if v is not None else None

        if self._is_persistent:
            # Slowly-changing physical property (e.g. fuel level) — the value
            # cannot meaningfully be 0 when the engine is off, so always return
            # the last-known reading rather than zeroing out.
            return self._attr_native_value

        status = self._coordinator.sync_status
        if status == SYNC_STATUS_CAR_OFF:
            return 0
        if status == SYNC_STATUS_API_OFFLINE:
            grace_elapsed = (
                time.monotonic() - self._last_live_at if self._last_live_at else float("inf")
            )
            if grace_elapsed < SENSOR_API_OFFLINE_GRACE_S:
                return self._attr_native_value  # last-known value during grace window
            return 0
        return self._attr_native_value

    @property
    def should_poll(self) -> bool:
        """Disable polling — updates arrive via SSE callbacks."""
        return False

    @callback
    def _handle_reading(self, reading: dict) -> None:
        """Update value when a reading for this sensor's PID arrives."""
        self._restored = False
        self._last_live_at = time.monotonic()
        self._attr_native_value = reading.get("value")
        self.async_write_ha_state()

    @callback
    def _handle_health_update(self, _health_data: dict) -> None:
        """Re-evaluate state whenever health data changes.

        ``native_value`` depends on ``sync_status`` so we must write state on
        every health change, not only when ``available`` flips.
        """
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Sync-status sensor
# ---------------------------------------------------------------------------

_SYNC_STATUS_ICON: dict[str, str] = {
    SYNC_STATUS_INCOMPATIBLE: "mdi:alert-circle",
    SYNC_STATUS_LIVE: "mdi:check-circle",
    SYNC_STATUS_CAR_OFF: "mdi:car-off",
    SYNC_STATUS_SYNCING: "mdi:sync",
    SYNC_STATUS_API_OFFLINE: "mdi:wifi-off",
}


class CanteraSyncStatusSensor(SensorEntity):
    """Sensor reporting the current data-update status of the CANtera integration.

    States:
    - ``incompatible``: Pi API major version does not match the integration.
    - ``live``:        API reachable, CAN connected, reading < 30 s old.
    - ``car_off``:     API reachable but no recent CAN data.
    - ``syncing``:     Connected to API; history backfill is in progress.
    - ``api_offline``: /api/health is unreachable.
    """

    _attr_has_entity_name = True
    _attr_name = "Data Sync Status"
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_SYNC_STATUS_ICON)
    _attr_translation_key = "sync_status"
    _attr_entity_category = EntityCategory.CONFIG

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

    @callback
    def _handle_health_update(self, _health_data: dict) -> None:
        """Refresh state whenever the health poll fires."""
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Firmware version sensor
# ---------------------------------------------------------------------------


class CanteraFirmwareVersionSensor(RestoreSensor):
    """Shows the version of the currently running Pi firmware.

    The version is read from the /api/health response and cached locally so it
    persists across Pi reboots and HA restarts.  When the Pi is unreachable the
    last known version continues to be displayed rather than reverting to
    "Unknown".
    """

    _attr_has_entity_name = True
    _attr_name = "Pi Firmware Version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: CanteraCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_firmware_version"
        self._cached_version: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore persisted version and register health listener."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            if last.native_value is not None:
                self._cached_version = str(last.native_value)
        self._coordinator.add_health_listener(self._handle_health_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister health listener."""
        self._coordinator.remove_health_listener(self._handle_health_update)

    @property
    def device_info(self) -> DeviceInfo:
        return self._coordinator.device_info

    @property
    def native_value(self) -> str | None:
        return self._cached_version

    @property
    def available(self) -> bool:
        return True

    @callback
    def _handle_health_update(self, health_data: dict) -> None:
        """Cache version from health data and push state to HA.

        Only updates the cache when a version string is present — an empty
        health_data dict (API offline) must not overwrite the last known version.
        """
        version = health_data.get("version")
        if version is not None:
            self._cached_version = str(version)
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# API version sensors
# ---------------------------------------------------------------------------


class CanteraPiApiVersionSensor(RestoreSensor):
    """Shows the API contract version currently reported by the Pi firmware.

    The value is read from ``api_version.major`` and ``api_version.minor`` in
    the /api/health response and formatted as ``"major.minor"`` (e.g. ``"1.0"``).
    The last known value persists when the Pi is unreachable so the sensor
    does not revert to Unknown during outages.
    """

    _attr_has_entity_name = True
    _attr_name = "Pi API Version"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:api"
    _attr_should_poll = False

    def __init__(self, coordinator: CanteraCoordinator, entry: ConfigEntry) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_pi_api_version"
        self._cached_version: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore persisted value and register health listener."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            if last.native_value is not None:
                self._cached_version = str(last.native_value)
        self._coordinator.add_health_listener(self._handle_health_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister health listener."""
        self._coordinator.remove_health_listener(self._handle_health_update)

    @property
    def device_info(self) -> DeviceInfo:
        return self._coordinator.device_info

    @property
    def native_value(self) -> str | None:
        return self._cached_version

    @property
    def available(self) -> bool:
        return True

    @callback
    def _handle_health_update(self, _health_data: dict) -> None:
        """Cache reported api_version from coordinator and push state to HA."""
        reported = self._coordinator.reported_api_version
        if reported is not None:
            self._cached_version = reported
        self.async_write_ha_state()


class CanteraExpectedApiVersionSensor(SensorEntity):
    """Shows the API contract version this integration was built to consume.

    This is a static sensor whose value is determined at install time by the
    ``EXPECTED_API_VERSION_MAJOR`` and ``MIN_API_VERSION_MINOR`` constants in
    ``const.py``.  Comparing this value against ``Pi API Version`` shows
    immediately whether the two sides are in sync.
    """

    _attr_has_entity_name = True
    _attr_name = "Expected API Version"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:api"
    _attr_should_poll = False
    _attr_available = True

    def __init__(self, coordinator: CanteraCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_expected_api_version"
        self._attr_native_value = (
            f"{EXPECTED_API_VERSION_MAJOR}.{MIN_API_VERSION_MINOR}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return self._coordinator.device_info


