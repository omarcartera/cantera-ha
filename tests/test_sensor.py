"""Tests for CANtera sensor entities."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from custom_components.cantera.sensor import CanteraSensor, async_setup_entry
from custom_components.cantera.coordinator import CanteraCoordinator
from custom_components.cantera.const import (
    CONF_HOST, CONF_PORT, DOMAIN,
    DEVICE_IDENTIFIER, DEVICE_MANUFACTURER, DEVICE_MODEL,
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
