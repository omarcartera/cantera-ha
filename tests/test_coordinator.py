"""Tests for CanteraCoordinator."""
import asyncio
import pytest
from unittest.mock import MagicMock

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


def test_coordinator_init(coordinator):
    """Coordinator initialises with correct defaults."""
    assert coordinator._host == "192.168.1.100"
    assert coordinator._port == 8088
    assert coordinator._listeners == []
    assert coordinator._sse_task is None


def test_add_reading_listener(coordinator):
    """add_reading_listener stores callback."""
    cb = MagicMock()
    coordinator.add_reading_listener(cb)
    assert cb in coordinator._listeners


async def test_start_creates_task(hass, coordinator):
    """start() creates an SSE loop task."""
    coordinator.start()
    assert coordinator._sse_task is not None
    coordinator._sse_task.cancel()
    try:
        await coordinator._sse_task
    except asyncio.CancelledError:
        pass


async def test_stop_cancels_task(hass, coordinator):
    """stop() cancels the SSE task."""
    coordinator.start()
    assert coordinator._sse_task is not None
    await coordinator.stop()
    assert coordinator._sse_task is None


def test_reading_listener_called(coordinator):
    """Callbacks in _listeners are called when _pid_units is updated via SSE."""
    cb = MagicMock()
    coordinator.add_reading_listener(cb)
    reading = {"pid": "engine_rpm", "value": 2400.0, "unit": "rpm"}
    coordinator._pid_units[reading["pid"]] = reading.get("unit", "")
    for listener in coordinator._listeners:
        listener(reading)
    cb.assert_called_once_with(reading)
