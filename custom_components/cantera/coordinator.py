"""Coordinator for CANtera — SSE client + health polling + history backfill."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
    HEALTH_ENDPOINT,
    HEALTH_FAIL_THRESHOLD,
    HEALTH_POLL_INTERVAL_S,
    HISTORY_ENDPOINT,
    SSE_ENDPOINT,
    SSE_EVENT_TYPE_OBD,
    SSE_RECONNECT_DELAY_S,
)
from .ha_statistics import import_statistics

STORAGE_KEY = f"{DOMAIN}.last_sync"
STORAGE_VERSION = 1

_LOGGER = logging.getLogger(__name__)


class CanteraCoordinator:
    """Manages SSE connection, health polling, and history backfill."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        """Initialise the coordinator."""
        self._hass = hass
        self._host: str = config_entry.data[CONF_HOST]
        self._port: int = config_entry.data[CONF_PORT]
        self._base_url = f"http://{self._host}:{self._port}"
        self._listeners: list[Callable[[dict], None]] = []
        self._sse_task: asyncio.Task | None = None
        self._pid_units: dict[str, str] = {}
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._connected: bool = False
        self._connection_listeners: list[Callable[[], None]] = []

        # Health polling state
        self._health_listeners: list[Callable[[dict], None]] = []
        self._health_data: dict = {}
        self._consecutive_health_failures: int = 0
        self._api_reachable: bool = False
        self._health_unsub: Callable | None = None

    # ------------------------------------------------------------------
    # Public API — SSE readings
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True when the SSE stream is actively connected."""
        return self._connected

    def add_connection_listener(self, cb: Callable[[], None]) -> None:
        """Register a callback invoked when connection state changes."""
        self._connection_listeners.append(cb)

    def remove_connection_listener(self, cb: Callable[[], None]) -> None:
        """Remove a connection state change callback."""
        try:
            self._connection_listeners.remove(cb)
        except ValueError:
            pass

    def _set_connected(self, value: bool) -> None:
        """Update connection state and notify listeners."""
        if self._connected != value:
            self._connected = value
            for cb in self._connection_listeners:
                cb()

    def add_reading_listener(self, cb: Callable[[dict], None]) -> None:
        """Register a callback invoked for each live SSE reading."""
        self._listeners.append(cb)

    def remove_reading_listener(self, cb: Callable[[dict], None]) -> None:
        """Remove a previously registered reading callback."""
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

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

    def add_health_listener(self, cb: Callable[[dict], None]) -> None:
        """Register a callback invoked on each health poll state change."""
        self._health_listeners.append(cb)

    def remove_health_listener(self, cb: Callable[[dict], None]) -> None:
        """Remove a health poll callback."""
        try:
            self._health_listeners.remove(cb)
        except ValueError:
            pass

    def _notify_health_listeners(self) -> None:
        for cb in self._health_listeners:
            cb(self._health_data)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the SSE connection loop and health polling."""
        self._sse_task = self._hass.async_create_task(self._sse_loop())
        self._health_unsub = async_track_time_interval(
            self._hass,
            self._poll_health,
            timedelta(seconds=HEALTH_POLL_INTERVAL_S),
        )
        # Run an immediate first poll without waiting for the interval.
        self._hass.async_create_task(self._poll_health())

    async def stop(self) -> None:
        """Stop the SSE loop and health polling."""
        if self._health_unsub is not None:
            self._health_unsub()
            self._health_unsub = None
        self._set_connected(False)
        self._api_reachable = False
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            self._sse_task = None

    # ------------------------------------------------------------------
    # Health polling
    # ------------------------------------------------------------------

    async def _poll_health(self, _now=None) -> None:
        """Poll /api/health and update reachability state."""
        url = f"{self._base_url}{HEALTH_ENDPOINT}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    if resp.status == 200:
                        self._health_data = await resp.json()
                        self._consecutive_health_failures = 0
                        if not self._api_reachable:
                            self._api_reachable = True
                        self._notify_health_listeners()
                        return
        except Exception:
            pass

        self._consecutive_health_failures += 1
        if (
            self._consecutive_health_failures >= HEALTH_FAIL_THRESHOLD
            and self._api_reachable
        ):
            self._api_reachable = False
            self._health_data = {}
            self._notify_health_listeners()

    # ------------------------------------------------------------------
    # Internal — SSE
    # ------------------------------------------------------------------

    async def _sse_loop(self) -> None:
        """Connect to SSE stream, reconnect on disconnect."""
        while True:
            try:
                await self._connect_and_stream()
            except asyncio.CancelledError:
                self._set_connected(False)
                return
            except Exception as exc:
                _LOGGER.warning(
                    "SSE connection error: %s — retrying in %ds",
                    exc,
                    SSE_RECONNECT_DELAY_S,
                )
                self._set_connected(False)
            await asyncio.sleep(SSE_RECONNECT_DELAY_S)

    async def _connect_and_stream(self) -> None:
        """Single SSE connection attempt: backfill history, then stream."""
        url = f"{self._base_url}{SSE_ENDPOINT}"
        timeout = aiohttp.ClientTimeout(connect=10, sock_read=None)

        async with aiohttp.ClientSession() as session:
            await self._backfill_history(session)

            _LOGGER.info("Connecting to CANtera SSE stream at %s", url)
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
                                self._pid_units[reading["pid"]] = reading.get(
                                    "unit", ""
                                )
                                for cb in self._listeners:
                                    cb(reading)
                            except (json.JSONDecodeError, KeyError):
                                _LOGGER.debug("Malformed SSE data: %s", data_str)
                    elif text == "":
                        event_type = None

    async def _backfill_history(
        self, session: aiohttp.ClientSession
    ) -> None:
        """Fetch /api/history for the gap since last sync, import stats."""
        try:
            last_sync_ms = await self._load_last_sync()
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

            history_url = (
                f"{self._base_url}{HISTORY_ENDPOINT}"
                f"?start={last_sync_ms}&end={now_ms}"
            )
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
                await import_statistics(self._hass, readings, self._pid_units)

                last_imported_ts = max(r["ts"] for r in readings)
                await self._save_last_sync(last_imported_ts)
        except Exception:
            _LOGGER.exception("History backfill failed")

    async def _load_last_sync(self) -> int:
        """Load last sync timestamp from HA storage (ms, 0 if never synced)."""
        data = await self._store.async_load()
        if data is None:
            return 0
        return data.get("ts", 0)

    async def _save_last_sync(self, ts_ms: int) -> None:
        """Persist last sync timestamp to HA storage."""
        await self._store.async_save({"ts": ts_ms})
