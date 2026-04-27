"""Diagnostics support for CANtera integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PORT

_REDACT_KEYS: frozenset[str] = frozenset({
    CONF_HOST,
    CONF_PORT,
    "vin",
    "wifi_ssid",
    "local_ip",
    "calibration_id",
    "cvn",
})


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    from .coordinator import CanteraCoordinator

    coordinator: CanteraCoordinator = entry.runtime_data

    return {
        "config": async_redact_data(dict(entry.data), _REDACT_KEYS),
        "connection": {
            "is_connected": coordinator.is_connected,
            "is_api_reachable": coordinator.is_api_reachable,
            "sync_status": coordinator.sync_status,
            "api_version": coordinator.reported_api_version,
            "first_health_received": coordinator._first_health_received,
            "consecutive_health_failures": coordinator._consecutive_health_failures,
        },
        "backfill": {
            "in_progress": coordinator._backfilling,
        },
        "firmware": {
            "update_state": coordinator.firmware_update_state,
        },
        "health_data": async_redact_data(
            dict(coordinator.health_data), _REDACT_KEYS
        ),
    }
