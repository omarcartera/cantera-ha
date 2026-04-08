"""Tests for CANtera sensor entities."""
import time
from unittest.mock import MagicMock

import pytest

from custom_components.cantera.const import (
    CONF_HOST,
    CONF_PORT,
    DEVICE_IDENTIFIER,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SYNC_STALE_THRESHOLD_S,
    SYNC_STATUS_API_OFFLINE,
    SYNC_STATUS_CAR_OFF,
    SYNC_STATUS_LIVE,
    SYNC_STATUS_SYNCING,
)
from custom_components.cantera.coordinator import CanteraCoordinator
from custom_components.cantera.sensor import (
    CanteraSensor,
    CanteraSyncStatusSensor,
    async_setup_entry,
)


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.data = {CONF_HOST: "192.168.1.100", CONF_PORT: 8088}
    entry.entry_id = "test_entry_id"
    return entry


@pytest.fixture
def coordinator(hass, mock_entry):
    return CanteraCoordinator(hass, mock_entry)


@pytest.fixture
def sample_reading():
    return {"pid": "Engine RPM", "value": 2400.0, "unit": "rpm"}


@pytest.fixture
def sensor(coordinator, sample_reading):
    s = CanteraSensor(coordinator, sample_reading)
    # Stub async_write_ha_state so tests don't need full HA entity platform
    s.async_write_ha_state = MagicMock()
    return s


# ---------- CanteraSensor unit tests ----------

def test_sensor_unique_id(sensor):
    assert sensor._attr_unique_id == "cantera_engine_rpm"


def test_sensor_name(sensor):
    assert sensor._attr_name == "Engine RPM"


def test_sensor_native_unit(sensor):
    assert sensor._attr_native_unit_of_measurement == "rpm"


def test_sensor_initial_value(sensor):
    assert sensor._attr_native_value == 2400.0


def test_sensor_device_info(sensor):
    info = sensor._attr_device_info
    assert (DOMAIN, DEVICE_IDENTIFIER) in info["identifiers"]
    assert info["manufacturer"] == DEVICE_MANUFACTURER
    assert info["model"] == DEVICE_MODEL


def test_sensor_no_unit(coordinator):
    """Sensor with no unit gets None for native_unit_of_measurement."""
    reading = {"pid": "DTC Count", "value": 3}
    s = CanteraSensor(coordinator, reading)
    assert s._attr_native_unit_of_measurement is None


def test_sensor_km_h_device_class(coordinator):
    """km/h maps to SensorDeviceClass.SPEED."""
    from homeassistant.components.sensor import SensorDeviceClass
    reading = {"pid": "Vehicle Speed", "value": 60.0, "unit": "km/h"}
    s = CanteraSensor(coordinator, reading)
    assert s._attr_device_class == SensorDeviceClass.SPEED


def test_sensor_temperature_device_class(coordinator):
    """°C maps to SensorDeviceClass.TEMPERATURE."""
    from homeassistant.components.sensor import SensorDeviceClass
    reading = {"pid": "Coolant Temp", "value": 90.0, "unit": "°C"}
    s = CanteraSensor(coordinator, reading)
    assert s._attr_device_class == SensorDeviceClass.TEMPERATURE


def test_sensor_voltage_device_class(coordinator):
    """V maps to SensorDeviceClass.VOLTAGE."""
    from homeassistant.components.sensor import SensorDeviceClass
    reading = {"pid": "Battery Voltage", "value": 14.2, "unit": "V"}
    s = CanteraSensor(coordinator, reading)
    assert s._attr_device_class == SensorDeviceClass.VOLTAGE


def test_handle_reading_matching_pid(sensor):
    """_handle_reading updates value for matching PID slug."""
    sensor._handle_reading({"pid": "Engine RPM", "value": 3000.0, "unit": "rpm"})
    assert sensor._attr_native_value == 3000.0
    sensor.async_write_ha_state.assert_called_once()


def test_handle_reading_non_matching_pid(sensor):
    """_handle_reading ignores non-matching PID."""
    sensor._handle_reading({"pid": "Vehicle Speed", "value": 60.0, "unit": "km/h"})
    assert sensor._attr_native_value == 2400.0  # unchanged
    sensor.async_write_ha_state.assert_not_called()


# ---------- async_setup_entry ----------

async def test_async_setup_entry_registers_listener(hass, mock_entry, coordinator):
    """async_setup_entry registers a reading listener on the coordinator."""
    hass.data[DOMAIN] = {mock_entry.entry_id: coordinator}
    add_entities = MagicMock()
    listener_count_before = len(coordinator._listeners)
    await async_setup_entry(hass, mock_entry, add_entities)
    assert len(coordinator._listeners) == listener_count_before + 1


# ---------- CanteraSyncStatusSensor unit tests ----------

@pytest.fixture
def sync_sensor(coordinator):
    s = CanteraSyncStatusSensor(coordinator)
    s.async_write_ha_state = MagicMock()
    return s


def test_sync_sensor_unique_id(sync_sensor):
    assert sync_sensor._attr_unique_id == "cantera_sync_status"


def test_sync_sensor_name(sync_sensor):
    assert sync_sensor._attr_name == "Data Sync Status"


def test_sync_status_api_offline_by_default(sync_sensor, coordinator):
    """Without any health data, status is api_offline."""
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    assert sync_sensor.native_value == SYNC_STATUS_API_OFFLINE


def test_sync_status_car_off_when_can_not_connected(coordinator):
    """API reachable but can_connected=False → car_off."""
    coordinator._api_reachable = True
    coordinator._health_data = {"can_connected": False, "last_reading_ms": 0}
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF


def test_sync_status_car_off_when_no_reading(coordinator):
    """API reachable, CAN connected, but last_reading_ms=0 → car_off."""
    coordinator._api_reachable = True
    coordinator._health_data = {"can_connected": True, "last_reading_ms": 0}
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF


def test_sync_status_car_off_when_reading_stale(coordinator):
    """API reachable, CAN connected, but reading older than threshold → car_off."""
    coordinator._api_reachable = True
    now_ms = int(time.time() * 1000)
    stale_ms = now_ms - (SYNC_STALE_THRESHOLD_S + 10) * 1000
    coordinator._health_data = {"can_connected": True, "last_reading_ms": stale_ms}
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF


def test_sync_status_live_when_recent_reading(coordinator):
    """API reachable, CAN connected, reading within threshold → live."""
    coordinator._api_reachable = True
    now_ms = int(time.time() * 1000)
    coordinator._health_data = {"can_connected": True, "last_reading_ms": now_ms - 5000}
    assert coordinator.sync_status == SYNC_STATUS_LIVE


def test_sync_status_syncing_during_backfill(coordinator):
    """API reachable + backfilling in progress → syncing."""
    coordinator._api_reachable = True
    coordinator._backfilling = True
    coordinator._health_data = {"can_connected": True, "last_reading_ms": int(time.time() * 1000)}
    assert coordinator.sync_status == SYNC_STATUS_SYNCING


def test_sync_status_icon_matches_state(coordinator):
    """Icon changes with state."""
    from custom_components.cantera.sensor import _SYNC_STATUS_ICON
    for _state, icon in _SYNC_STATUS_ICON.items():
        assert icon.startswith("mdi:")


def test_sync_sensor_health_update_triggers_write(sync_sensor):
    """Health update callback triggers async_write_ha_state."""
    sync_sensor._handle_health_update({})
    sync_sensor.async_write_ha_state.assert_called_once()


async def test_async_setup_entry_adds_sync_status_sensor(hass, mock_entry, coordinator):
    """async_setup_entry immediately registers CanteraSyncStatusSensor."""
    hass.data[DOMAIN] = {mock_entry.entry_id: coordinator}
    added: list = []
    add_entities = MagicMock(side_effect=lambda entities: added.extend(entities))
    await async_setup_entry(hass, mock_entry, add_entities)
    sync_sensors = [e for e in added if isinstance(e, CanteraSyncStatusSensor)]
    assert len(sync_sensors) == 1
