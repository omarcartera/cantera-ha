"""Shared test fixtures for CANtera HA integration tests."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.core import HomeAssistant


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
