"""Firmware update entity for CANtera Pi daemon.

Polls GET /api/update to check if a new version of the Pi binary is
available.  When the user presses Install, POSTs to /api/update/install,
then polls /api/health until the reported version changes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_PORT,
    DOMAIN,
    FIRMWARE_INSTALL_ENDPOINT,
    FIRMWARE_UPDATE_ENDPOINT,
)
from .coordinator import CanteraCoordinator

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=1)
_INSTALL_POLL_TIMEOUT_S = 300
_INSTALL_POLL_INTERVAL_S = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CANtera firmware update entity from a config entry."""
    coordinator: CanteraCoordinator = entry.runtime_data
    entity = CanteraFirmwareUpdateEntity(coordinator, entry)
    async_add_entities([entity], update_before_add=True)

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if "current_unique_ids" in entry_data and entity.unique_id:
        entry_data["current_unique_ids"].add(entity.unique_id)


class CanteraFirmwareUpdateEntity(UpdateEntity):
    """Represents the Pi firmware update state."""

    _attr_has_entity_name = True
    _attr_name = "Pi Firmware"
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(
        self,
        coordinator: CanteraCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_firmware"
        self._latest_version: str | None = None
        self._release_notes: str | None = None
        self._release_url: str | None = None
        self._attr_in_progress = False

    @property
    def device_info(self) -> DeviceInfo:
        return self._coordinator.device_info

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed version from the health endpoint."""
        return self._coordinator.health_data.get("version")

    @property
    def latest_version(self) -> str | None:
        return self._latest_version

    @property
    def release_url(self) -> str | None:
        return self._release_url

    async def async_release_notes(self) -> str | None:
        return self._release_notes

    @property
    def available(self) -> bool:
        # Always available — even when API is offline we show the installed version.
        return True

    async def async_update(self) -> None:
        """Poll GET /api/update for the latest version info."""
        if self._coordinator.api_offline:
            return

        host = self._entry.data.get("host", "")
        port = self._entry.data.get("port", DEFAULT_PORT)
        url = f"http://{host}:{port}{FIRMWARE_UPDATE_ENDPOINT}"

        self._coordinator.set_firmware_update_state("checking")

        try:
            _timeout = aiohttp.ClientTimeout(total=10)
            async with (
                aiohttp.ClientSession() as session,
                session.get(url, timeout=_timeout) as resp,
            ):
                if resp.status == 200:
                    data = await resp.json()
                    self._latest_version = data.get("latest_version")
                    self._release_notes = data.get("release_notes")
                    self._release_url = data.get("release_url")
                    # Pi is authoritative — read its status field directly.
                    pi_status = data.get("status")
                    if pi_status in (
                        "not_checked", "checking", "up_to_date",
                        "update_available", "check_failed",
                    ):
                        self._coordinator.set_firmware_update_state(pi_status)
                    else:
                        # Unknown / future status value — fall back to boolean.
                        if data.get("update_available"):
                            self._coordinator.set_firmware_update_state("update_available")
                        elif data.get("last_checked_utc") is not None:
                            self._coordinator.set_firmware_update_state("up_to_date")
                        else:
                            self._coordinator.set_firmware_update_state("not_checked")
                elif resp.status == 503:
                    _LOGGER.debug("Firmware updater disabled on Pi")
                    self._coordinator.set_firmware_update_state("not_checked")
                else:
                    self._coordinator.set_firmware_update_state("check_failed")
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug("Firmware update check failed: %s", err)
            self._coordinator.set_firmware_update_state("check_failed")

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Trigger firmware OTA install on the Pi."""
        host = self._entry.data.get("host", "")
        port = self._entry.data.get("port", DEFAULT_PORT)
        install_url = f"http://{host}:{port}{FIRMWARE_INSTALL_ENDPOINT}"
        health_url = f"http://{host}:{port}/api/health"

        payload: dict[str, Any] = {}
        if version:
            payload["version"] = version

        # Capture the current version BEFORE posting so that a brief health-
        # data gap during the install does not cause old_version = None and a
        # spurious early exit from the polling loop.
        old_version = self.installed_version or self._coordinator.health_data.get("version")

        try:
            async with aiohttp.ClientSession() as session, session.post(
                install_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 202):
                    body = await resp.text()
                    _LOGGER.error("Install request rejected (%s): %s", resp.status, body)
                    return
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.error("Install request failed: %s", err)
            return

        self._attr_in_progress = True
        self.async_write_ha_state()

        # Poll /api/health until version changes or timeout.
        new_version: str | None = None
        deadline = asyncio.get_running_loop().time() + _INSTALL_POLL_TIMEOUT_S
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(_INSTALL_POLL_INTERVAL_S)
            try:
                async with aiohttp.ClientSession() as session, session.get(
                    health_url, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        v = data.get("version")
                        if v is not None and v != old_version:
                            new_version = v
                            _LOGGER.info(
                                "CANtera Pi firmware updated: %s → %s",
                                old_version,
                                new_version,
                            )
                            break
            except (TimeoutError, aiohttp.ClientError):
                pass  # Pi may be restarting; keep polling

        self._attr_in_progress = False
        self.async_write_ha_state()

        if new_version:
            self.hass.components.persistent_notification.async_create(
                f"CANtera Pi firmware updated successfully.\n\n"
                f"**{old_version or 'previous version'} → {new_version}**\n\n"
                f"The Pi service restarted automatically. All sensors are live.",
                title="CANtera Pi Updated",
                notification_id="cantera_firmware_updated",
            )
        else:
            _LOGGER.warning(
                "CANtera firmware install: version did not change within %ds "
                "(old=%s). The Pi may still be installing in the background.",
                _INSTALL_POLL_TIMEOUT_S,
                old_version,
            )
