"""CANtera OBD-II Home Assistant Integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import CanteraCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "update", "firmware_update"]

# Key used to store the set of unique_ids registered by current code for an entry.
_CURRENT_UNIQUE_IDS_KEY = "current_unique_ids"

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

    # Initialise the unique_id tracking set so each platform can populate it.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        _CURRENT_UNIQUE_IDS_KEY: set()
    }

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

    # Remove entities that existed in the registry from a previous version but
    # are no longer provided by the current integration code.
    _async_remove_stale_entities(hass, entry)

    return True


def _async_remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entity registry entries that are no longer provided by this version.

    Each platform's ``async_setup_entry`` registers the unique_ids it creates
    into ``hass.data[DOMAIN][entry.entry_id][_CURRENT_UNIQUE_IDS_KEY]``.  Any
    entity present in the registry for this config entry whose unique_id is
    *not* in that set is a stale remnant from an older integration version and
    is removed here so the user does not have to delete and re-add the entry.

    User-disabled entities are left untouched.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    current_ids: set[str] = entry_data.get(_CURRENT_UNIQUE_IDS_KEY, set())

    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.disabled_by is not None:
            continue
        if entity_entry.unique_id not in current_ids:
            _LOGGER.debug(
                "Removing stale entity %s (unique_id=%r no longer registered by current version)",
                entity_entry.entity_id,
                entity_entry.unique_id,
            )
            registry.async_remove(entity_entry.entity_id)


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
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
