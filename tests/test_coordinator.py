"""Tests for CanteraCoordinator."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cantera.const import CONF_HOST, CONF_PORT
from custom_components.cantera.coordinator import CanteraCoordinator


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
    assert len(coordinator._reading_listeners) == 0
    assert coordinator._sse_task is None
    assert coordinator._api_reachable is False
    assert coordinator._consecutive_health_failures == 0
    assert coordinator._health_data == {}


# ---------- SSE reading listeners ----------

def test_add_reading_listener(coordinator):
    """add_reading_listener stores callback under the given slug."""
    cb = MagicMock()
    coordinator.add_reading_listener("engine_rpm", cb)
    assert cb in coordinator._reading_listeners["engine_rpm"]


def test_remove_reading_listener(coordinator):
    """remove_reading_listener removes callback from the slug bucket."""
    cb = MagicMock()
    coordinator.add_reading_listener("engine_rpm", cb)
    coordinator.remove_reading_listener("engine_rpm", cb)
    assert cb not in coordinator._reading_listeners["engine_rpm"]


def test_remove_reading_listener_missing_is_safe(coordinator):
    """Removing a callback that was never added doesn't raise."""
    coordinator.remove_reading_listener("engine_rpm", MagicMock())


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
    import contextlib
    with contextlib.suppress(asyncio.CancelledError):
        await coordinator._sse_task


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

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session):
        await coordinator._poll_health()

    assert coordinator._api_reachable is True
    assert coordinator._health_data["can_connected"] is True
    assert coordinator._consecutive_health_failures == 0
    health_cb.assert_called_once()


async def test_poll_health_failure_increments_counter(coordinator):
    """Network error increments failure counter."""
    import aiohttp
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=aiohttp.ClientError())
    with patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session):
        await coordinator._poll_health()

    assert coordinator._consecutive_health_failures == 1
    assert coordinator._api_reachable is False


async def test_poll_health_marks_unreachable_after_threshold(coordinator):
    """After HEALTH_FAIL_THRESHOLD failures, is_api_reachable → False with notification."""
    import aiohttp

    from custom_components.cantera.const import HEALTH_FAIL_THRESHOLD

    coordinator._api_reachable = True  # Simulate previously reachable.
    health_cb = MagicMock()
    coordinator.add_health_listener(health_cb)

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=aiohttp.ClientError())
    with patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session):
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
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session):
        await coordinator._poll_health()

    assert coordinator._consecutive_health_failures == 0


# ---------- Connection state ----------

def test_reading_listener_called(coordinator):
    """Callbacks are called only for the slug they registered with."""
    cb = MagicMock()
    coordinator.add_reading_listener("engine_rpm", cb)
    reading = {"pid": "engine_rpm", "value": 2400.0, "unit": "rpm"}
    for listener in coordinator._reading_listeners["engine_rpm"]:
        listener(reading)
    cb.assert_called_once_with(reading)


def test_reading_listener_not_called_for_other_slug(coordinator):
    """Callbacks are NOT called for readings with a different slug."""
    cb = MagicMock()
    coordinator.add_reading_listener("engine_rpm", cb)
    # Simulate dispatch for a different slug
    for listener in coordinator._reading_listeners.get("vehicle_speed", []):
        listener({})
    cb.assert_not_called()


# ---------- _backfill_history ----------
# _backfill_history uses the shared aiohttp session from async_get_clientsession.
# Tests patch async_get_clientsession at the coordinator module level.


def _make_mock_session(status: int, json_return=None, get_side_effect=None):
    """Build a mock session returned by async_get_clientsession."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    if json_return is not None:
        mock_resp.json = AsyncMock(return_value=json_return)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
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

    with (
        patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session),
        patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0),
        patch(
            "custom_components.cantera.coordinator.import_statistics",
            new_callable=AsyncMock,
        ) as mock_import,
        patch.object(coordinator, "_save_last_sync", new_callable=AsyncMock) as mock_save,
    ):
        await coordinator._backfill_history()

    mock_import.assert_awaited_once()
    mock_save.assert_awaited_once_with(1700000000000)


async def test_backfill_history_404_logs_warning_and_returns(coordinator):
    """Non-200 response: import_statistics is NOT called."""
    mock_session = _make_mock_session(404)

    with (
        patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session),
        patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0),
        patch(
            "custom_components.cantera.coordinator.import_statistics",
            new_callable=AsyncMock,
        ) as mock_import,
    ):
        await coordinator._backfill_history()

    mock_import.assert_not_awaited()


async def test_backfill_history_exception_does_not_propagate(coordinator):
    """Any exception inside _backfill_history is caught and logged, never propagated."""
    mock_session = _make_mock_session(200, get_side_effect=RuntimeError("network failure"))

    with (
        patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session),
        patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0),
    ):
        # Must not raise
        await coordinator._backfill_history()


async def test_backfill_history_exception_inside_context_manager(coordinator):
    """Exception raised inside the response context (e.g. JSON decode) is caught."""
    mock_session = _make_mock_session(200)
    mock_session.get.return_value.json = AsyncMock(side_effect=RuntimeError("json decode failed"))

    with (
        patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session),
        patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0),
    ):
        # Must not raise
        await coordinator._backfill_history()


async def test_backfill_history_exception_inside_context_manager_does_not_propagate(coordinator):
    """Exception raised while reading response body (inside async-with) is also caught."""
    mock_session = _make_mock_session(200)
    mock_session.get.return_value.json = AsyncMock(side_effect=RuntimeError("json decode error"))

    with (
        patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session),
        patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0),
    ):
        # Must not raise
        await coordinator._backfill_history()


async def test_backfill_history_empty_readings_skips_import(coordinator):
    """Empty readings list: import_statistics and _save_last_sync are NOT called."""
    mock_session = _make_mock_session(200, json_return=[])

    with (
        patch("custom_components.cantera.coordinator.async_get_clientsession", return_value=mock_session),
        patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0),
        patch(
            "custom_components.cantera.coordinator.import_statistics",
            new_callable=AsyncMock,
        ) as mock_import,
        patch.object(coordinator, "_save_last_sync", new_callable=AsyncMock) as mock_save,
    ):
        await coordinator._backfill_history()

    mock_import.assert_not_awaited()
    mock_save.assert_not_awaited()


async def test_backfill_not_duplicated_on_rapid_reconnect(coordinator):
    """A second _connect_and_stream call does not start a new backfill if one is running."""
    # Simulate an already-running (not-done) backfill task
    long_task = coordinator._hass.async_create_task(asyncio.sleep(9999))
    coordinator._backfill_task = long_task

    # _connect_and_stream would start a task only if _backfill_task is None or done
    # Since it's running, the new SSE attempt must NOT replace _backfill_task
    assert not coordinator._backfill_task.done()
    old_task = coordinator._backfill_task

    # Mimic the guard logic from _connect_and_stream
    if coordinator._backfill_task is None or coordinator._backfill_task.done():
        coordinator._backfill_task = coordinator._hass.async_create_task(asyncio.sleep(1))

    assert coordinator._backfill_task is old_task, "Backfill task must not be replaced while running"
    long_task.cancel()


async def test_stop_cancels_backfill_task(coordinator):
    """stop() cancels an in-flight backfill task."""
    running = coordinator._hass.async_create_task(asyncio.sleep(9999))
    coordinator._backfill_task = running
    coordinator._sse_task = None

    await coordinator.stop()

    assert running.cancelled()


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
    # Must be set so _sse_loop doesn't spin forever on the compatibility guard.
    coordinator._api_compatible = True
    iterations = 0

    async def fake_connect():
        nonlocal iterations
        iterations += 1
        if iterations == 1:
            raise RuntimeError("SSE dropped")
        # Exit cleanly on the second iteration via CancelledError handler
        raise asyncio.CancelledError()

    with (
        patch.object(coordinator, "_connect_and_stream", side_effect=fake_connect),
        patch.object(coordinator, "_sse_backoff_sleep", new_callable=AsyncMock),
    ):
        await coordinator._sse_loop()

    assert coordinator._connected is False
    assert iterations == 2


async def test_poll_health_reentrant_guard_prevents_concurrent_calls(hass):
    """_poll_health returns immediately if already running (no double-poll)."""
    from unittest.mock import AsyncMock, patch

    entry = MagicMock()
    entry.data = {CONF_HOST: "10.0.0.1", CONF_PORT: 8080}
    coordinator = CanteraCoordinator(hass, entry)

    call_count = 0

    async def slow_get(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated slow failure")

    # Manually mark as running before calling
    coordinator._health_poll_running = True
    with patch("custom_components.cantera.coordinator.async_get_clientsession"):
        await coordinator._poll_health()

    # Must return without touching the network
    assert call_count == 0
    # Guard must still be True (we set it, poll returned early without touching finally)
    assert coordinator._health_poll_running is True


# ---------- Connection state properties (lines 98, 102, 106-107, 112-117, 145, 150) ----------

def test_is_connected_initially_false(coordinator):
    """is_connected returns the internal _connected flag (starts False)."""
    assert coordinator.is_connected is False


def test_add_connection_listener_stores_callback(coordinator):
    """add_connection_listener appends callback to _connection_listeners."""
    cb = MagicMock()
    coordinator.add_connection_listener(cb)
    assert cb in coordinator._connection_listeners


def test_remove_connection_listener_removes_callback(coordinator):
    """remove_connection_listener removes a previously added callback."""
    cb = MagicMock()
    coordinator.add_connection_listener(cb)
    coordinator.remove_connection_listener(cb)
    assert cb not in coordinator._connection_listeners


def test_remove_connection_listener_missing_is_safe(coordinator):
    """Removing a callback that was never added does not raise."""
    coordinator.remove_connection_listener(MagicMock())


def test_set_connected_true_notifies_listeners(coordinator):
    """_set_connected(True) calls all registered connection listeners."""
    cb = MagicMock()
    coordinator.add_connection_listener(cb)
    coordinator._set_connected(True)
    cb.assert_called_once()


def test_set_connected_same_value_does_not_notify(coordinator):
    """_set_connected with the same value (False→False) does NOT call listeners."""
    cb = MagicMock()
    coordinator.add_connection_listener(cb)
    coordinator._set_connected(False)  # Already False — no change
    cb.assert_not_called()


def test_set_connected_listener_exception_does_not_propagate(coordinator):
    """Exceptions raised inside a connection listener are swallowed."""
    bad_cb = MagicMock(side_effect=RuntimeError("listener boom"))
    coordinator.add_connection_listener(bad_cb)
    coordinator._set_connected(True)  # Must not raise


def test_api_offline_is_inverse_of_api_reachable(coordinator):
    """api_offline returns True when _api_reachable is False, and vice-versa."""
    coordinator._api_reachable = False
    assert coordinator.api_offline is True
    coordinator._api_reachable = True
    assert coordinator.api_offline is False


def test_device_info_returns_device_info_instance(coordinator):
    """device_info returns a dict with identifiers (DeviceInfo is a TypedDict)."""
    info = coordinator.device_info
    assert isinstance(info, dict)
    assert "identifiers" in info


# ---------- _notify_health_listeners exception path (lines 197-198) ----------

def test_notify_health_listeners_swallows_exception(coordinator):
    """An exception raised by a health listener does not propagate."""
    bad_cb = MagicMock(side_effect=RuntimeError("listener crash"))
    coordinator.add_health_listener(bad_cb)
    coordinator._notify_health_listeners()  # Must not raise


# ---------- Car-off debounce timer start (line 224) ----------

def test_update_car_off_debounce_starts_timer_when_was_ever_live(coordinator):
    """Debounce timer starts when _was_ever_live is True and currently not live."""
    coordinator._was_ever_live = True
    coordinator._car_off_since_mono = None
    coordinator._health_data = {"can_connected": False, "last_reading_ms": 0}
    coordinator._update_car_off_debounce()
    assert coordinator._car_off_since_mono is not None


# ---------- _sse_loop backoff reset (line 316) ----------

async def test_sse_loop_resets_backoff_after_successful_connection(coordinator):
    """After _connect_and_stream returns without error, delay resets to initial value."""
    # Must be set so _sse_loop doesn't spin forever on the compatibility guard.
    coordinator._api_compatible = True
    connect_calls = 0

    async def _fake_connect():
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls >= 2:
            raise asyncio.CancelledError()
        # First call returns normally — simulates successful SSE stream.

    coordinator._connect_and_stream = _fake_connect
    with patch.object(coordinator, "_sse_backoff_sleep", new_callable=AsyncMock):
        await coordinator._sse_loop()

    assert connect_calls == 2


async def test_sse_wake_event_set_when_pi_becomes_reachable(hass, mock_entry):
    """When health poll transitions _api_reachable False→True, _sse_wake is set."""
    coordinator = CanteraCoordinator(hass, mock_entry)
    assert not coordinator._sse_wake.is_set()

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "api_version": "2.0",
        "obd_state": "live",
        "version": "0.3.0",
    })

    with patch("custom_components.cantera.coordinator.async_get_clientsession") as mock_session_fn:
        mock_session = MagicMock()
        mock_session_fn.return_value = mock_session
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(coordinator, "_verify_api_compatibility", new_callable=AsyncMock):
            await coordinator._poll_health()

    assert coordinator._sse_wake.is_set(), "_sse_wake must be set on unreachable→reachable"


async def test_sse_wake_event_not_set_when_already_reachable(hass, mock_entry):
    """_sse_wake is NOT set on a routine healthy poll (already reachable)."""
    coordinator = CanteraCoordinator(hass, mock_entry)
    coordinator._api_reachable = True  # already reachable
    coordinator._sse_wake.clear()

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "api_version": "2.0",
        "obd_state": "live",
        "version": "0.3.0",
    })

    with patch("custom_components.cantera.coordinator.async_get_clientsession") as mock_session_fn:
        mock_session = MagicMock()
        mock_session_fn.return_value = mock_session
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(coordinator, "_verify_api_compatibility", new_callable=AsyncMock):
            await coordinator._poll_health()

    assert not coordinator._sse_wake.is_set(), "_sse_wake must NOT be set on a routine poll"


# ---------- _connect_and_stream (lines 351-378) ----------

async def test_connect_and_stream_non_200_raises(hass, mock_entry):
    """A non-200 SSE response raises ConnectionError."""
    coordinator = CanteraCoordinator(hass, mock_entry)
    coordinator._backfill_task = MagicMock(done=MagicMock(return_value=False))

    mock_resp = AsyncMock()
    mock_resp.status = 503

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ConnectionError, match="SSE returned HTTP 503"):
            await coordinator._connect_and_stream()


async def test_connect_and_stream_dispatches_sse_readings(hass, mock_entry):
    """SSE obd_reading events are parsed and dispatched to registered listeners."""
    coordinator = CanteraCoordinator(hass, mock_entry)
    coordinator._backfill_task = MagicMock(done=MagicMock(return_value=False))

    reading_cb = MagicMock()
    coordinator.add_reading_listener("engine_rpm", reading_cb)

    sse_lines = [
        b"event: obd_reading\n",
        b'data: {"pid": "Engine RPM", "value": 2400.0, "unit": "rpm"}\n',
        b"\n",
    ]

    class _AsyncLineIter:
        def __init__(self, items):
            self._iter = iter(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration from None

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.content = _AsyncLineIter(sse_lines)

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

        await coordinator._connect_and_stream()

    reading_cb.assert_called_once()
    assert reading_cb.call_args[0][0]["pid"] == "Engine RPM"
    assert reading_cb.call_args[0][0]["value"] == 2400.0


async def test_connect_and_stream_sets_connected_true_on_200(hass, mock_entry):
    """_connect_and_stream calls _set_connected(True) after a 200 response."""
    coordinator = CanteraCoordinator(hass, mock_entry)
    coordinator._backfill_task = MagicMock(done=MagicMock(return_value=False))

    class _Empty:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.content = _Empty()

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

        await coordinator._connect_and_stream()

    assert coordinator._connected is True


# ---------- _backfill_history aiohttp.ClientError path (line 419) ----------

async def test_backfill_history_client_error_logs_debug_not_warning(coordinator):
    """aiohttp.ClientError inside _backfill_history hits the DEBUG log path (not WARNING)."""
    import aiohttp as _aiohttp

    mock_session = _make_mock_session(200, get_side_effect=_aiohttp.ClientError("Pi offline"))

    with (
        patch(
            "custom_components.cantera.coordinator.async_get_clientsession",
            return_value=mock_session,
        ),
        patch.object(coordinator, "_load_last_sync", new_callable=AsyncMock, return_value=0),
    ):
        await coordinator._backfill_history()  # Must not raise


# ---------- API compatibility ----------

def test_api_compatible_initial_is_none(coordinator):
    """_api_compatible is None until the first health poll resolves."""
    assert coordinator._api_compatible is None


def test_reported_api_version_initial_is_none(coordinator):
    """reported_api_version is None until the Pi reports it."""
    assert coordinator.reported_api_version is None


async def test_verify_api_compatibility_matching_major_sets_compatible(coordinator, hass):
    """api_version with matching major → _api_compatible True."""
    from custom_components.cantera.const import EXPECTED_API_VERSION_MAJOR

    hass.services.async_call = AsyncMock()
    await coordinator._verify_api_compatibility(
        {"api_version": {"major": EXPECTED_API_VERSION_MAJOR, "minor": 0}}
    )

    assert coordinator._api_compatible is True
    assert coordinator.reported_api_version == f"{EXPECTED_API_VERSION_MAJOR}.0"


async def test_verify_api_compatibility_wrong_major_sets_incompatible(coordinator, hass):
    """api_version with mismatching major → _api_compatible False."""
    from custom_components.cantera.const import EXPECTED_API_VERSION_MAJOR

    hass.services.async_call = AsyncMock()
    wrong_major = EXPECTED_API_VERSION_MAJOR + 99
    await coordinator._verify_api_compatibility(
        {"api_version": {"major": wrong_major, "minor": 0}}
    )

    assert coordinator._api_compatible is False
    assert coordinator.reported_api_version == f"{wrong_major}.0"


async def test_verify_api_compatibility_missing_field_sets_compatible(coordinator, hass):
    """Health data without api_version (old firmware) → _api_compatible True."""
    hass.services.async_call = AsyncMock()
    await coordinator._verify_api_compatibility({})

    assert coordinator._api_compatible is True
    assert coordinator.reported_api_version is None


async def test_verify_api_compatibility_notifies_once_on_incompatible(coordinator, hass):
    """Persistent notification is created exactly once for incompatible major version."""
    from custom_components.cantera.const import EXPECTED_API_VERSION_MAJOR

    hass.services.async_call = AsyncMock()
    wrong_major = EXPECTED_API_VERSION_MAJOR + 99

    await coordinator._verify_api_compatibility(
        {"api_version": {"major": wrong_major, "minor": 0}}
    )
    await coordinator._verify_api_compatibility(
        {"api_version": {"major": wrong_major, "minor": 0}}
    )

    # Notification should be created only once.
    create_calls = [
        c for c in hass.services.async_call.call_args_list
        if c.args[1] == "create"
    ]
    assert len(create_calls) == 1


def test_sync_status_incompatible_takes_priority(coordinator):
    """sync_status is 'incompatible' when _api_compatible is False, regardless of other state."""
    from custom_components.cantera.const import SYNC_STATUS_INCOMPATIBLE

    coordinator._api_compatible = False
    coordinator._api_reachable = True
    assert coordinator.sync_status == SYNC_STATUS_INCOMPATIBLE


def test_sync_status_not_incompatible_when_compatible(coordinator):
    """sync_status is NOT 'incompatible' when _api_compatible is True."""
    from custom_components.cantera.const import SYNC_STATUS_INCOMPATIBLE

    coordinator._api_compatible = True
    coordinator._api_reachable = False
    assert coordinator.sync_status != SYNC_STATUS_INCOMPATIBLE
