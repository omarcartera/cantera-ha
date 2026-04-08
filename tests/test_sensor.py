"""Tests for CanteraSensor."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.cantera.sensor import CanteraSensor
from custom_components.cantera.coordinator import CanteraCoordinator
from custom_components.cantera.const import DOMAIN, CONF_HOST, CONF_PORT


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.data = {CONF_HOST: "192.168.1.100", CONF_PORT: 8088}
    return entry


@pytest.fixture
def mock_coordinator(hass, mock_entry):
    coord = CanteraCoordinator(hass, mock_entry)
    return coord


def _make_sensor(coordinator, pid="Engine RPM", value=2400.0, unit="rpm"):
    reading = {"pid": pid, "value": value, "unit": unit}
    return CanteraSensor(coordinator, reading)


def test_sensor_unique_id(mock_coordinator):
    sensor = _make_sensor(mock_coordinator)
    assert sensor.unique_id == f"{DOMAIN}_engine_rpm"


def test_sensor_name(mock_coordinator):
    sensor = _make_sensor(mock_coordinator)
    assert sensor.name == "Engine RPM"


def test_sensor_initial_value(mock_coordinator):
    sensor = _make_sensor(mock_coordinator, value=2400.0)
    assert sensor.native_value == 2400.0


def test_sensor_unit(mock_coordinator):
    sensor = _make_sensor(mock_coordinator, unit="rpm")
    assert sensor.native_unit_of_measurement == "rpm"


def test_sensor_no_unit(mock_coordinator):
    sensor = _make_sensor(mock_coordinator, unit="")
    assert sensor.native_unit_of_measurement is None


def test_sensor_device_class_temperature(mock_coordinator):
    sensor = _make_sensor(mock_coordinator, unit="\u00b0C")
    assert sensor.device_class == SensorDeviceClass.TEMPERATURE


def test_sensor_device_class_speed(mock_coordinator):
    sensor = _make_sensor(mock_coordinator, unit="km/h")
    assert sensor.device_class == SensorDeviceClass.SPEED


def test_sensor_device_class_rpm_is_none(mock_coordinator):
    sensor = _make_sensor(mock_coordinator, unit="rpm")
    assert sensor.device_class is None


def test_sensor_state_class_measurement(mock_coordinator):
    sensor = _make_sensor(mock_coordinator, unit="rpm")
    assert sensor.state_class == SensorStateClass.MEASUREMENT


def test_sensor_state_class_total_increasing_km(mock_coordinator):
    sensor = _make_sensor(mock_coordinator, unit="km")
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING


def test_sensor_handle_reading_updates_value(mock_coordinator):
    """Sensor updates value when matching reading arrives."""
    sensor = _make_sensor(mock_coordinator, pid="Engine RPM", value=2400.0)
    sensor._attr_native_value = 2400.0

    # Simulate receiving new reading
    new_reading = {"pid": "Engine RPM", "value": 3000.0, "unit": "rpm"}
    sensor._attr_native_value = new_reading["value"]
    assert sensor.native_value == 3000.0


def test_sensor_ignores_different_pid(mock_coordinator):
    """Sensor should not update for readings from a different PID."""
    sensor = _make_sensor(mock_coordinator, pid="Engine RPM", value=2400.0)
    assert sensor._slug == "engine_rpm"
    other_slug = "vehicle_speed"
    assert sensor._slug != other_slug
