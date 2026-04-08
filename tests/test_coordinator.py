"""Tests for CanteraCoordinator."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.cantera.coordinator import CanteraCoordinator
from custom_components.cantera.const import CONF_HOST, CONF_PORT


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.data = {CONF_HOST: "192.168.1.100", CONF_PORT: 8088}
    return entry


@pytest.fixture
def coordinator(hass, mock_entry):
    return CanteraCoordinator(hass, mock_entry)


# ---------- Init ----------

def test_coordinator_init(coordinator):
    """Coordinator initialises with correct defaults."""
    assert coordinator._host == "192.168.1.100"
    assert coordinator._port == 8088
    assert coordinator._listeners == []
    assert coordinator._sse_task is None
    assert coordinator._api_reachable is False
    assert coordinator._consecutive_health_failures == 0
    assert coordinator._health_data == {}


# ---------- SSE reading listeners ----------

def test_add_reading_listener(coordinator):
    """add_reading_listener stores callback."""
    cb = MagicMock()
    coordinator.add_reading_listener(cb)
    assert cb in coordinator._listeners


def test_remove_reading_listener(coordinator):
    """remove_reading_listener removes callback."""
    cb = MagicMock()
    coordinator.add_reading_listener(cb)
    coordinator.remove_reading_listener(cb)
    assert cb not in coordinator._listeners


def test_remove_reading_listener_missing_is_safe(coordinator):
    """Removing a callback that was never added doesn't raise."""
    coordinator.remove_reading_listener(MagicMock())


# ---------- Health listeners ----------

def test_add_health_listener(coordinator):
    cb = MagicMock()
    coordinator.add_health_listener(cb)
    assert cb in coordinator._health_listeners


def test_remove_health_listener(coordinator):
    cb = MagicMock()
    coordinator.add_health_listener(cb)
    coordinator.remove_health_listener(cb)
    assert cb not in coordinator._health_listeners


def test_notify_health_listeners_called(coordinator):
    """_notify_health_listeners calls all registered callbacks."""
    cb1, cb2 = MagicMock(), MagicMock()
    coordinator.add_health_listener(cb1)
    coordinator.add_health_listener(cb2)
    coordinator._notify_health_listeners()
    cb1.assert_called_once_with({})
    cb2.assert_called_once_with({})


# ---------- Health properties ----------

def test_is_api_reachable_initial(coordinator):
    assert coordinator.is_api_reachable is False


def test_health_data_initial(coordinator):
    assert coordinator.health_data == {}


# ---------- Lifecycle ----------

async def test_start_creates_sse_task(hass, coordinator):
    """start() creates an SSE loop task."""
    with patch("homeassistant.helpers.event.async_track_time_interval", return_value=MagicMock()):
        coordinator.start()
    assert coordinator._sse_task is not None
    coordinator._sse_task.cancel()
    try:
        await coordinator._sse_task
    except asyncio.CancelledError:
        pass


async def test_stop_cancels_task(hass, coordinator):
    """stop() cancels the SSE task and clears health state."""
    with patch("homeassistant.helpers.event.async_track_time_interval", return_value=MagicMock()):
        coordinator.start()
    assert coordinator._sse_task is not None
    await coordinator.stop()
    assert coordinator._sse_task is None
    assert coordinator._api_reachable is False


# ---------- _poll_health ----------

async def test_poll_health_success_sets_reachable(coordinator):
    """A 200 response from /api/health marks api_reachable True."""
    health_cb = MagicMock()
    coordinator.add_health_listener(health_cb)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": "ok", "can_connected": True})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        await coordinator._poll_health()

    assert coordinator._api_reachable is True
    assert coordinator._health_data["can_connected"] is True
    assert coordinator._consecutive_health_failures == 0
    health_cb.assert_called_once()


async def test_poll_health_failure_increments_counter(coordinator):
    """Network error increments failure counter."""
    import aiohttp
    with patch("aiohttp.ClientSession") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError())
        await coordinator._poll_health()

    assert coordinator._consecutive_health_failures == 1
    assert coordinator._api_reachable is False


async def test_poll_health_marks_unreachable_after_threshold(coordinator):
    """After HEALTH_FAIL_THRESHOLD failures, is_api_reachable → False with notification."""
    from custom_components.cantera.const import HEALTH_FAIL_THRESHOLD
    import aiohttp

    coordinator._api_reachable = True  # Simulate previously reachable.
    health_cb = MagicMock()
    coordinator.add_health_listener(health_cb)

    with patch("aiohttp.ClientSession") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError())
        for _ in range(HEALTH_FAIL_THRESHOLD):
            await coordinator._poll_health()

    assert coordinator._api_reachable is False
    health_cb.assert_called()


async def test_poll_health_resets_failures_on_success(coordinator):
    """A successful poll resets the consecutive failure counter."""
    coordinator._consecutive_health_failures = 3

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": "ok", "can_connected": False})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        await coordinator._poll_health()

    assert coordinator._consecutive_health_failures == 0


# ---------- Connection state ----------

def test_reading_listener_called(coordinator):
    """Callbacks in _listeners are called when a reading arrives."""
    cb = MagicMock()
    coordinator.add_reading_listener(cb)
    reading = {"pid": "engine_rpm", "value": 2400.0, "unit": "rpm"}
    coordinator._pid_units[reading["pid"]] = reading.get("unit", "")
    for listener in coordinator._listeners:
        listener(reading)
    cb.assert_called_once_with(reading)


# ---------- _backfill_history ----------

def _make_mock_session(status: int, json_return=None, get_side_effect=None):
    """Build a minimal aiohttp session mock for _backfill_history tests."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    if json_return is not None:
        mock_resp.json = AsyncMock(return_value=json_return)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    if get_side_effect is not None:
        mock_session.get = MagicMock(side_effect=get_side_effect)
    else:
        mock_session.get = MagicMock(return_value=mock_resp)
    return mock_session


async def test_backfill_history_200_imports_stats_and_saves(coordinator):
    """200 response: import_statistics and _save_last_sync are called."""
    readings = [
        {
            "pid": "Engine RPM",
            "ts": 1700000000000,
            "timestamp_ms": 1700000000000,
            "value": 2000.0,
            "unit": "rpm",
        }
    ]
    mock_session = _make_mock_session(200, json_return=readings)

    with patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0):
        with patch(
            "custom_components.cantera.coordinator.import_statistics",
            new_callable=AsyncMock,
        ) as mock_import:
            with patch.object(coordinator, "_save_last_sync", new_callable=AsyncMock) as mock_save:
                await coordinator._backfill_history(mock_session)

    mock_import.assert_awaited_once()
    mock_save.assert_awaited_once_with(1700000000000)


async def test_backfill_history_404_logs_warning_and_returns(coordinator):
    """Non-200 response: import_statistics is NOT called."""
    mock_session = _make_mock_session(404)

    with patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0):
        with patch(
            "custom_components.cantera.coordinator.import_statistics",
            new_callable=AsyncMock,
        ) as mock_import:
            await coordinator._backfill_history(mock_session)

    mock_import.assert_not_awaited()


async def test_backfill_history_exception_does_not_propagate(coordinator):
    """Any exception inside _backfill_history is caught and logged, never propagated."""
    mock_session = _make_mock_session(200, get_side_effect=RuntimeError("network failure"))

    with patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0):
        # Must not raise
        await coordinator._backfill_history(mock_session)


async def test_backfill_history_exception_inside_context_manager(coordinator):
    """Exception raised inside the response context (e.g. JSON decode) is caught."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(side_effect=RuntimeError("json decode failed"))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0):
        # Must not raise
        await coordinator._backfill_history(mock_session)


async def test_backfill_history_exception_inside_context_manager_does_not_propagate(coordinator):
    """Exception raised while reading response body (inside async-with) is also caught."""
    mock_session = _make_mock_session(200)
    mock_session.get.return_value.json = AsyncMock(side_effect=RuntimeError("json decode error"))

    with patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0):
        # Must not raise
        await coordinator._backfill_history(mock_session)


async def test_backfill_history_empty_readings_skips_import(coordinator):
    """Empty readings list: import_statistics and _save_last_sync are NOT called."""
    mock_session = _make_mock_session(200, json_return=[])

    with patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0):
        with patch(
            "custom_components.cantera.coordinator.import_statistics",
            new_callable=AsyncMock,
        ) as mock_import:
            with patch.object(coordinator, "_save_last_sync", new_callable=AsyncMock) as mock_save:
                await coordinator._backfill_history(mock_session)

    mock_import.assert_not_awaited()
    mock_save.assert_not_awaited()


# ---------- _load_last_sync ----------

async def test_load_last_sync_returns_zero_when_store_is_empty(coordinator):
    """_load_last_sync returns 0 when the store has no data."""
    with patch.object(coordinator._store, "async_load", AsyncMock(return_value=None)):
        result = await coordinator._load_last_sync()
    assert result == 0


async def test_load_last_sync_returns_stored_timestamp(coordinator):
    """_load_last_sync returns the ts value from storage."""
    with patch.object(coordinator._store, "async_load", AsyncMock(return_value={"ts": 123456})):
        result = await coordinator._load_last_sync()
    assert result == 123456


# ---------- _save_last_sync ----------

async def test_save_last_sync_persists_timestamp(coordinator):
    """_save_last_sync writes {ts: ts_ms} to the store."""
    with patch.object(coordinator._store, "async_save", AsyncMock()) as mock_save:
        await coordinator._save_last_sync(999000)
    mock_save.assert_awaited_once_with({"ts": 999000})


# ---------- SSE reconnect loop ----------

async def test_sse_loop_reconnects_after_exception(coordinator):
    """When _connect_and_stream raises, _connected is set False and the loop retries."""
    iterations = 0

    async def fake_connect():
        nonlocal iterations
        iterations += 1
        if iterations == 1:
            raise RuntimeError("SSE dropped")
        # Exit cleanly on the second iteration via CancelledError handler
        raise asyncio.CancelledError()

    with patch.object(coordinator, "_connect_and_stream", side_effect=fake_connect):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await coordinator._sse_loop()

    assert coordinator._connected is False
    assert iterations == 2
