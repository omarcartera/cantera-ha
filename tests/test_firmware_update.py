"""Tests for the CANtera firmware update entity and firmware version sensor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.cantera.const import (
    FIRMWARE_INSTALL_ENDPOINT,
)
from custom_components.cantera.firmware_update import CanteraFirmwareUpdateEntity


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

        coordinator = _mock_coordinator({"version": "0.3.0"})
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())
        assert entity.installed_version == "0.3.0"

    @pytest.mark.asyncio
    async def test_latest_version_parsed(self):

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

        coordinator = _mock_coordinator({"version": "0.3.0"})
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())
        entity._latest_version = "0.3.1"

        assert entity.installed_version == "0.3.0"
        assert entity.latest_version == "0.3.1"

    @pytest.mark.asyncio
    async def test_no_update_check_when_api_offline(self):

        coordinator = _mock_coordinator(api_offline=True)
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

        with patch("aiohttp.ClientSession") as mock_session_cls:
            await entity.async_update()
            mock_session_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_install_posts_to_install_endpoint(self):

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

        coordinator = _mock_coordinator({"version": "0.3.0"})
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

        in_progress_states: list[bool] = []
        original_write = MagicMock(
            side_effect=lambda: in_progress_states.append(entity._attr_in_progress)
        )
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
        coordinator.add_health_listener = MagicMock()
        coordinator.remove_health_listener = MagicMock()
        entry = _mock_entry()
        sensor = CanteraFirmwareVersionSensor(coordinator, entry)
        sensor.async_write_ha_state = MagicMock()

        # Before a health update the cache is empty.
        assert sensor.native_value is None

        # Simulate the coordinator notifying the listener with health data.
        sensor._handle_health_update({"version": "0.3.0"})
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


# ---------------------------------------------------------------------------
# Uncovered paths: async_setup_entry unique_id tracking (lines 45-51)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_setup_entry_registers_unique_id_in_tracking_set(hass):
    """async_setup_entry adds the entity unique_id to hass.data current_unique_ids."""
    from custom_components.cantera.const import DOMAIN
    from custom_components.cantera.firmware_update import async_setup_entry

    coordinator = _mock_coordinator()
    entry = _mock_entry()
    entry.runtime_data = coordinator

    uid_set: set[str] = set()
    hass.data = {DOMAIN: {entry.entry_id: {"current_unique_ids": uid_set}}}

    async_add_entities = MagicMock()
    # async_update is called by update_before_add=True — mock it out
    with patch(
        "custom_components.cantera.firmware_update.CanteraFirmwareUpdateEntity.async_update",
        new_callable=AsyncMock,
    ):
        await async_setup_entry(hass, entry, async_add_entities)

    assert f"{entry.entry_id}_firmware" in uid_set


# ---------------------------------------------------------------------------
# Simple property tests (lines 76, 89, 92, 97)
# ---------------------------------------------------------------------------

class TestProperties:
    def test_device_info_delegated_to_coordinator(self):
        """device_info returns the coordinator's DeviceInfo."""
        expected = {"identifiers": {("cantera", "test")}}
        coordinator = _mock_coordinator()
        coordinator.device_info = expected
        entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())
        assert entity.device_info is expected

    def test_release_url_initially_none(self):
        """release_url is None until async_update populates it."""
        entity = CanteraFirmwareUpdateEntity(_mock_coordinator(), _mock_entry())
        assert entity.release_url is None

    @pytest.mark.asyncio
    async def test_async_release_notes_initially_none(self):
        """async_release_notes returns None before first successful update check."""
        entity = CanteraFirmwareUpdateEntity(_mock_coordinator(), _mock_entry())
        assert await entity.async_release_notes() is None

    def test_available_always_true(self):
        """available is always True (firmware entity never goes unavailable)."""
        entity = CanteraFirmwareUpdateEntity(_mock_coordinator(), _mock_entry())
        assert entity.available is True


# ---------------------------------------------------------------------------
# async_update non-200 path (lines 119-122)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_update_503_does_not_set_latest_version():
    """503 from /api/update → latest_version stays None."""

    entity = CanteraFirmwareUpdateEntity(_mock_coordinator(), _mock_entry())

    mock_resp = AsyncMock()
    mock_resp.status = 503

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        await entity.async_update()

    assert entity.latest_version is None


# ---------------------------------------------------------------------------
# async_install error paths (lines 144-149)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_install_non_202_returns_before_setting_in_progress():
    """Non-202 POST response → returns early without ever marking in_progress=True."""

    entity = CanteraFirmwareUpdateEntity(_mock_coordinator(), _mock_entry())
    entity.async_write_ha_state = MagicMock()

    post_resp = AsyncMock()
    post_resp.status = 500
    post_resp.text = AsyncMock(return_value="Internal Server Error")

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=post_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        await entity.async_install(version=None, backup=False)

    # install failed before reaching the in_progress block
    entity.async_write_ha_state.assert_not_called()
    assert entity._attr_in_progress is False


@pytest.mark.asyncio
async def test_async_install_client_error_returns_early():
    """ClientError during POST → returns early, never sets in_progress."""
    entity = CanteraFirmwareUpdateEntity(_mock_coordinator(), _mock_entry())
    entity.async_write_ha_state = MagicMock()

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session_cls.return_value.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("connection failed")
        )
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await entity.async_install(version=None, backup=False)

    entity.async_write_ha_state.assert_not_called()


# ---------------------------------------------------------------------------
# async_install poll loop (lines 159-174)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_install_poll_loop_client_error_is_swallowed():
    """ClientError during health poll → loop continues (Pi may be restarting)."""
    coordinator = _mock_coordinator({"version": "0.3.0"})
    entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())
    entity.async_write_ha_state = MagicMock()

    post_resp = AsyncMock()
    post_resp.status = 202

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=post_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        # GET health fails with ClientError (Pi is restarting)
        mock_session.get.return_value.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("Pi restarting")
        )
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("asyncio.get_event_loop") as mock_loop:
            loop = MagicMock()
            mock_loop.return_value = loop
            # Deadline expires immediately after first poll attempt
            loop.time.side_effect = [0, 200]

            with patch("asyncio.sleep", new_callable=AsyncMock):
                await entity.async_install(version=None, backup=False)

    # Should complete cleanly with in_progress cleared
    assert entity._attr_in_progress is False


# ---------------------------------------------------------------------------
# Pi-owned status field tests
# ---------------------------------------------------------------------------

def _make_mock_session(get_resp):
    """Return a patched aiohttp.ClientSession that returns get_resp for GET."""
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=get_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_session


@pytest.mark.asyncio
async def test_async_update_uses_pi_status_field_up_to_date():
    """Pi response with status='up_to_date' sets coordinator state directly."""
    coordinator = _mock_coordinator()
    coordinator.set_firmware_update_state = MagicMock()
    entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "current_version": "0.3.0",
        "latest_version": None,
        "update_available": False,
        "status": "up_to_date",
        "last_checked_utc": "2026-04-11T09:00:00Z",
    })

    with patch("aiohttp.ClientSession", return_value=_make_mock_session(resp)):
        await entity.async_update()

    coordinator.set_firmware_update_state.assert_called_with("up_to_date")


@pytest.mark.asyncio
async def test_async_update_uses_pi_status_field_update_available():
    """Pi response with status='update_available' sets coordinator state directly."""
    coordinator = _mock_coordinator()
    coordinator.set_firmware_update_state = MagicMock()
    entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "current_version": "0.3.0",
        "latest_version": "0.3.1",
        "update_available": True,
        "status": "update_available",
        "last_checked_utc": "2026-04-11T09:00:00Z",
    })

    with patch("aiohttp.ClientSession", return_value=_make_mock_session(resp)):
        await entity.async_update()

    coordinator.set_firmware_update_state.assert_called_with("update_available")


@pytest.mark.asyncio
async def test_async_update_uses_pi_status_field_not_checked():
    """Pi in Idle state (status='not_checked') sets coordinator state directly."""
    coordinator = _mock_coordinator()
    coordinator.set_firmware_update_state = MagicMock()
    entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "current_version": "0.3.0",
        "latest_version": None,
        "update_available": False,
        "status": "not_checked",
        "last_checked_utc": None,
    })

    with patch("aiohttp.ClientSession", return_value=_make_mock_session(resp)):
        await entity.async_update()

    coordinator.set_firmware_update_state.assert_called_with("not_checked")


@pytest.mark.asyncio
async def test_async_update_fallback_when_status_field_absent():
    """Old Pi firmware without 'status' field falls back to boolean logic."""
    coordinator = _mock_coordinator()
    coordinator.set_firmware_update_state = MagicMock()
    entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "current_version": "0.3.0",
        "latest_version": "0.3.1",
        "update_available": True,
        # No "status" field — old firmware
        "last_checked_utc": "2026-04-11T09:00:00Z",
    })

    with patch("aiohttp.ClientSession", return_value=_make_mock_session(resp)):
        await entity.async_update()

    coordinator.set_firmware_update_state.assert_called_with("update_available")


@pytest.mark.asyncio
async def test_async_update_fallback_no_status_no_check():
    """Old Pi firmware without 'status' and last_checked_utc=None → 'not_checked'."""
    coordinator = _mock_coordinator()
    coordinator.set_firmware_update_state = MagicMock()
    entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "current_version": "0.3.0",
        "latest_version": None,
        "update_available": False,
        "last_checked_utc": None,
    })

    with patch("aiohttp.ClientSession", return_value=_make_mock_session(resp)):
        await entity.async_update()

    coordinator.set_firmware_update_state.assert_called_with("not_checked")


@pytest.mark.asyncio
async def test_async_update_sets_checking_then_final_state():
    """async_update sets 'checking' first, then the Pi's status."""
    coordinator = _mock_coordinator()
    calls = []
    coordinator.set_firmware_update_state = MagicMock(side_effect=calls.append)
    entity = CanteraFirmwareUpdateEntity(coordinator, _mock_entry())

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "current_version": "0.3.0",
        "latest_version": None,
        "update_available": False,
        "status": "up_to_date",
        "last_checked_utc": "2026-04-11T09:00:00Z",
    })

    with patch("aiohttp.ClientSession", return_value=_make_mock_session(resp)):
        await entity.async_update()

    assert calls == ["checking", "up_to_date"]
