"""Shared test fixtures for CANtera HA integration tests."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry as _MockConfigEntry,  # noqa: F401
    )
    HAS_HA_TEST = True
except ImportError:
    HAS_HA_TEST = False


@pytest.fixture
def mock_config_entry_data():
    """Return config entry data for tests."""
    return {"host": "192.168.1.100", "port": 8088}


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp.ClientSession."""
    with patch("aiohttp.ClientSession") as mock_session_class:
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_class.return_value.__aexit__ = AsyncMock(return_value=False)
        yield mock_session


if not HAS_HA_TEST:
    @pytest.fixture(autouse=True)
    def _patch_frame_helper():
        """Prevent HA frame helper RuntimeError in tests without full HA test infra."""
        with patch("homeassistant.helpers.frame.report_usage"):
            yield

    @pytest.fixture
    def hass():
        """Minimal mock HomeAssistant when pytest-homeassistant-custom-component is unavailable."""
        mock_hass = MagicMock()
        mock_hass.data = {}
        mock_hass.async_create_task = MagicMock(
            side_effect=lambda coro: asyncio.ensure_future(coro)
        )
        return mock_hass
