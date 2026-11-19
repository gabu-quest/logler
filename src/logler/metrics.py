"""
Numeric value extraction and time-series statistics (M5).

Extracts numeric fields from log entries (both structured fields and
message-embedded patterns like "duration=123ms") and computes summary
statistics, time-bucketed aggregations, and anomaly detection.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .parser import format_time, to_utc


@dataclass
class DataPoint:
    """A single numeric observation extracted from a log entry."""

    timestamp: str | None
    value: float
    file: str
    line_number: int
    unit: str | None = None


@dataclass
class Anomaly:
    """A value that deviates significantly from the series mean."""

    timestamp: str | None
    value: float
    z_score: float
    file: str
    line_number: int


@dataclass
class Bucket:
    """A time-aggregated bucket of data points."""

    start: str
    end: str
    min: float
    max: float
    avg: float
    count: int


@dataclass
class SeriesStats:
    """Summary statistics for a numeric series."""

    count: int
    min: float
    max: float
    mean: float
    median: float
    stddev: float
    p95: float
    p99: float
    first_timestamp: str | None
    last_timestamp: str | None
    anomalies: list[Anomaly] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex patterns for extracting numeric values from log messages
# ---------------------------------------------------------------------------

# Pattern 1: key=value with optional unit  (e.g., "temperature=22.5°C")
# A field's name runs from the first ASCII letter or underscore of its word to the word's end.
_KV_FIELD = (
    r"[^\Wa-zA-Z_]*"  # the word's leading digits and non-ASCII letters are not part of the name
    r"(?P<field>[a-zA-Z_][\w]*)"
    r"\s*[=:]\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)"
    r"\s*(?P<unit>ms|s|us|ns|MB|GB|KB|kPa|°[CF]|%|rpm|Hz)?"
)
# Tried only where a word starts. Tried at every character, each try runs to the end of the
# word and fails the same way, which is quadratic in the word's length: seconds for a 20 KB
# hex dump, minutes for 50 KB.
_KV_PATTERN = re.compile(r"(?<!\w)" + _KV_FIELD)
# The one place a name may start inside a word: right where the previous match ended
# ("a=1b=2" holds a and b).
_KV_RESUME = re.compile(_KV_FIELD)


def _kv_matches(message: str) -> Iterator[re.Match[str]]:
    """Every ``name=number`` in a message, left to right, in one pass."""
    pos = 0
    while match := _KV_RESUME.match(message, pos) or _KV_PATTERN.search(message, pos):
        yield match
        pos = match.end()


# Pattern 2: duration-style phrases  (e.g., "took 45ms", "elapsed 120s")
_DURATION_PATTERN = re.compile(
    r"(?:took|elapsed|duration|latency|time|response_time)"
    r"\s*(?:[:=]\s*)?"  # not "\s*[:=]?\s*": two runs side by side split a run of spaces every way
    r"(?P<value>\d+(?:\.\d+)?)"
    r"\s*(?P<unit>ms|s|us|ns)"
)


def extract_numeric_fields(
    entries: Sequence[dict[str, Any]],
) -> dict[str, list[DataPoint]]:
    """Extract all numeric fields from a sequence of log entries.

    Sources (checked in order):
    1. entry["fields"] dict — any value that is int/float
    2. entry["message"] — regex-matched key=value pairs
    3. Named fields on the entry itself (e.g., "duration_ms")

    Args:
        entries: List of log entry dicts (as returned by investigate.search()).

    Returns:
        Mapping of field_name -> list of DataPoints, sorted by timestamp.
    """
    series: dict[str, list[DataPoint]] = {}

    for entry in entries:
        file_path = entry.get("file", "")
        line_number = entry.get("line_number", 0)
        timestamp = entry.get("timestamp")

        # Source 1: structured fields dict
        fields = entry.get("fields") or {}
        for key, val in fields.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                _add_point(
                    series,
                    key,
                    DataPoint(
                        timestamp=timestamp,
                        value=float(val),
                        file=file_path,
                        line_number=line_number,
                    ),
                )

        # Source 2: top-level numeric fields (duration_ms, etc.)
        for known_field in ("duration_ms",):
            val = entry.get(known_field)
            if val is not None and isinstance(val, (int, float)):
                _add_point(
                    series,
                    known_field,
                    DataPoint(
                        timestamp=timestamp,
                        value=float(val),
                        file=file_path,
                        line_number=line_number,
                        unit="ms" if known_field.endswith("_ms") else None,
                    ),
                )

        # Source 3: regex extraction from message
        message = entry.get("message") or ""
        if message:
            _extract_from_message(message, timestamp, file_path, line_number, series)

    return series


def _add_point(series: dict[str, list[DataPoint]], field_name: str, point: DataPoint) -> None:
    if field_name not in series:
        series[field_name] = []
    series[field_name].append(point)


def _extract_from_message(
    message: str,
    timestamp: str | None,
    file_path: str,
    line_number: int,
    series: dict[str, list[DataPoint]],
) -> None:
    """Extract numeric values from a log message string using regex patterns."""
    seen_fields: set = set()

    # Apply key=value pattern first (highest priority — most specific)
    for match in _kv_matches(message):
        field_name = match.group("field")
        if field_name in seen_fields:
            continue
        # Skip fields that look like timestamps or hex
        if field_name.lower() in ("port", "pid", "uid", "euid", "gid"):
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        unit = match.group("unit") or None
        seen_fields.add(field_name)
        _add_point(
            series,
            field_name,
            DataPoint(
                timestamp=timestamp,
                value=value,
                file=file_path,
                line_number=line_number,
                unit=unit,
            ),
        )

    # Apply duration pattern (catch "took 45ms" without explicit field name)
    for match in _DURATION_PATTERN.finditer(message):
        field_name = "duration"
        if field_name in seen_fields:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        unit = match.group("unit") or None
        seen_fields.add(field_name)
        _add_point(
            series,
            field_name,
            DataPoint(
                timestamp=timestamp,
                value=value,
                file=file_path,
                line_number=line_number,
                unit=unit,
            ),
        )


def compute_series_stats(
    points: Sequence[DataPoint],
    anomaly_threshold: float = 2.0,
) -> SeriesStats:
    """Compute summary statistics for a series of data points.

    Args:
        points: Non-empty list of DataPoint values.
        anomaly_threshold: Z-score threshold for anomaly detection (default 2.0).

    Returns:
        SeriesStats with min, max, mean, median, stddev, percentiles, anomalies.

    Raises:
        ValueError: If points is empty.
    """
    if not points:
        raise ValueError("Cannot compute stats on empty series")

    values = [p.value for p in points]
    n = len(values)
    sorted_values = sorted(values)

    mean = sum(values) / n
    median = _percentile(sorted_values, 50.0)
    p95 = _percentile(sorted_values, 95.0)
    p99 = _percentile(sorted_values, 99.0)

    # Population standard deviation (not sample)
    variance = sum((v - mean) ** 2 for v in values) / n
    stddev = math.sqrt(variance)

    # Timestamps (from sorted by timestamp)
    ts_points = [p for p in points if p.timestamp]
    ts_sorted = sorted(ts_points, key=lambda p: p.timestamp or "")
    first_ts = ts_sorted[0].timestamp if ts_sorted else None
    last_ts = ts_sorted[-1].timestamp if ts_sorted else None

    # Anomalies: z-score > threshold
    anomalies: list[Anomaly] = []
    if stddev > 0:
        for p in points:
            z = abs(p.value - mean) / stddev
            if z > anomaly_threshold:
                anomalies.append(
                    Anomaly(
                        timestamp=p.timestamp,
                        value=p.value,
                        z_score=round(z, 4),
                        file=p.file,
                        line_number=p.line_number,
                    )
                )

    return SeriesStats(
        count=n,
        min=min(values),
        max=max(values),
        mean=round(mean, 6),
        median=median,
        stddev=round(stddev, 6),
        p95=p95,
        p99=p99,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        anomalies=anomalies,
    )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute percentile using linear interpolation (same as numpy default)."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = (pct / 100.0) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])


def aggregate_time_buckets(
    points: Sequence[DataPoint],
    bucket_size: str = "1s",
) -> list[Bucket]:
    """Aggregate data points into fixed-size time buckets.

    Args:
        points: Data points with timestamps.
        bucket_size: Duration string for bucket width (e.g., "1s", "5s", "1m").

    Returns:
        List of Buckets sorted by start time. Points without timestamps are skipped.
    """
    delta = _parse_bucket_duration(bucket_size)

    # Filter and sort by timestamp
    timestamped = [(p, to_utc(p.timestamp)) for p in points if p.timestamp]
    timestamped = [(p, ts) for p, ts in timestamped if ts is not None]

    if not timestamped:
        return []

    timestamped.sort(key=lambda x: x[1])

    # Build buckets
    first_ts = timestamped[0][1]
    buckets: dict[int, list[float]] = {}

    for point, ts in timestamped:
        bucket_idx = int((ts - first_ts).total_seconds() / delta.total_seconds())
        if bucket_idx not in buckets:
            buckets[bucket_idx] = []
        buckets[bucket_idx].append(point.value)

    # Convert to Bucket objects
    result: list[Bucket] = []
    for idx in sorted(buckets.keys()):
        values = buckets[idx]
        start = first_ts + delta * idx
        end = start + delta
        result.append(
            Bucket(
                start=format_time(start),
                end=format_time(end),
                min=min(values),
                max=max(values),
                avg=round(sum(values) / len(values), 6),
                count=len(values),
            )
        )

    return result


def _parse_bucket_duration(duration: str) -> timedelta:
    """Parse a bucket size string like '5s', '1m', '500ms'."""
    match = re.match(r"^(\d+)(ms|s|m|h)$", duration.lower())
    if not match:
        raise ValueError(
            f"Invalid bucket size: {duration!r}. Use format like '1s', '5s', '1m', '500ms'."
        )
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "ms":
        return timedelta(milliseconds=amount)
    elif unit == "s":
        return timedelta(seconds=amount)
    elif unit == "m":
        return timedelta(minutes=amount)
    else:  # "h"
        return timedelta(hours=amount)


# ---------------------------------------------------------------------------
# High-level API (used by investigate.py wrappers and CLI)
# ---------------------------------------------------------------------------


def extract_metrics(
    entries: Sequence[dict[str, Any]],
    fields: list[str] | None = None,
    bucket_size: str | None = None,
    anomaly_threshold: float = 2.0,
) -> dict[str, Any]:
    """Full metrics pipeline: extract → stats → buckets.

    Args:
        entries: Log entry dicts.
        fields: If specified, only return these field names.
        bucket_size: If specified, include time-bucketed aggregation.
        anomaly_threshold: Z-score threshold for anomaly detection.

    Returns:
        Dict with "fields" mapping, each containing stats and optional buckets.
    """
    all_series = extract_numeric_fields(entries)

    # Filter to requested fields
    if fields:
        all_series = {k: v for k, v in all_series.items() if k in fields}

    result_fields: dict[str, Any] = {}

    for field_name, points in all_series.items():
        if not points:
            continue

        stats = compute_series_stats(points, anomaly_threshold)

        field_data: dict[str, Any] = {
            "count": stats.count,
            "stats": {
                "min": stats.min,
                "max": stats.max,
                "mean": stats.mean,
                "median": stats.median,
                "stddev": stats.stddev,
                "p95": stats.p95,
                "p99": stats.p99,
            },
            "first_timestamp": stats.first_timestamp,
            "last_timestamp": stats.last_timestamp,
            "anomalies": [
                {
                    "timestamp": a.timestamp,
                    "value": a.value,
                    "z_score": a.z_score,
                    "file": a.file,
                    "line_number": a.line_number,
                }
                for a in stats.anomalies
            ],
        }

        if bucket_size:
            buckets = aggregate_time_buckets(points, bucket_size)
            field_data["buckets"] = [
                {
                    "start": b.start,
                    "end": b.end,
                    "min": b.min,
                    "max": b.max,
                    "avg": b.avg,
                    "count": b.count,
                }
                for b in buckets
            ]

        # Detect common unit from points
        units = {p.unit for p in points if p.unit}
        if len(units) == 1:
            field_data["unit"] = units.pop()

        result_fields[field_name] = field_data

    return {
        "fields": result_fields,
        "entries_scanned": len(entries),
    }
