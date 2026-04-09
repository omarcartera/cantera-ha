"""Tests for CANtera diagnostics platform."""
from unittest.mock import MagicMock

import pytest

from custom_components.cantera.diagnostics import async_get_config_entry_diagnostics
from custom_components.cantera.const import CONF_HOST, CONF_PORT, DOMAIN


@pytest.fixture
def mock_coordinator():
    coord = MagicMock()
    coord.is_connected = True
    coord.is_api_reachable = True
    coord.sync_status = "live"
    coord._first_health_received = True
    coord.health_data = {"can_connected": True, "version": "0.3.0"}
    return coord


@pytest.fixture
def mock_entry(mock_coordinator):
    entry = MagicMock()
    entry.data = {CONF_HOST: "10.0.0.1", CONF_PORT: 8080}
    entry.runtime_data = mock_coordinator
    return entry


async def test_diagnostics_returns_config(hass, mock_entry):
    """Config section contains host and port."""
    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    assert result["config"]["host"] == "10.0.0.1"
    assert result["config"]["port"] == 8080


async def test_diagnostics_returns_connection_state(hass, mock_entry, mock_coordinator):
    """Connection section reflects coordinator state."""
    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    conn = result["connection"]
    assert conn["is_connected"] is True
    assert conn["is_api_reachable"] is True
    assert conn["sync_status"] == "live"
    assert conn["first_health_received"] is True


async def test_diagnostics_returns_health_data(hass, mock_entry, mock_coordinator):
    """health_data from coordinator is included."""
    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    assert result["health_data"] == {"can_connected": True, "version": "0.3.0"}


async def test_diagnostics_disconnected_coordinator(hass, mock_entry, mock_coordinator):
    """Disconnected coordinator shows correctly in diagnostics."""
    mock_coordinator.is_connected = False
    mock_coordinator.is_api_reachable = False
    mock_coordinator.sync_status = "api_offline"
    mock_coordinator.health_data = {}

    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    assert result["connection"]["is_connected"] is False
    assert result["connection"]["sync_status"] == "api_offline"
    assert result["health_data"] == {}
