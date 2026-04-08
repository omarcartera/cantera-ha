"""Coordinator for CANtera — SSE client + history backfill."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable

import aiohttp

from homeassistant.core import HomeAssistant

from .const import (
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
    HISTORY_ENDPOINT,
    LAST_SYNC_ENDPOINT,
    SSE_ENDPOINT,
    SSE_EVENT_TYPE_OBD,
    SSE_RECONNECT_DELAY_S,
)
from .ha_statistics import import_statistics

_LOGGER = logging.getLogger(__name__)


class CanteraCoordinator:
    """Manages SSE connection and history backfill for one CANtera device."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        """Initialise the coordinator."""
        self._hass = hass
        self._host: str = config_entry.data[CONF_HOST]
        self._port: int = config_entry.data[CONF_PORT]
        self._base_url = f"http://{self._host}:{self._port}"
        self._listeners: list[Callable[[dict], None]] = []
        self._sse_task: asyncio.Task | None = None
        self._pid_units: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_reading_listener(self, cb: Callable[[dict], None]) -> None:
        """Register a callback invoked for each live SSE reading."""
        self._listeners.append(cb)

    def start(self) -> None:
        """Start the SSE connection loop."""
        self._sse_task = self._hass.async_create_task(self._sse_loop())

    async def stop(self) -> None:
        """Stop the SSE connection loop."""
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            self._sse_task = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _sse_loop(self) -> None:
        """Connect to SSE stream, reconnect on disconnect."""
        while True:
            try:
                await self._connect_and_stream()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _LOGGER.warning(
                    "SSE connection error: %s — retrying in %ds",
                    exc,
                    SSE_RECONNECT_DELAY_S,
                )
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
            last_sync_ms = await self._get_last_sync(session)
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
                await import_statistics(self.hass, readings, self._pid_units)
                await self._set_last_sync(session, now_ms)
        except Exception:
            _LOGGER.exception("History backfill failed")

    async def _get_last_sync(self, session: aiohttp.ClientSession) -> int:
        """Return last sync timestamp in ms (0 if never synced)."""
        try:
            url = f"{self._base_url}{LAST_SYNC_ENDPOINT}"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ts = data.get("ts")
                    return ts if ts is not None else 0
        except Exception:
            pass
        return 0

    async def _set_last_sync(
        self, session: aiohttp.ClientSession, ts_ms: int
    ) -> None:
        """Write last sync timestamp to Pi."""
        try:
            url = f"{self._base_url}{LAST_SYNC_ENDPOINT}"
            async with session.post(
                url,
                json={"ts": ts_ms},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status not in (200, 204):
                    _LOGGER.debug("last-sync POST returned %d", resp.status)
        except Exception:
            _LOGGER.debug("Failed to update last-sync marker")
