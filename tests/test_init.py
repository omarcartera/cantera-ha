"""Tests for CANtera __init__ setup and teardown."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cantera import async_setup_entry, async_unload_entry, async_remove_entry
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
    assert mock_entry.runtime_data is mock_coordinator


async def test_async_setup_entry_stores_coordinator_in_hass_data(hass, mock_entry):
    """Coordinator is stored in entry.runtime_data."""
    mock_coordinator = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    with patch("custom_components.cantera.CanteraCoordinator", return_value=mock_coordinator):
        await async_setup_entry(hass, mock_entry)

    assert mock_entry.runtime_data is mock_coordinator


async def test_async_unload_entry_success_pops_coordinator(hass, mock_entry):
    """Successful unload calls coordinator.stop()."""
    mock_coordinator = AsyncMock()
    mock_entry.runtime_data = mock_coordinator
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    result = await async_unload_entry(hass, mock_entry)

    assert result is True
    mock_coordinator.stop.assert_awaited_once()


async def test_async_unload_entry_failure_does_not_pop_coordinator(hass, mock_entry):
    """Failed unload does not call stop()."""
    mock_coordinator = AsyncMock()
    mock_entry.runtime_data = mock_coordinator
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    result = await async_unload_entry(hass, mock_entry)

    assert result is False
    mock_coordinator.stop.assert_not_awaited()


async def test_async_remove_entry_clears_statistics(hass, mock_entry):
    """async_remove_entry removes external statistics for this domain."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock()

    mock_stats = [
        {"statistic_id": "cantera:engine_rpm", "source": "cantera"},
        {"statistic_id": "other:something", "source": "other"},
    ]

    with (
        patch("custom_components.cantera.get_instance", return_value=mock_recorder),
        patch(
            "custom_components.cantera.async_list_statistic_ids",
            new_callable=AsyncMock,
            return_value=mock_stats,
        ),
        patch("custom_components.cantera.clear_statistics") as mock_clear,
    ):
        await async_remove_entry(hass, mock_entry)

    mock_recorder.async_add_executor_job.assert_awaited_once()
    args = mock_recorder.async_add_executor_job.call_args[0]
    assert args[0] is mock_clear
    assert args[2] == ["cantera:engine_rpm"]


async def test_async_remove_entry_no_stats_does_not_call_clear(hass, mock_entry):
    """async_remove_entry does nothing when there are no matching statistics."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock()

    with (
        patch("custom_components.cantera.get_instance", return_value=mock_recorder),
        patch(
            "custom_components.cantera.async_list_statistic_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await async_remove_entry(hass, mock_entry)

    mock_recorder.async_add_executor_job.assert_not_awaited()


async def test_async_remove_entry_exception_does_not_raise(hass, mock_entry):
    """async_remove_entry swallows exceptions (recorder unavailable etc.)."""
    from unittest.mock import patch

    with patch(
        "custom_components.cantera.get_instance",
        side_effect=RuntimeError("recorder not loaded"),
    ):
        await async_remove_entry(hass, mock_entry)  # must not raise


async def test_services_registered_on_setup(hass, mock_entry):
    """reconnect and request_history services are registered after setup."""
    from unittest.mock import AsyncMock, patch

    mock_coordinator = MagicMock()
    mock_coordinator.start = MagicMock()
    mock_coordinator.stop = AsyncMock()
    mock_coordinator._backfill_task = None
    mock_coordinator._backfill_history = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    mock_entry.runtime_data = mock_coordinator

    with patch("custom_components.cantera.CanteraCoordinator", return_value=mock_coordinator):
        await async_setup_entry(hass, mock_entry)

    assert hass.services.has_service(DOMAIN, "reconnect")
    assert hass.services.has_service(DOMAIN, "request_history")


async def test_services_not_double_registered(hass, mock_entry):
    """Services are not registered twice if setup is called again."""
    from unittest.mock import AsyncMock, patch

    mock_coordinator = MagicMock()
    mock_coordinator.start = MagicMock()
    mock_coordinator.stop = AsyncMock()
    mock_coordinator._backfill_task = None
    mock_coordinator._backfill_history = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    mock_entry.runtime_data = mock_coordinator

    with patch("custom_components.cantera.CanteraCoordinator", return_value=mock_coordinator):
        await async_setup_entry(hass, mock_entry)
        # Calling again should not raise (services already registered)
        await async_setup_entry(hass, mock_entry)

    assert hass.services.has_service(DOMAIN, "reconnect")
