"""Tests for CANtera __init__ setup and teardown."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cantera import (
    _async_remove_stale_entities,
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.cantera.const import DOMAIN


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    return entry


@pytest.fixture(autouse=True)
def patch_entity_registry():
    """Patch the HA entity registry for all tests in this module.

    Tests that specifically exercise cleanup logic override this with their
    own mock via additional patches.  The default returns an empty entity
    list so async_setup_entry does not fail during non-registry tests.
    """
    mock_reg = MagicMock()
    mock_reg.async_remove = MagicMock()
    with (
        patch("custom_components.cantera.er.async_get", return_value=mock_reg),
        patch(
            "custom_components.cantera.er.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        yield mock_reg


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


# ---------------------------------------------------------------------------
# Stale entity cleanup tests
# ---------------------------------------------------------------------------

def _make_entity_entry(entity_id: str, unique_id: str, disabled_by=None):
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.unique_id = unique_id
    entry.disabled_by = disabled_by
    return entry


def test_stale_entity_removed_when_not_in_current_ids(hass, mock_entry):
    """Entities no longer provided by the current version are removed from registry."""
    stale = _make_entity_entry("sensor.cantera_old_sensor", "cantera_test_entry_id_old_pid")
    current = _make_entity_entry("sensor.cantera_rpm", "cantera_test_entry_id_engine_rpm")

    hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            "current_unique_ids": {"cantera_test_entry_id_engine_rpm"}
        }
    }

    mock_registry = MagicMock()
    mock_registry.async_remove = MagicMock()

    with (
        patch("custom_components.cantera.er.async_get", return_value=mock_registry),
        patch(
            "custom_components.cantera.er.async_entries_for_config_entry",
            return_value=[stale, current],
        ),
    ):
        _async_remove_stale_entities(hass, mock_entry)

    mock_registry.async_remove.assert_called_once_with(stale.entity_id)


def test_current_entity_not_removed(hass, mock_entry):
    """Entities still provided by the current version are kept in the registry."""
    current = _make_entity_entry("sensor.cantera_rpm", "cantera_test_entry_id_engine_rpm")

    hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            "current_unique_ids": {"cantera_test_entry_id_engine_rpm"}
        }
    }

    mock_registry = MagicMock()
    mock_registry.async_remove = MagicMock()

    with (
        patch("custom_components.cantera.er.async_get", return_value=mock_registry),
        patch(
            "custom_components.cantera.er.async_entries_for_config_entry",
            return_value=[current],
        ),
    ):
        _async_remove_stale_entities(hass, mock_entry)

    mock_registry.async_remove.assert_not_called()


def test_disabled_stale_entity_is_preserved(hass, mock_entry):
    """User-disabled entities are never removed, even if no longer provided."""
    disabled_stale = _make_entity_entry(
        "sensor.cantera_old_sensor",
        "cantera_test_entry_id_old_pid",
        disabled_by="user",
    )

    hass.data[DOMAIN] = {
        mock_entry.entry_id: {"current_unique_ids": set()}
    }

    mock_registry = MagicMock()
    mock_registry.async_remove = MagicMock()

    with (
        patch("custom_components.cantera.er.async_get", return_value=mock_registry),
        patch(
            "custom_components.cantera.er.async_entries_for_config_entry",
            return_value=[disabled_stale],
        ),
    ):
        _async_remove_stale_entities(hass, mock_entry)

    mock_registry.async_remove.assert_not_called()


def test_stale_cleanup_skips_when_no_entry_data(hass, mock_entry):
    """Cleanup is a no-op when hass.data has no entry data (e.g., edge-case reload)."""
    hass.data[DOMAIN] = {}

    mock_registry = MagicMock()
    mock_registry.async_remove = MagicMock()

    with (
        patch("custom_components.cantera.er.async_get", return_value=mock_registry),
        patch(
            "custom_components.cantera.er.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        _async_remove_stale_entities(hass, mock_entry)

    mock_registry.async_remove.assert_not_called()


async def test_setup_initialises_current_unique_ids_in_hass_data(hass, mock_entry):
    """async_setup_entry populates hass.data with the current_unique_ids tracking set."""
    mock_coordinator = MagicMock()
    mock_coordinator.start = MagicMock()
    mock_coordinator.stop = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    with patch("custom_components.cantera.CanteraCoordinator", return_value=mock_coordinator):
        await async_setup_entry(hass, mock_entry)

    assert DOMAIN in hass.data
    assert mock_entry.entry_id in hass.data[DOMAIN]
    assert "current_unique_ids" in hass.data[DOMAIN][mock_entry.entry_id]
    assert isinstance(hass.data[DOMAIN][mock_entry.entry_id]["current_unique_ids"], set)


async def test_unload_cleans_up_hass_data(hass, mock_entry):
    """async_unload_entry removes the entry's data from hass.data."""
    hass.data[DOMAIN] = {mock_entry.entry_id: {"current_unique_ids": {"some_id"}}}
    mock_coordinator = AsyncMock()
    mock_entry.runtime_data = mock_coordinator
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    await async_unload_entry(hass, mock_entry)

    assert mock_entry.entry_id not in hass.data.get(DOMAIN, {})


# ---------------------------------------------------------------------------
# Service handler closures (lines 44-57) — requires has_service to return False
# ---------------------------------------------------------------------------

async def test_reconnect_service_handler_calls_stop_and_start(hass, mock_entry):
    """_handle_reconnect calls coordinator.stop() and .start() for every active entry."""
    coordinator = MagicMock()
    coordinator.start = MagicMock()
    coordinator.stop = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    # Force service registration path (has_service returns False)
    hass.services.has_service = MagicMock(return_value=False)

    with patch("custom_components.cantera.CanteraCoordinator", return_value=coordinator):
        await async_setup_entry(hass, mock_entry)

    # Locate the registered handler and invoke it
    calls = hass.services.async_register.call_args_list
    reconnect_call = next(c for c in calls if c[0][1] == "reconnect")
    handler = reconnect_call[0][2]

    mock_entry.runtime_data = coordinator
    # Handler iterates all active entries — return the single test entry.
    hass.config_entries.async_entries.return_value = [mock_entry]
    coordinator.start.reset_mock()
    coordinator.stop.reset_mock()
    await handler(MagicMock())

    coordinator.stop.assert_called_once()
    coordinator.start.assert_called_once()


async def test_request_history_service_creates_task_when_not_running(hass, mock_entry):
    """_handle_request_history schedules _backfill_history when task is None."""
    coordinator = MagicMock()
    coordinator.start = MagicMock()
    coordinator.stop = AsyncMock()
    coordinator._backfill_task = None
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.services.has_service = MagicMock(return_value=False)

    created_tasks: list = []

    def _capture_task(coro):
        import asyncio
        t = asyncio.ensure_future(coro)
        created_tasks.append(t)
        return t

    hass.async_create_task = MagicMock(side_effect=_capture_task)
    coordinator._backfill_history = AsyncMock()

    with patch("custom_components.cantera.CanteraCoordinator", return_value=coordinator):
        await async_setup_entry(hass, mock_entry)

    calls = hass.services.async_register.call_args_list
    history_call = next(c for c in calls if c[0][1] == "request_history")
    handler = history_call[0][2]

    mock_entry.runtime_data = coordinator
    # Handler iterates all active entries — return the single test entry.
    hass.config_entries.async_entries.return_value = [mock_entry]
    await handler(MagicMock())

    assert len(created_tasks) >= 1


async def test_request_history_service_skips_when_task_already_running(hass, mock_entry):
    """_handle_request_history does NOT schedule a second task when one is running."""
    coordinator = MagicMock()
    coordinator.start = MagicMock()
    coordinator.stop = AsyncMock()

    running_task = MagicMock()
    running_task.done = MagicMock(return_value=False)
    coordinator._backfill_task = running_task

    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.services.has_service = MagicMock(return_value=False)

    with patch("custom_components.cantera.CanteraCoordinator", return_value=coordinator):
        await async_setup_entry(hass, mock_entry)

    calls = hass.services.async_register.call_args_list
    history_call = next(c for c in calls if c[0][1] == "request_history")
    handler = history_call[0][2]

    hass.async_create_task.reset_mock()
    mock_entry.runtime_data = coordinator
    await handler(MagicMock())

    hass.async_create_task.assert_not_called()


# ---------------------------------------------------------------------------
# async_migrate_entry (line 97)
# ---------------------------------------------------------------------------

async def test_async_migrate_entry_version_1_returns_true(hass, mock_entry):
    """Migration returns True for version==1 (current schema)."""
    from custom_components.cantera import async_migrate_entry
    mock_entry.version = 1
    result = await async_migrate_entry(hass, mock_entry)
    assert result is True


async def test_async_migrate_entry_version_2_returns_false(hass, mock_entry):
    """Migration returns False for unknown future versions."""
    from custom_components.cantera import async_migrate_entry
    mock_entry.version = 2
    result = await async_migrate_entry(hass, mock_entry)
    assert result is False


# ---------------------------------------------------------------------------
# async_remove_entry when recorder unavailable (line 103)
# ---------------------------------------------------------------------------

async def test_async_remove_entry_returns_early_without_recorder(hass, mock_entry):
    """async_remove_entry exits immediately when _RECORDER_AVAILABLE is False."""
    import custom_components.cantera as cantera_init
    from custom_components.cantera import async_remove_entry

    original = cantera_init._RECORDER_AVAILABLE
    try:
        cantera_init._RECORDER_AVAILABLE = False
        # Should return without calling get_instance or listing statistics
        with patch("custom_components.cantera.get_instance") as mock_get:
            await async_remove_entry(hass, mock_entry)
            mock_get.assert_not_called()
    finally:
        cantera_init._RECORDER_AVAILABLE = original
