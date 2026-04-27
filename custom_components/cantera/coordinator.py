"""Coordinator for CANtera — SSE client + health polling + history backfill."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, TypeVar

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CAR_OFF_DEBOUNCE,
    CONF_HEALTH_POLL_INTERVAL,
    CONF_HOST,
    CONF_PORT,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    HEALTH_ENDPOINT,
    HEALTH_FAIL_THRESHOLD,
    HEALTH_POLL_INTERVAL_S,
    HISTORY_ENDPOINT,
    SSE_ENDPOINT,
    SSE_EVENT_TYPE_BUS_STATS,
    SSE_EVENT_TYPE_OBD,
    SSE_MAX_RECONNECT_DELAY_S,
    SSE_READ_TIMEOUT_S,
    SSE_RECONNECT_DELAY_S,
    SYNC_CAR_OFF_DEBOUNCE_S,
    SYNC_STALE_THRESHOLD_S,
    SYNC_STATUS_API_OFFLINE,
    SYNC_STATUS_CAR_OFF,
    SYNC_STATUS_INCOMPATIBLE,
    SYNC_STATUS_LIVE,
    SYNC_STATUS_SYNCING,
    EXPECTED_API_VERSION_MAJOR,
    MIN_API_VERSION_MINOR,
)
from .ha_statistics import import_statistics

STORAGE_VERSION = 1

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class ListenerRegistry(Generic[_T]):
    """Generic fan-out listener list with add, remove, and notify.

    Eliminates the repetitive add/remove/try-except boilerplate that
    previously appeared six times in ``CanteraCoordinator``.

    Usage::

        reg: ListenerRegistry[dict] = ListenerRegistry("health")
        reg.add(my_callback)
        reg.notify({"can_connected": True})   # calls my_callback({"can_connected": True})
        reg.notify()                           # valid for zero-arg callbacks (T = None)
    """

    def __init__(self, label: str) -> None:
        self._label = label
        self._listeners: list[Callable[..., None]] = []

    def add(self, cb: Callable[..., None]) -> None:
        """Register a listener callback."""
        self._listeners.append(cb)

    def remove(self, cb: Callable[..., None]) -> None:
        """Unregister a listener callback (no-op if not registered)."""
        with contextlib.suppress(ValueError):
            self._listeners.remove(cb)

    def notify(self, *args: Any, **kwargs: Any) -> None:
        """Call every registered listener, logging exceptions instead of raising."""
        for cb in list(self._listeners):
            try:
                cb(*args, **kwargs)
            except Exception:
                _LOGGER.exception("%s listener %r raised an exception", self._label, cb)


class CanteraCoordinator:
    """Manages SSE connection, health polling, and history backfill."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        """Initialise the coordinator."""
        self._hass = hass
        self._config_entry = config_entry
        self._entry_id: str = config_entry.entry_id
        self._host: str = config_entry.data[CONF_HOST]
        self._port: int = config_entry.data[CONF_PORT]
        self._base_url = f"http://{self._host}:{self._port}"
        self._reading_listeners: dict[str, list[Callable[[dict], None]]] = defaultdict(list)
        self._sse_task: asyncio.Task | None = None
        self._pid_units: dict[str, str] = {}
        # Scope storage key to this config entry so two CANtera devices don't
        # share a last-sync timestamp (would cause missed/duplicate backfill).
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{self._entry_id}.last_sync"
        )
        self._connected: bool = False
        self._connection_reg: ListenerRegistry[None] = ListenerRegistry("connection")

        # Health polling state
        self._health_reg: ListenerRegistry[dict] = ListenerRegistry("health")
        self._health_data: dict = {}
        self._consecutive_health_failures: int = 0
        self._api_reachable: bool = False
        self._health_unsub: Callable | None = None
        # True while history backfill is in progress for the current connection.
        self._backfilling: bool = False
        # Task handle for the background backfill so we never double-start it.
        self._backfill_task: asyncio.Task | None = None
        # Set True when the first successful /api/health response arrives.
        self._first_health_received: bool = False
        # Guard against concurrent health poll invocations.
        self._health_poll_running: bool = False
        # Task for the immediate first health poll fired from start().
        self._initial_health_task: asyncio.Task | None = None
        # Monotonic timestamp (time.monotonic()) of when the car-off condition
        # was first detected.  None means the last health poll was live.
        # Used to debounce rapid live→car_off→live oscillations caused by
        # brief ECU keep-alive retries between successful OBD sessions.
        self._car_off_since_mono: float | None = None
        # True once at least one health poll has confirmed a live reading.
        # The car-off debounce is suppressed until we've seen live data so
        # that startup and reconnect windows don't falsely report "live".
        self._was_ever_live: bool = False

        # API contract compatibility state.
        # None = not yet checked (startup), True = compatible, False = incompatible.
        self._api_compatible: bool | None = None
        self._reported_api_version: str | None = None
        self._api_incompatible_notified: bool = False
        # Set once the first compatibility check completes (replaces busy-wait).
        self._api_compat_event: asyncio.Event = asyncio.Event()

        # Firmware update check state (set by firmware_update.py after each poll).
        self._firmware_update_state: str = "not_checked"
        self._firmware_reg: ListenerRegistry[str] = ListenerRegistry("firmware")

        # Bus statistics listeners — notified via SSE 'bus_stats' events.
        self._bus_stats_reg: ListenerRegistry[dict] = ListenerRegistry("bus_stats")

        # Event set by the health poller whenever the Pi transitions from
        # unreachable → reachable.  The SSE reconnect sleep awaits this so that
        # the SSE stream reconnects immediately when the Pi comes back online
        # rather than waiting out the full exponential backoff.
        self._sse_wake: asyncio.Event = asyncio.Event()

        # Last-delivered Mode 09 values — deduplicate to avoid spurious
        # write_ha_state() calls on every health poll (every 5 s).
        self._mode09_cache: dict[str, str | None] = {
            "vin": None,
            "calibration_id": None,
            "cvn": None,
        }

    # ------------------------------------------------------------------
    # Public API — SSE readings
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True when the SSE stream is actively connected."""
        return self._connected

    def add_connection_listener(self, cb: Callable[[], None]) -> None:
        """Register a callback invoked when connection state changes."""
        self._connection_reg.add(cb)

    def remove_connection_listener(self, cb: Callable[[], None]) -> None:
        """Remove a connection state change callback."""
        self._connection_reg.remove(cb)

    def _set_connected(self, value: bool) -> None:
        """Update connection state and notify listeners."""
        if self._connected != value:
            self._connected = value
            self._connection_reg.notify()

    def add_reading_listener(self, slug: str, cb: Callable[[dict], None]) -> None:
        """Register a callback invoked when a reading for ``slug`` arrives."""
        self._reading_listeners[slug].append(cb)

    def remove_reading_listener(self, slug: str, cb: Callable[[dict], None]) -> None:
        """Remove a previously registered reading callback for ``slug``."""
        with contextlib.suppress(ValueError):
            self._reading_listeners[slug].remove(cb)

    # ------------------------------------------------------------------
    # Public API — Health polling
    # ------------------------------------------------------------------

    @property
    def is_api_reachable(self) -> bool:
        """True when /api/health responds successfully."""
        return self._api_reachable

    @property
    def health_data(self) -> dict:
        """Last successful /api/health response (contains can_connected, etc.)."""
        return self._health_data

    @property
    def api_offline(self) -> bool:
        """True when /api/health is unreachable."""
        return not self._api_reachable

    @property
    def device_info(self) -> DeviceInfo:
        """Shared device info so all CANtera entities group under one device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"cantera_vehicle_{self._entry_id}")},
            name=f"CANtera Vehicle ({self._host})",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @property
    def reported_api_version(self) -> str | None:
        """The ``major.minor`` API version string reported by the Pi, or ``None``."""
        return self._reported_api_version

    @property
    def sync_status(self) -> str:
        """Composite data-update status for the sync-status sensor.

        States (in priority order):
        - ``incompatible``: Pi API major version does not match integration.
        - ``api_offline``: /api/health is unreachable (Pi is down / no network).
        - ``syncing``:     API reachable, RPi reports syncing.
        - ``car_off``:     API reachable, RPi reports car_off.
        - ``live``:        API reachable, RPi reports live.

        Since API minor version 6 the RPi owns ``syncing``, ``live``, and
        ``car_off`` via the ``sync_status`` field in ``/api/health``.  For
        older firmware we fall back to the legacy heuristic (backfill →
        syncing, car-off debounce from ``can_connected`` / ``last_reading_ms``).
        """
        if self._api_compatible is False:
            return SYNC_STATUS_INCOMPATIBLE
        if not self._api_reachable:
            return SYNC_STATUS_API_OFFLINE

        # Trust RPi-owned status when available (API minor >= 6).
        pi_status = self._health_data.get("sync_status")
        if pi_status is not None:
            if pi_status == "syncing":
                return SYNC_STATUS_SYNCING
            if pi_status == "live":
                return SYNC_STATUS_LIVE
            if pi_status == "car_off":
                return SYNC_STATUS_CAR_OFF
            # Unknown value — fall through to legacy logic.

        # Legacy fallback for firmware that does not report sync_status.
        if self._backfilling:
            return SYNC_STATUS_SYNCING
        if (
            self._car_off_since_mono is not None
            and time.monotonic() - self._car_off_since_mono >= self.car_off_debounce_s
        ):
            return SYNC_STATUS_CAR_OFF
        return SYNC_STATUS_LIVE

    @property
    def health_poll_interval_s(self) -> int:
        """Health poll interval in seconds, from options or const default."""
        return int(
            self._config_entry.options.get(
                CONF_HEALTH_POLL_INTERVAL, HEALTH_POLL_INTERVAL_S
            )
        )

    @property
    def car_off_debounce_s(self) -> int:
        """Car-off debounce duration in seconds, from options or const default."""
        return int(
            self._config_entry.options.get(
                CONF_CAR_OFF_DEBOUNCE, SYNC_CAR_OFF_DEBOUNCE_S
            )
        )

    def add_health_listener(self, cb: Callable[[dict], None]) -> None:
        """Register a callback invoked on each health poll state change."""
        self._health_reg.add(cb)

    def remove_health_listener(self, cb: Callable[[dict], None]) -> None:
        """Remove a health poll callback."""
        self._health_reg.remove(cb)

    def _notify_health_listeners(self) -> None:
        self._health_reg.notify(self._health_data)

    # ------------------------------------------------------------------
    # Firmware update state
    # ------------------------------------------------------------------

    @property
    def firmware_update_state(self) -> str:
        """Return the current firmware update check state.

        Possible values: ``not_checked``, ``checking``, ``up_to_date``,
        ``update_available``, ``check_failed``.
        """
        return self._firmware_update_state

    def set_firmware_update_state(self, state: str) -> None:
        """Update firmware check state and notify registered listeners."""
        self._firmware_update_state = state
        self._firmware_reg.notify(state)

    def add_firmware_state_listener(self, cb: Callable[[str], None]) -> None:
        """Register a callback invoked when firmware update state changes."""
        self._firmware_reg.add(cb)

    def remove_firmware_state_listener(self, cb: Callable[[str], None]) -> None:
        """Remove a firmware state change callback."""
        self._firmware_reg.remove(cb)

    def add_bus_stats_listener(self, cb: Callable[[dict], None]) -> None:
        """Register a callback invoked on each SSE 'bus_stats' event."""
        self._bus_stats_reg.add(cb)

    def remove_bus_stats_listener(self, cb: Callable[[dict], None]) -> None:
        """Remove a bus stats callback."""
        self._bus_stats_reg.remove(cb)

    def _notify_bus_stats_listeners(self, stats: dict) -> None:
        self._bus_stats_reg.notify(stats)

    def _notify_mode09_from_health(self) -> None:
        """Deliver Mode 09 vehicle identity to registered reading listeners.

        The health endpoint carries ``vin``, ``calibration_id``, and ``cvn``
        fields since API minor version 4.  This method maps them to the same
        slug → callback path used by the SSE stream so that Mode 09 HA sensors
        are populated without a separate SSE event type.

        Notifications are deduplicated: a listener is only called when the
        value has changed since the last delivery.
        """
        # Mapping: health field → Mode 09 PID display name (must match const.py).
        field_to_name = {
            "vin": "Vehicle Identification Number (VIN)",
            "calibration_id": "Calibration ID (CalID)",
            "cvn": "Calibration Verification Number (CVN)",
        }
        now_ms = int(time.time() * 1000)
        for field, pid_name in field_to_name.items():
            value = self._health_data.get(field)
            if value is None:
                continue
            value_str = str(value)
            if value_str == self._mode09_cache.get(field):
                continue  # unchanged — skip
            self._mode09_cache[field] = value_str
            slug = pid_name.lower().replace(" ", "_")
            reading = {"pid": pid_name, "value": value_str, "unit": "", "ts": now_ms}
            for cb in list(self._reading_listeners.get(slug, [])):
                try:
                    cb(reading)
                except Exception:
                    _LOGGER.exception("Mode 09 reading listener %r raised an exception", cb)

    def _update_car_off_debounce(self) -> None:
        """Update the car-off debounce timer from the latest health data.

        Must be called after ``_health_data`` is updated on each successful
        health poll, before notifying listeners so that ``sync_status`` is
        already correct when callbacks read it.

        If the condition is live: clear the timer (keep / return to "live").
        If not live and we *have* been live before: start the normal debounce
        window (``car_off_debounce_s``) so brief ECU gaps don't flicker.
        If not live and we have *never* been live: report ``car_off``
        immediately by back-dating the timer past the debounce threshold.
        """
        connected = self._health_data.get("can_connected", False)
        last_ms: int = self._health_data.get("last_reading_ms", 0)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        is_live = (
            connected
            and self._connected
            and last_ms > 0
            and (now_ms - last_ms) <= SYNC_STALE_THRESHOLD_S * 1000
        )
        if is_live:
            self._was_ever_live = True
            self._car_off_since_mono = None
        elif self._car_off_since_mono is None:
            if self._was_ever_live:
                # Normal debounce: brief gaps (ECU keep-alive) stay "live".
                self._car_off_since_mono = time.monotonic()
            else:
                # Never been live — report car_off immediately, no debounce.
                self._car_off_since_mono = time.monotonic() - self.car_off_debounce_s

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the SSE connection loop and health polling."""
        self._sse_task = self._hass.async_create_task(self._sse_loop())
        self._health_unsub = async_track_time_interval(
            self._hass,
            self._poll_health,
            timedelta(seconds=self.health_poll_interval_s),
        )
        # Run an immediate first poll without waiting for the interval.
        self._initial_health_task = self._hass.async_create_task(self._poll_health())

    async def stop(self) -> None:
        """Stop the SSE loop, health polling, and any in-progress backfill."""
        if self._health_unsub is not None:
            self._health_unsub()
            self._health_unsub = None
        if self._initial_health_task and not self._initial_health_task.done():
            self._initial_health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._initial_health_task
            self._initial_health_task = None
        self._set_connected(False)
        self._api_reachable = False
        if self._backfill_task and not self._backfill_task.done():
            self._backfill_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._backfill_task
            self._backfill_task = None
        if self._sse_task:
            self._sse_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sse_task
            self._sse_task = None

    # ------------------------------------------------------------------
    # Health polling
    # ------------------------------------------------------------------

    async def _poll_health(self, _now=None) -> None:
        """Poll /api/health and update reachability state."""
        if self._health_poll_running:
            return
        self._health_poll_running = True
        _success = False
        try:
            url = f"{self._base_url}{HEALTH_ENDPOINT}"
            try:
                session = async_get_clientsession(self._hass)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        self._health_data = await resp.json()
                        self._consecutive_health_failures = 0
                        if not self._api_reachable:
                            self._api_reachable = True
                            # Wake the SSE loop so it reconnects immediately
                            # instead of waiting out the current backoff sleep.
                            self._sse_wake.set()
                        self._first_health_received = True
                        # Only run legacy car-off debounce when the Pi does not
                        # own sync_status (firmware < API minor 6).
                        if self._health_data.get("sync_status") is None:
                            self._update_car_off_debounce()
                        # Propagate firmware update status on every health poll
                        # (every 5 s) rather than waiting for the hourly scan.
                        fw_status = self._health_data.get("firmware_update_status")
                        if fw_status is not None:
                            self.set_firmware_update_state(fw_status)
                        # Deliver Mode 09 vehicle identity (VIN/CalID/CVN) via the
                        # same reading-listener path used by SSE OBD readings.
                        # The health endpoint carries these fields since API minor 4.
                        # Only notify when the value is present and has changed to
                        # avoid spurious write_ha_state() calls on every 5 s poll.
                        self._notify_mode09_from_health()
                        self._notify_health_listeners()
                        _success = True
            except (TimeoutError, aiohttp.ClientError, OSError):
                _LOGGER.debug("Health poll request failed", exc_info=True)

            if _success:
                # Run compatibility check outside the network error handler so
                # that notification failures don't affect reachability tracking.
                await self._verify_api_compatibility(self._health_data)
                return

            self._consecutive_health_failures += 1
            if (
                self._consecutive_health_failures >= HEALTH_FAIL_THRESHOLD
                and self._api_reachable
            ):
                self._api_reachable = False
                self._health_data = {}
                # Suspend the car-off debounce timer during API outages.
                # We have no fresh evidence either way, so don't let stale
                # elapsed time count toward the debounce threshold.
                self._car_off_since_mono = None
                self._notify_health_listeners()
        finally:
            self._health_poll_running = False

    async def _verify_api_compatibility(self, health_data: dict) -> None:
        """Check ``api_version`` in health data against the expected major version.

        Updates ``_api_compatible`` and ``_reported_api_version``.  When the
        major version mismatches, the active SSE task is cancelled and restarted
        so that ``_sse_loop`` re-evaluates the compatibility gate immediately.
        Notification failures are logged but do not affect reachability state.
        """
        api_ver = health_data.get("api_version")

        if api_ver is None:
            # Old firmware that predates the api_version field.  Give the
            # benefit of the doubt and log once so the user knows to upgrade.
            if self._api_compatible is None:
                _LOGGER.warning(
                    "Pi firmware does not report api_version — "
                    "update Pi firmware to enable contract verification"
                )
            self._api_compatible = True
            self._api_compat_event.set()
            return

        major = api_ver.get("major", 0)
        minor = api_ver.get("minor", 0)
        self._reported_api_version = f"{major}.{minor}"

        if minor < MIN_API_VERSION_MINOR:
            _LOGGER.info(
                "Pi API minor version %s.%s is below integration minimum %s.%s",
                major,
                minor,
                EXPECTED_API_VERSION_MAJOR,
                MIN_API_VERSION_MINOR,
            )

        was_compatible = self._api_compatible
        self._api_compatible = major == EXPECTED_API_VERSION_MAJOR
        self._api_compat_event.set()

        if not self._api_compatible:
            # Cancel the active SSE task so _sse_loop immediately re-evaluates
            # the compatibility gate instead of continuing to consume events.
            if self._sse_task is not None and not self._sse_task.done():
                self._sse_task.cancel()
                self._sse_task = self._hass.async_create_task(self._sse_loop())

            if not self._api_incompatible_notified:
                self._api_incompatible_notified = True
                try:
                    await self._hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": "CANtera API Incompatible",
                            "message": (
                                f"The CANtera Pi firmware reports API version "
                                f"{major}.{minor}, but this integration expects "
                                f"API version {EXPECTED_API_VERSION_MAJOR}.x. "
                                "Update both Pi firmware and HA integration to "
                                "matching versions."
                            ),
                            "notification_id": f"cantera_api_incompatible_{self._entry_id}",
                        },
                    )
                except Exception:
                    _LOGGER.exception(
                        "Failed to create API incompatibility notification"
                    )
        elif was_compatible is False:
            # Major version became compatible again (e.g. firmware rollback).
            self._api_incompatible_notified = False
            try:
                await self._hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": f"cantera_api_incompatible_{self._entry_id}"},
                )
            except Exception:
                _LOGGER.debug("Failed to dismiss API incompatibility notification")

    # ------------------------------------------------------------------
    # Internal — SSE
    # ------------------------------------------------------------------

    async def _sse_loop(self) -> None:
        """Connect to SSE stream, reconnect with exponential backoff on error."""
        delay = SSE_RECONNECT_DELAY_S
        while True:
            # Block until the first health poll resolves compatibility (startup
            # guard against the race where SSE starts before health is checked).
            # 60-second timeout prevents indefinite blocking if health poll never succeeds.
            if self._api_compatible is None:
                try:
                    await asyncio.wait_for(self._api_compat_event.wait(), timeout=60)
                except asyncio.TimeoutError:
                    _LOGGER.warning("API compatibility check timed out; proceeding assuming compatible")
                    self._api_compatible = True

            # Hard-block when API major version is explicitly incompatible.
            if self._api_compatible is False:
                _LOGGER.error(
                    "SSE stream blocked: Pi API version incompatible with integration"
                )
                self._set_connected(False)
                await asyncio.sleep(30)
                continue

            try:
                await self._connect_and_stream()
                # Successful connection — reset backoff.
                delay = SSE_RECONNECT_DELAY_S
            except asyncio.CancelledError:
                self._set_connected(False)
                return
            except Exception as exc:
                _LOGGER.warning(
                    "SSE connection error: %s — retrying in %ds",
                    exc,
                    delay,
                )
                self._set_connected(False)
            await self._sse_backoff_sleep(delay)
            delay = min(delay * 2, SSE_MAX_RECONNECT_DELAY_S)

    async def _sse_backoff_sleep(self, seconds: float) -> None:
        """Sleep for up to ``seconds``, waking immediately if the Pi comes back online.

        The health poller sets ``_sse_wake`` when the Pi transitions from
        unreachable → reachable, which cancels this sleep so the SSE loop
        reconnects without waiting out the remaining backoff window.
        """
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._sse_wake.wait(), timeout=seconds)
        self._sse_wake.clear()

    async def _connect_and_stream(self) -> None:
        """Start backfill concurrently then stream live SSE data.

        Backfill runs as a background task so the SSE stream starts immediately
        — this lets live data flow in while historical gaps are being filled,
        maximising use of the potentially short window we have wifi access.

        A guard prevents a second backfill from starting if one is already
        running from a previous (quickly-lost) connection attempt.

        ``sock_read=SSE_READ_TIMEOUT_S`` detects dead TCP connections that
        arise when the Pi is power-killed (e.g. car cuts power) without a
        clean TCP FIN.  The Pi firmware sends an SSE keepalive comment every
        15 s, so the 45 s timeout fires only when the stream has been truly
        silent for three keepalive periods — well beyond any normal quiet gap.
        """
        url = f"{self._base_url}{SSE_ENDPOINT}"
        timeout = aiohttp.ClientTimeout(connect=10, sock_read=SSE_READ_TIMEOUT_S)

        # Launch backfill concurrently, but only if not already in flight.
        if self._backfill_task is None or self._backfill_task.done():
            self._backfill_task = self._hass.async_create_task(
                self._backfill_history()
            )

        _LOGGER.info("Connecting to CANtera SSE stream at %s", url)
        session = async_get_clientsession(self._hass)
        async with session.get(url, timeout=timeout) as resp:
                if resp.status != 200:
                    raise ConnectionError(f"SSE returned HTTP {resp.status}")
                self._set_connected(True)

                event_type = None
                async for line in resp.content:
                    text = line.decode("utf-8").rstrip("\n\r")
                    if text.startswith("event:"):
                        event_type = text[6:].strip()
                    elif text.startswith("data:"):
                        data_str = text[5:].strip()
                        if event_type == SSE_EVENT_TYPE_OBD:
                            try:
                                reading = json.loads(data_str)
                                pid = reading["pid"]
                                self._pid_units[pid] = reading.get("unit", "")
                                slug = pid.lower().replace(" ", "_")
                                listeners = self._reading_listeners.get(slug, [])
                                if not listeners:
                                    _LOGGER.debug(
                                        "No SSE listener registered for PID slug %r (pid=%r)",
                                        slug, pid,
                                    )
                                for cb in list(listeners):
                                    try:
                                        cb(reading)
                                    except Exception:
                                        _LOGGER.exception(
                                            "Reading listener %r raised an exception", cb
                                        )
                            except (json.JSONDecodeError, KeyError):
                                _LOGGER.debug("Malformed SSE data: %s", data_str)
                        elif event_type == SSE_EVENT_TYPE_BUS_STATS:
                            try:
                                stats = json.loads(data_str)
                                self._notify_bus_stats_listeners(stats)
                            except json.JSONDecodeError:
                                _LOGGER.debug("Malformed bus_stats SSE data: %s", data_str)
                    elif text == "":
                        event_type = None

    async def _backfill_history(self) -> None:
        """Fetch /api/history for the gap since last sync, import stats.

        Uses its own aiohttp session so it can run concurrently with the SSE
        stream on a separate connection.
        """
        self._backfilling = True
        self._notify_health_listeners()
        try:
            last_sync_ms = await self._load_last_sync()
            now_ms = int(datetime.now(UTC).timestamp() * 1000)

            history_url = (
                f"{self._base_url}{HISTORY_ENDPOINT}"
                f"?start={last_sync_ms}&end={now_ms}"
            )
            session = async_get_clientsession(self._hass)
            async with session.get(
                history_url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("History endpoint returned %d", resp.status)
                    return
                readings = await resp.json()

            if readings:
                _LOGGER.info(
                    "Importing %d historical readings into HA statistics",
                    len(readings),
                )
                for r in readings:
                    self._pid_units[r["pid"]] = r.get("unit", "")
                await import_statistics(self._hass, readings, self._pid_units, self._entry_id)

                last_imported_ts = max(r["ts"] for r in readings)
                await self._save_last_sync(last_imported_ts)
        except (TimeoutError, aiohttp.ClientError) as exc:
            # Pi offline or unreachable — expected during startup or when the car
            # is off.  Log at DEBUG so HA logs stay clean.
            _LOGGER.debug("History backfill skipped (Pi not reachable): %s", exc)
        except Exception:
            _LOGGER.warning("History backfill failed unexpectedly", exc_info=True)
        finally:
            self._backfilling = False
            self._notify_health_listeners()

    async def _load_last_sync(self) -> int:
        """Load last sync timestamp from HA storage (ms, 0 if never synced)."""
        data = await self._store.async_load()
        if data is None:
            return 0
        return data.get("ts", 0)

    async def _save_last_sync(self, ts_ms: int) -> None:
        """Persist last sync timestamp to HA storage."""
        await self._store.async_save({"ts": ts_ms})
