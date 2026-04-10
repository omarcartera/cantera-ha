"""HA long-term statistics importer for CANtera OBD readings."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.util.dt import utc_from_timestamp

from .const import DOMAIN, HISTORY_BUCKET_MINUTES

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

BUCKET_S = HISTORY_BUCKET_MINUTES * 60


def build_statistic_ids(pid_names: list[str]) -> list[str]:
    """Return the external statistic IDs for the given PID display names."""
    return [f"{DOMAIN}:{name.lower().replace(' ', '_')}" for name in pid_names]


def _bucket_start(ts_ms: int) -> int:
    """Round timestamp down to bucket boundary (in seconds)."""
    ts_s = ts_ms // 1000
    return (ts_s // BUCKET_S) * BUCKET_S


def aggregate_readings(readings: list[dict]) -> dict[str, list[dict]]:
    """Aggregate raw readings into per-PID, per-bucket mean/min/max."""
    buckets: dict[str, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for r in readings:
        pid = r["pid"]
        bucket = _bucket_start(r["ts"])
        buckets[pid][bucket].append(r["value"])

    result: dict[str, list[dict]] = {}
    for pid, pid_buckets in buckets.items():
        result[pid] = [
            {
                "start": bucket_ts,
                "mean": sum(vals) / len(vals),
                "min": min(vals),
                "max": max(vals),
            }
            for bucket_ts, vals in sorted(pid_buckets.items())
        ]
    return result


async def import_statistics(
    hass: HomeAssistant,
    readings: list[dict],
    pid_units: dict[str, str],
) -> None:
    """Import historical readings as HA long-term statistics."""
    if not readings:
        return

    aggregated = aggregate_readings(readings)

    for pid_name, stat_buckets in aggregated.items():
        unit = pid_units.get(pid_name, "")
        statistic_id = f"{DOMAIN}:{pid_name.lower().replace(' ', '_')}"
        source = DOMAIN

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name=pid_name,
            source=source,
            statistic_id=statistic_id,
            unit_class=None,
            unit_of_measurement=unit or None,
        )

        statistics = [
            StatisticData(
                start=utc_from_timestamp(b["start"]),
                mean=b["mean"],
                min=b["min"],
                max=b["max"],
            )
            for b in stat_buckets
        ]

        try:
            async_add_external_statistics(hass, metadata, statistics)
        except Exception:
            _LOGGER.exception("Failed to import statistics for %s", pid_name)
