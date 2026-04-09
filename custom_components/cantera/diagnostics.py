"""Diagnostics support for CANtera integration."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PORT


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    from .coordinator import CanteraCoordinator

    coordinator: CanteraCoordinator = entry.runtime_data

    return {
        "config": {
            "host": entry.data.get(CONF_HOST),
            "port": entry.data.get(CONF_PORT),
        },
        "connection": {
            "is_connected": coordinator.is_connected,
            "is_api_reachable": coordinator.is_api_reachable,
            "sync_status": coordinator.sync_status,
            "first_health_received": coordinator._first_health_received,
        },
        "health_data": coordinator.health_data,
    }
