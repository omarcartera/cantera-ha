"""HA binary sensors for CANtera — CAN/OBD vehicle connection."""
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
    async_add_entities([CanteraCanConnectionSensor(coordinator)])


def _device_info() -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        name="CANtera Vehicle",
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
    )


class CanteraCanConnectionSensor(BinarySensorEntity):
    """Binary sensor tracking live CAN/OBD link to the vehicle ECU.

    Reflects the ``can_connected`` field returned by ``/api/health``.
    This field is ``true`` only when the OBD polling loop is actively
    exchanging frames with the ECU, so it accurately represents whether
    a vehicle is connected and powered on.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "CAN Connection"

    def __init__(self, coordinator: CanteraCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_can_connection"
        self._attr_is_on = False  # Unknown until first health poll.
        self._attr_device_info = _device_info()

    async def async_added_to_hass(self) -> None:
        """Register health poll callback."""
        await super().async_added_to_hass()
        self._coordinator.add_health_listener(self._handle_health_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister health poll callback."""
        self._coordinator.remove_health_listener(self._handle_health_update)

    @callback
    def _handle_health_update(self, health_data: dict) -> None:
        """Update state from can_connected field in /api/health response."""
        self._attr_is_on = health_data.get("can_connected", False)
        self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        return False
