"""HA binary sensor for CANtera connection status."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_IDENTIFIER, DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN
from .coordinator import CanteraCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CANtera binary sensors from a config entry."""
    coordinator: CanteraCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CanteraConnectionSensor(coordinator)])


class CanteraConnectionSensor(BinarySensorEntity):
    """Binary sensor tracking SSE connection state."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "Connection"

    def __init__(self, coordinator: CanteraCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_connection"
        self._attr_is_on = coordinator.is_connected
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name="CANtera Vehicle",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    async def async_added_to_hass(self) -> None:
        """Register connection state callback."""
        await super().async_added_to_hass()
        self._coordinator.add_connection_listener(self._handle_connection_change)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister connection state callback."""
        self._coordinator.remove_connection_listener(self._handle_connection_change)

    @callback
    def _handle_connection_change(self) -> None:
        """Update state when connection state changes."""
        self._attr_is_on = self._coordinator.is_connected
        self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        return False
