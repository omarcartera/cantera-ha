"""Tests for ha_statistics module."""
import pytest
from custom_components.cantera.ha_statistics import aggregate_readings, _bucket_start, BUCKET_S


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
    readings = [{"pid": "engine_rpm", "timestamp_ms": 0, "value": 2000.0, "unit": "rpm"}]
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
        {"pid": "engine_rpm", "timestamp_ms": (bucket_ts + 1) * 1000, "value": 1000.0, "unit": "rpm"},
        {"pid": "engine_rpm", "timestamp_ms": (bucket_ts + 2) * 1000, "value": 3000.0, "unit": "rpm"},
    ]
    result = aggregate_readings(readings)
    bucket = result["engine_rpm"][0]
    assert bucket["mean"] == 2000.0
    assert bucket["min"] == 1000.0
    assert bucket["max"] == 3000.0


def test_aggregate_readings_multiple_pids():
    readings = [
        {"pid": "engine_rpm", "timestamp_ms": 0, "value": 2000.0, "unit": "rpm"},
        {"pid": "vehicle_speed", "timestamp_ms": 0, "value": 60.0, "unit": "km/h"},
    ]
    result = aggregate_readings(readings)
    assert "engine_rpm" in result
    assert "vehicle_speed" in result


def test_aggregate_readings_multiple_buckets():
    """Readings spanning two buckets produce two bucket entries."""
    b1 = BUCKET_S * 1
    b2 = BUCKET_S * 2
    readings = [
        {"pid": "rpm", "timestamp_ms": (b1 + 1) * 1000, "value": 1000.0, "unit": "rpm"},
        {"pid": "rpm", "timestamp_ms": (b2 + 1) * 1000, "value": 2000.0, "unit": "rpm"},
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
        {"pid": "rpm", "timestamp_ms": (b2 + 1) * 1000, "value": 200.0, "unit": "rpm"},
        {"pid": "rpm", "timestamp_ms": (b1 + 1) * 1000, "value": 100.0, "unit": "rpm"},
    ]
    result = aggregate_readings(readings)
    starts = [b["start"] for b in result["rpm"]]
    assert starts == sorted(starts)
