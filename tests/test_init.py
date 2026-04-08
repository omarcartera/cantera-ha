"""Tests for CANtera __init__ setup and teardown."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cantera import async_setup_entry, async_unload_entry
from custom_components.cantera.const import DOMAIN


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    return entry


async def test_async_setup_entry_creates_coordinator(hass, mock_entry):
    """async_setup_entry instantiates coordinator, starts it, forwards platforms, returns True."""
    mock_coordinator = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    with patch(
        "custom_components.cantera.CanteraCoordinator", return_value=mock_coordinator
    ) as mock_cls:
        result = await async_setup_entry(hass, mock_entry)

    assert result is True
    mock_cls.assert_called_once_with(hass, mock_entry)
    mock_coordinator.start.assert_called_once()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
    assert hass.data[DOMAIN][mock_entry.entry_id] is mock_coordinator


async def test_async_setup_entry_stores_coordinator_in_hass_data(hass, mock_entry):
    """Coordinator is stored under hass.data[DOMAIN][entry_id]."""
    mock_coordinator = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    with patch("custom_components.cantera.CanteraCoordinator", return_value=mock_coordinator):
        await async_setup_entry(hass, mock_entry)

    assert DOMAIN in hass.data
    assert mock_entry.entry_id in hass.data[DOMAIN]


async def test_async_unload_entry_success_pops_coordinator(hass, mock_entry):
    """Successful unload pops coordinator from hass.data and calls stop()."""
    mock_coordinator = AsyncMock()
    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    result = await async_unload_entry(hass, mock_entry)

    assert result is True
    mock_coordinator.stop.assert_awaited_once()
    assert mock_entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_async_unload_entry_failure_does_not_pop_coordinator(hass, mock_entry):
    """Failed unload does not pop coordinator and does not call stop()."""
    mock_coordinator = AsyncMock()
    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    result = await async_unload_entry(hass, mock_entry)

    assert result is False
    mock_coordinator.stop.assert_not_awaited()
    assert mock_entry.entry_id in hass.data[DOMAIN]
