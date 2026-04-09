"""CANtera OBD-II Home Assistant Integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .coordinator import CanteraCoordinator

PLATFORMS = ["sensor", "update"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CANtera from a config entry."""
    coordinator = CanteraCoordinator(hass, entry)
    entry.runtime_data = coordinator
    coordinator.start()

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


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a CANtera config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: CanteraCoordinator = entry.runtime_data
        await coordinator.stop()
        hass.services.async_remove(DOMAIN, "reconnect")
        hass.services.async_remove(DOMAIN, "request_history")
    return unload_ok
