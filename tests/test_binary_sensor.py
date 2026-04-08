"""Tests for CANtera binary sensor entities."""
import pytest
from unittest.mock import MagicMock

from custom_components.cantera.binary_sensor import (
    CanteraConnectionSensor,
    CanteraCanConnectionSensor,
)
from custom_components.cantera.coordinator import CanteraCoordinator
from custom_components.cantera.const import CONF_HOST, CONF_PORT, DOMAIN


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.data = {CONF_HOST: "192.168.1.100", CONF_PORT: 8088}
    return entry


@pytest.fixture
def coordinator(hass, mock_entry):
    return CanteraCoordinator(hass, mock_entry)


# ---------- CanteraConnectionSensor ----------

def test_connection_sensor_initial_state(coordinator):
    """Sensor initialises from coordinator.is_api_reachable (False)."""
    sensor = CanteraConnectionSensor(coordinator)
    assert sensor._attr_is_on is False


def test_connection_sensor_unique_id(coordinator):
    """Unique ID is preserved for migration from SSE-based sensor."""
    sensor = CanteraConnectionSensor(coordinator)
    assert sensor._attr_unique_id == f"{DOMAIN}_connection"


def test_connection_sensor_name(coordinator):
    sensor = CanteraConnectionSensor(coordinator)
    assert sensor._attr_name == "API Connection"


def test_connection_sensor_no_poll(coordinator):
    sensor = CanteraConnectionSensor(coordinator)
    assert sensor.should_poll is False


def test_connection_sensor_updates_on_health(coordinator):
    """_handle_health_update reflects is_api_reachable."""
    sensor = CanteraConnectionSensor(coordinator)
    sensor.async_write_ha_state = MagicMock()

    coordinator._api_reachable = True
    sensor._handle_health_update({})
    assert sensor._attr_is_on is True
    sensor.async_write_ha_state.assert_called_once()

    coordinator._api_reachable = False
    sensor._handle_health_update({})
    assert sensor._attr_is_on is False


async def test_connection_sensor_registers_health_listener(hass, coordinator):
    """async_added_to_hass registers a health listener."""
    sensor = CanteraConnectionSensor(coordinator)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    await sensor.async_added_to_hass()
    assert sensor._handle_health_update in coordinator._health_listeners


async def test_connection_sensor_removes_listener_on_remove(hass, coordinator):
    """async_will_remove_from_hass unregisters the health listener."""
    sensor = CanteraConnectionSensor(coordinator)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    await sensor.async_added_to_hass()
    await sensor.async_will_remove_from_hass()
    assert sensor._handle_health_update not in coordinator._health_listeners


# ---------- CanteraCanConnectionSensor ----------

def test_can_sensor_initial_state(coordinator):
    """CAN sensor starts as False (unknown until first health poll)."""
    sensor = CanteraCanConnectionSensor(coordinator)
    assert sensor._attr_is_on is False


def test_can_sensor_unique_id(coordinator):
    sensor = CanteraCanConnectionSensor(coordinator)
    assert sensor._attr_unique_id == f"{DOMAIN}_can_connection"


def test_can_sensor_name(coordinator):
    sensor = CanteraCanConnectionSensor(coordinator)
    assert sensor._attr_name == "CAN Connection"


def test_can_sensor_no_poll(coordinator):
    sensor = CanteraCanConnectionSensor(coordinator)
    assert sensor.should_poll is False


def test_can_sensor_true_when_can_connected(coordinator):
    """can_connected=True in health data turns sensor on."""
    sensor = CanteraCanConnectionSensor(coordinator)
    sensor.async_write_ha_state = MagicMock()
    sensor._handle_health_update({"can_connected": True})
    assert sensor._attr_is_on is True
    sensor.async_write_ha_state.assert_called_once()


def test_can_sensor_false_when_can_disconnected(coordinator):
    """can_connected=False in health data turns sensor off."""
    sensor = CanteraCanConnectionSensor(coordinator)
    sensor.async_write_ha_state = MagicMock()
    sensor._attr_is_on = True
    sensor._handle_health_update({"can_connected": False})
    assert sensor._attr_is_on is False


def test_can_sensor_false_when_api_unreachable(coordinator):
    """Missing can_connected (API down) defaults to False."""
    sensor = CanteraCanConnectionSensor(coordinator)
    sensor.async_write_ha_state = MagicMock()
    sensor._attr_is_on = True
    sensor._handle_health_update({})  # Empty — API went offline.
    assert sensor._attr_is_on is False


async def test_can_sensor_registers_health_listener(hass, coordinator):
    """async_added_to_hass registers a health listener."""
    sensor = CanteraCanConnectionSensor(coordinator)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    await sensor.async_added_to_hass()
    assert sensor._handle_health_update in coordinator._health_listeners


async def test_can_sensor_removes_listener_on_remove(hass, coordinator):
    """async_will_remove_from_hass unregisters the health listener."""
    sensor = CanteraCanConnectionSensor(coordinator)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    await sensor.async_added_to_hass()
    await sensor.async_will_remove_from_hass()
    assert sensor._handle_health_update not in coordinator._health_listeners
