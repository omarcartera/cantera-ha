"""Tests for ha_statistics module."""
from unittest.mock import AsyncMock, call, patch

from homeassistant.components.recorder.models import StatisticMeanType

from custom_components.cantera.ha_statistics import (
    BUCKET_S,
    _bucket_start,
    aggregate_readings,
    build_statistic_ids,
    import_statistics,
)


def test_bucket_start_rounds_down():
    """_bucket_start should round timestamps down to bucket boundary."""
    ts_ms = (BUCKET_S * 3 + 42) * 1000  # 3 full buckets + 42 seconds
    result = _bucket_start(ts_ms)
    assert result == BUCKET_S * 3


def test_bucket_start_at_boundary():
    ts_ms = BUCKET_S * 5 * 1000
    assert _bucket_start(ts_ms) == BUCKET_S * 5


def test_aggregate_readings_empty():
    assert aggregate_readings([]) == {}


def test_aggregate_readings_single():
    readings = [{"pid": "engine_rpm", "ts": 0, "value": 2000.0, "unit": "rpm"}]
    result = aggregate_readings(readings)
    assert "engine_rpm" in result
    assert len(result["engine_rpm"]) == 1
    bucket = result["engine_rpm"][0]
    assert bucket["mean"] == 2000.0
    assert bucket["min"] == 2000.0
    assert bucket["max"] == 2000.0


def test_aggregate_readings_multiple_same_bucket():
    bucket_ts = BUCKET_S * 10
    readings = [
        {"pid": "engine_rpm", "ts": (bucket_ts + 1) * 1000,
         "value": 1000.0, "unit": "rpm"},
        {"pid": "engine_rpm", "ts": (bucket_ts + 2) * 1000,
         "value": 3000.0, "unit": "rpm"},
    ]
    result = aggregate_readings(readings)
    bucket = result["engine_rpm"][0]
    assert bucket["mean"] == 2000.0
    assert bucket["min"] == 1000.0
    assert bucket["max"] == 3000.0


def test_aggregate_readings_multiple_pids():
    readings = [
        {"pid": "engine_rpm", "ts": 0, "value": 2000.0, "unit": "rpm"},
        {"pid": "vehicle_speed", "ts": 0, "value": 60.0, "unit": "km/h"},
    ]
    result = aggregate_readings(readings)
    assert "engine_rpm" in result
    assert "vehicle_speed" in result


def test_aggregate_readings_multiple_buckets():
    """Readings spanning two buckets produce two bucket entries."""
    b1 = BUCKET_S * 1
    b2 = BUCKET_S * 2
    readings = [
        {"pid": "rpm", "ts": (b1 + 1) * 1000, "value": 1000.0, "unit": "rpm"},
        {"pid": "rpm", "ts": (b2 + 1) * 1000, "value": 2000.0, "unit": "rpm"},
    ]
    result = aggregate_readings(readings)
    assert len(result["rpm"]) == 2
    assert result["rpm"][0]["start"] == b1
    assert result["rpm"][1]["start"] == b2


def test_aggregate_readings_sorted_by_bucket():
    """Bucket entries should be sorted by start time."""
    b2 = BUCKET_S * 2
    b1 = BUCKET_S * 1
    readings = [
        {"pid": "rpm", "ts": (b2 + 1) * 1000, "value": 200.0, "unit": "rpm"},
        {"pid": "rpm", "ts": (b1 + 1) * 1000, "value": 100.0, "unit": "rpm"},
    ]
    result = aggregate_readings(readings)
    starts = [b["start"] for b in result["rpm"]]
    assert starts == sorted(starts)


# ---------------------------------------------------------------------------
# import_statistics (covers lines 59-91)
# ---------------------------------------------------------------------------


async def test_import_statistics_empty_readings_is_noop(hass):
    """import_statistics with empty readings calls nothing."""
    with patch(
        "custom_components.cantera.ha_statistics.async_add_external_statistics"
    ) as mock_add:
        await import_statistics(hass, [], {})
    mock_add.assert_not_called()


async def test_import_statistics_calls_add_external_statistics(hass):
    """import_statistics builds correct metadata and passes it to HA."""

    readings = [
        {"pid": "Engine RPM", "ts": BUCKET_S * 1000, "value": 2500.0, "unit": "rpm"},
    ]
    pid_units = {"Engine RPM": "rpm"}

    with patch(
        "custom_components.cantera.ha_statistics.async_add_external_statistics"
    ) as mock_add:
        await import_statistics(hass, readings, pid_units, "test_entry")

    mock_add.assert_called_once()
    _, metadata, stats = mock_add.call_args.args
    assert metadata["name"] == "Engine RPM"
    assert metadata["unit_of_measurement"] == "rpm"
    assert metadata["mean_type"] == StatisticMeanType.ARITHMETIC
    assert metadata["unit_class"] is None
    assert metadata["has_sum"] is False
    assert "test_entry" in metadata["statistic_id"]
    assert len(stats) == 1
    assert stats[0]["mean"] == 2500.0


async def test_import_statistics_no_unit_sets_none(hass):
    """import_statistics sets unit_of_measurement to None when unit is empty string."""

    readings = [{"pid": "custom_pid", "ts": BUCKET_S * 1000, "value": 42.0, "unit": ""}]

    with patch(
        "custom_components.cantera.ha_statistics.async_add_external_statistics"
    ) as mock_add:
        await import_statistics(hass, readings, {"custom_pid": ""}, "test_entry")

    _, metadata, _ = mock_add.call_args.args
    assert metadata["unit_of_measurement"] is None
    assert "test_entry" in metadata["statistic_id"]


async def test_import_statistics_exception_does_not_crash(hass):
    """Exception in async_add_external_statistics is caught; no crash."""

    readings = [
        {"pid": "Engine RPM", "ts": BUCKET_S * 1000, "value": 1000.0, "unit": "rpm"},
    ]

    with patch(
        "custom_components.cantera.ha_statistics.async_add_external_statistics",
        side_effect=RuntimeError("recorder unavailable"),
    ):
        await import_statistics(hass, readings, {"Engine RPM": "rpm"}, "test_entry")


async def test_import_statistics_multiple_pids(hass):
    """import_statistics imports stats for each unique PID."""

    readings = [
        {"pid": "Engine RPM", "ts": BUCKET_S * 1000, "value": 2000.0, "unit": "rpm"},
        {"pid": "Vehicle Speed", "ts": BUCKET_S * 1000, "value": 80.0, "unit": "km/h"},
    ]
    pid_units = {"Engine RPM": "rpm", "Vehicle Speed": "km/h"}

    with patch(
        "custom_components.cantera.ha_statistics.async_add_external_statistics"
    ) as mock_add:
        await import_statistics(hass, readings, pid_units, "test_entry")

    assert mock_add.call_count == 2
    for call in mock_add.call_args_list:
        _, metadata, _ = call.args
        assert "test_entry" in metadata["statistic_id"]


# ---------------------------------------------------------------------------
# build_statistic_ids
# ---------------------------------------------------------------------------

def test_build_statistic_ids_formats_correctly():
    """build_statistic_ids returns domain-prefixed, lower-snake IDs scoped to entry."""
    from custom_components.cantera.const import DOMAIN
    ids = build_statistic_ids(["Engine RPM", "Vehicle Speed"], "entry_1")
    assert ids == [f"{DOMAIN}_entry_1:engine_rpm", f"{DOMAIN}_entry_1:vehicle_speed"]


def test_build_statistic_ids_empty():
    ids = build_statistic_ids([], "entry_1")
    assert ids == []


def test_build_statistic_ids_already_lowercase():
    from custom_components.cantera.const import DOMAIN
    ids = build_statistic_ids(["coolant_temp"], "entry_1")
    assert ids == [f"{DOMAIN}_entry_1:coolant_temp"]


# ---------------------------------------------------------------------------
# Concurrency / event-loop priority (these guard the asyncio.to_thread and
# yield-between-PID behaviours added to keep the SSE loop responsive)
# ---------------------------------------------------------------------------


async def test_import_statistics_uses_thread_for_aggregation(hass):
    """aggregate_readings must run in a thread pool, not on the event loop."""
    readings = [
        {"pid": "Engine RPM", "ts": BUCKET_S * 1000, "value": 2000.0, "unit": "rpm"},
    ]
    with patch(
        "custom_components.cantera.ha_statistics.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value={"Engine RPM": [{"start": BUCKET_S, "mean": 2000.0, "min": 2000.0, "max": 2000.0}]},
    ) as mock_thread, patch(
        "custom_components.cantera.ha_statistics.async_add_external_statistics"
    ):
        await import_statistics(hass, readings, {"Engine RPM": "rpm"}, "test_entry")

    mock_thread.assert_awaited_once_with(aggregate_readings, readings)


async def test_import_statistics_yields_between_pids(hass):
    """asyncio.sleep(0) must be awaited once per PID to yield to the event loop."""
    readings = [
        {"pid": "Engine RPM", "ts": BUCKET_S * 1000, "value": 2000.0, "unit": "rpm"},
        {"pid": "Vehicle Speed", "ts": BUCKET_S * 1000, "value": 80.0, "unit": "km/h"},
    ]
    pid_units = {"Engine RPM": "rpm", "Vehicle Speed": "km/h"}

    sleep_calls: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with patch(
        "custom_components.cantera.ha_statistics.asyncio.sleep",
        side_effect=record_sleep,
    ), patch(
        "custom_components.cantera.ha_statistics.async_add_external_statistics"
    ):
        await import_statistics(hass, readings, pid_units, "test_entry")

    # One yield per PID
    assert len(sleep_calls) == 2
    assert all(d == 0 for d in sleep_calls)
