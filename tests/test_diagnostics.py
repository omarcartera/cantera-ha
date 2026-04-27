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
    coord.reported_api_version = "1.4"
    coord._first_health_received = True
    coord._consecutive_health_failures = 0
    coord._backfilling = False
    coord.firmware_update_state = "up_to_date"
    coord.health_data = {
        "can_connected": True,
        "version": "0.3.0",
        "vin": "1HGCM82633A123456",
        "wifi_ssid": "MyHomeNetwork",
        "local_ip": "192.168.1.50",
        "calibration_id": "CAL123",
        "cvn": "CVN456",
    }
    return coord


@pytest.fixture
def mock_entry(mock_coordinator):
    entry = MagicMock()
    entry.data = {CONF_HOST: "10.0.0.1", CONF_PORT: 8080}
    entry.runtime_data = mock_coordinator
    return entry


async def test_diagnostics_redacts_host_and_port(hass, mock_entry):
    """Host and port must be redacted in config section."""
    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    assert result["config"][CONF_HOST] == "**REDACTED**"
    assert result["config"][CONF_PORT] == "**REDACTED**"


async def test_diagnostics_returns_connection_state(hass, mock_entry, mock_coordinator):
    """Connection section reflects coordinator state."""
    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    conn = result["connection"]
    assert conn["is_connected"] is True
    assert conn["is_api_reachable"] is True
    assert conn["sync_status"] == "live"
    assert conn["api_version"] == "1.4"
    assert conn["first_health_received"] is True
    assert conn["consecutive_health_failures"] == 0


async def test_diagnostics_includes_operational_fields(hass, mock_entry, mock_coordinator):
    """Backfill and firmware sections are present."""
    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    assert result["backfill"]["in_progress"] is False
    assert result["firmware"]["update_state"] == "up_to_date"


async def test_diagnostics_redacts_sensitive_health_data(hass, mock_entry, mock_coordinator):
    """Sensitive health_data fields (VIN, Wi-Fi, IP, CalID, CVN) are redacted."""
    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    health = result["health_data"]
    assert health["can_connected"] is True
    assert health["version"] == "0.3.0"
    assert health["vin"] == "**REDACTED**"
    assert health["wifi_ssid"] == "**REDACTED**"
    assert health["local_ip"] == "**REDACTED**"
    assert health["calibration_id"] == "**REDACTED**"
    assert health["cvn"] == "**REDACTED**"


async def test_diagnostics_disconnected_coordinator(hass, mock_entry, mock_coordinator):
    """Disconnected coordinator shows correctly in diagnostics."""
    mock_coordinator.is_connected = False
    mock_coordinator.is_api_reachable = False
    mock_coordinator.sync_status = "api_offline"
    mock_coordinator._consecutive_health_failures = 5
    mock_coordinator.health_data = {}

    result = await async_get_config_entry_diagnostics(hass, mock_entry)
    assert result["connection"]["is_connected"] is False
    assert result["connection"]["sync_status"] == "api_offline"
    assert result["connection"]["consecutive_health_failures"] == 5
    assert result["health_data"] == {}
