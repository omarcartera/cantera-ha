"""Tests for the CANtera firmware update entity and firmware version sensor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cantera.const import (
    FIRMWARE_INSTALL_ENDPOINT,
    FIRMWARE_UPDATE_ENDPOINT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_coordinator(health_data: dict | None = None, api_offline: bool = False) -> MagicMock:
    coordinator = MagicMock()
    coordinator.health_data = health_data or {"version": "0.3.0"}
    coordinator.api_offline = api_offline
    coordinator.device_info = {"identifiers": {("cantera", "test")}}
    return coordinator


def _mock_entry(host: str = "192.168.1.100", port: int = 8080) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"host": host, "port": port}
    return entry


# ---------------------------------------------------------------------------
# GET /api/update tests
# ---------------------------------------------------------------------------

class TestCanteraFirmwareUpdateEntity:
    """Tests for the firmware update entity."""

    def test_installed_version_from_health_data(self):
        from custom_components.cantera.firmware_update import CanteraFirmwareUpdateEntity

        coordinator = _mock_coordinator({"version": "0.3.0"})
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())
        assert entity.installed_version == "0.3.0"

    @pytest.mark.asyncio
    async def test_latest_version_parsed(self):
        from custom_components.cantera.firmware_update import CanteraFirmwareUpdateEntity

        coordinator = _mock_coordinator()
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "current_version": "0.3.0",
                "latest_version": "0.3.1",
                "update_available": True,
                "release_url": "https://github.com/.../releases/tag/v0.3.1",
                "release_notes": "## What's new",
                "last_checked_utc": "2026-04-09T14:00:00Z",
            }
        )

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

            await entity.async_update()

        assert entity.latest_version == "0.3.1"
        assert entity._release_notes == "## What's new"

    def test_update_available_when_versions_differ(self):
        from custom_components.cantera.firmware_update import CanteraFirmwareUpdateEntity

        coordinator = _mock_coordinator({"version": "0.3.0"})
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())
        entity._latest_version = "0.3.1"

        assert entity.installed_version == "0.3.0"
        assert entity.latest_version == "0.3.1"

    @pytest.mark.asyncio
    async def test_no_update_check_when_api_offline(self):
        from custom_components.cantera.firmware_update import CanteraFirmwareUpdateEntity

        coordinator = _mock_coordinator(api_offline=True)
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

        with patch("aiohttp.ClientSession") as mock_session_cls:
            await entity.async_update()
            mock_session_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_install_posts_to_install_endpoint(self):
        from custom_components.cantera.firmware_update import CanteraFirmwareUpdateEntity

        coordinator = _mock_coordinator({"version": "0.3.0"})
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())
        entity.async_write_ha_state = MagicMock()

        post_response = AsyncMock()
        post_response.status = 202

        health_response = AsyncMock()
        health_response.status = 200
        health_response.json = AsyncMock(return_value={"version": "0.3.1"})

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.post.return_value.__aenter__ = AsyncMock(return_value=post_response)
            mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=health_response)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("asyncio.get_event_loop") as mock_loop:
                loop = MagicMock()
                mock_loop.return_value = loop
                # Make deadline always hit immediately so we exit after first poll
                loop.time.side_effect = [0, 200]

                await entity.async_install(version="0.3.1", backup=False)

        args, _ = mock_session.post.call_args
        assert FIRMWARE_INSTALL_ENDPOINT in args[0]

    @pytest.mark.asyncio
    async def test_install_sets_in_progress_then_clears(self):
        from custom_components.cantera.firmware_update import CanteraFirmwareUpdateEntity

        coordinator = _mock_coordinator({"version": "0.3.0"})
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

        in_progress_states: list[bool] = []
        original_write = MagicMock(side_effect=lambda: in_progress_states.append(entity._attr_in_progress))
        entity.async_write_ha_state = original_write

        post_response = AsyncMock()
        post_response.status = 202

        health_response = AsyncMock()
        health_response.status = 200
        health_response.json = AsyncMock(return_value={"version": "0.3.1"})

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.post.return_value.__aenter__ = AsyncMock(return_value=post_response)
            mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=health_response)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("asyncio.get_event_loop") as mock_loop:
                loop = MagicMock()
                mock_loop.return_value = loop
                loop.time.side_effect = [0, 200]

                await entity.async_install(version=None, backup=False)

        # First write_ha_state call: in_progress=True; second: in_progress=False
        assert len(in_progress_states) == 2
        assert in_progress_states[0] is True
        assert in_progress_states[1] is False


# ---------------------------------------------------------------------------
# Firmware version sensor tests
# ---------------------------------------------------------------------------

class TestCanteraFirmwareVersionSensor:
    def test_firmware_version_sensor(self):
        from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

        coordinator = _mock_coordinator({"version": "0.3.0"})
        entry = _mock_entry()
        sensor = CanteraFirmwareVersionSensor(coordinator, entry)

        assert sensor.native_value == "0.3.0"
        assert sensor.available is True


# ---------------------------------------------------------------------------
# Integration update no-restart test
# ---------------------------------------------------------------------------

class TestIntegrationUpdateNoRestart:
    @pytest.mark.asyncio
    async def test_integration_update_reloads_entry_not_ha(self):
        """Installing an integration update should reload the config entry, NOT restart HA."""
        import pathlib
        update_src = pathlib.Path(
            "custom_components/cantera/update.py"
        ).read_text()

        assert "homeassistant.restart" not in update_src, (
            "update.py must not call homeassistant.restart — "
            "use config_entries.async_reload instead"
        )
        assert "async_reload" in update_src, (
            "update.py must call config_entries.async_reload"
        )
