"""CANtera OBD-II Home Assistant Integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .coordinator import CanteraCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "update", "firmware_update"]

try:
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import (
        async_list_statistic_ids,
        clear_statistics,
    )
    _RECORDER_AVAILABLE = True
except ImportError:
    _RECORDER_AVAILABLE = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CANtera from a config entry."""
    coordinator = CanteraCoordinator(hass, entry)
    entry.runtime_data = coordinator
    coordinator.start()
    entry.async_on_unload(coordinator.stop)

    if not hass.services.has_service(DOMAIN, "reconnect"):
        async def _handle_reconnect(call: ServiceCall) -> None:
            coord: CanteraCoordinator = entry.runtime_data
            await coord.stop()
            coord.start()

        async def _handle_request_history(call: ServiceCall) -> None:
            coord: CanteraCoordinator = entry.runtime_data
            if coord._backfill_task is None or coord._backfill_task.done():
                coord._backfill_task = hass.async_create_task(
                    coord._backfill_history()
                )

        hass.services.async_register(DOMAIN, "reconnect", _handle_reconnect)
        hass.services.async_register(DOMAIN, "request_history", _handle_request_history)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entry to the current version."""
    if entry.version == 1:
        return True
    return False


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove external statistics when the integration entry is deleted."""
    if not _RECORDER_AVAILABLE:
        return
    try:
        recorder = get_instance(hass)
        all_ids = await async_list_statistic_ids(hass)
        cantera_ids = [
            s["statistic_id"] for s in all_ids if s.get("source") == DOMAIN
        ]
        if cantera_ids:
            await recorder.async_add_executor_job(
                clear_statistics, recorder, cantera_ids
            )
    except Exception:
        _LOGGER.warning("Failed to clean up CANtera statistics on entry removal")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a CANtera config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: CanteraCoordinator = entry.runtime_data
        await coordinator.stop()
        hass.services.async_remove(DOMAIN, "reconnect")
        hass.services.async_remove(DOMAIN, "request_history")
    return unload_ok
