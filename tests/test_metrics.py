"""
Brutal test suite for logler.metrics (M5).

Every test asserts exact values — not types, not existence, not "is truthy".
If the function returned garbage, these tests MUST fail.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from logler.metrics import (
    DataPoint,
    aggregate_time_buckets,
    compute_series_stats,
    extract_metrics,
    extract_numeric_fields,
)


# ============================================================================
# Fixtures with KNOWN, EXACT values
# ============================================================================

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _make_entry(
    message: str = "",
    timestamp: str | None = None,
    file: str = "test.log",
    line_number: int = 1,
    fields: dict | None = None,
    **kwargs,
) -> dict:
    """Helper to build a log entry dict."""
    entry = {
        "message": message,
        "timestamp": timestamp,
        "file": file,
        "line_number": line_number,
        "fields": fields or {},
    }
    entry.update(kwargs)
    return entry


def _make_points(values: list[float], base_ts: str = "2024-01-15T10:00:0") -> list[DataPoint]:
    """Helper: create DataPoints with sequential timestamps."""
    return [
        DataPoint(
            timestamp=f"{base_ts}{i}Z",
            value=v,
            file="test.log",
            line_number=i + 1,
        )
        for i, v in enumerate(values)
    ]


# ============================================================================
# extract_numeric_fields — exact value assertions
# ============================================================================


class TestExtractFromFieldsDict:
    """Test extraction from entry.fields (structured data)."""

    def test_single_int_field(self):
        entries = [_make_entry(fields={"response_code": 200})]
        result = extract_numeric_fields(entries)
        assert "response_code" in result
        assert len(result["response_code"]) == 1
        assert result["response_code"][0].value == 200.0

    def test_single_float_field(self):
        entries = [_make_entry(fields={"duration_ms": 150.5})]
        result = extract_numeric_fields(entries)
        assert "duration_ms" in result
        assert len(result["duration_ms"]) == 1
        assert result["duration_ms"][0].value == 150.5

    def test_multiple_numeric_fields(self):
        entries = [_make_entry(fields={"cpu": 92.1, "memory_mb": 1024, "label": "worker"})]
        result = extract_numeric_fields(entries)
        # Only numeric fields, not string "label"
        assert "cpu" in result
        assert "memory_mb" in result
        assert "label" not in result
        assert result["cpu"][0].value == 92.1
        assert result["memory_mb"][0].value == 1024.0

    def test_boolean_fields_excluded(self):
        """Booleans are technically int subclass — must be excluded."""
        entries = [_make_entry(fields={"is_active": True, "count": 5})]
        result = extract_numeric_fields(entries)
        assert "is_active" not in result
        assert "count" in result
        assert result["count"][0].value == 5.0

    def test_zero_value_extracted(self):
        """Zero is a valid numeric value, not falsy skip."""
        entries = [_make_entry(fields={"errors": 0})]
        result = extract_numeric_fields(entries)
        assert "errors" in result
        assert result["errors"][0].value == 0.0

    def test_negative_value_from_fields(self):
        entries = [_make_entry(fields={"delta": -5.3})]
        result = extract_numeric_fields(entries)
        assert result["delta"][0].value == -5.3

    def test_preserves_file_and_line(self):
        entries = [
            _make_entry(
                fields={"x": 42},
                file="/var/log/app.log",
                line_number=99,
                timestamp="2024-01-15T10:00:00Z",
            )
        ]
        result = extract_numeric_fields(entries)
        pt = result["x"][0]
        assert pt.file == "/var/log/app.log"
        assert pt.line_number == 99
        assert pt.timestamp == "2024-01-15T10:00:00Z"


class TestExtractFromMessage:
    """Test regex extraction from entry.message."""

    def test_key_equals_value_with_unit(self):
        entries = [_make_entry(message="temperature=22.5°C pressure=101.3kPa")]
        result = extract_numeric_fields(entries)
        assert result["temperature"][0].value == 22.5
        assert result["temperature"][0].unit == "°C"
        assert result["pressure"][0].value == 101.3
        assert result["pressure"][0].unit == "kPa"

    def test_key_colon_value(self):
        entries = [_make_entry(message="latency: 45ms")]
        result = extract_numeric_fields(entries)
        assert "latency" in result
        assert result["latency"][0].value == 45.0
        assert result["latency"][0].unit == "ms"

    def test_duration_took_pattern(self):
        entries = [_make_entry(message="Request to /api/users took 123ms")]
        result = extract_numeric_fields(entries)
        assert "duration" in result
        assert result["duration"][0].value == 123.0
        assert result["duration"][0].unit == "ms"

    def test_negative_value_in_message(self):
        entries = [_make_entry(message="delta=-5.3")]
        result = extract_numeric_fields(entries)
        assert result["delta"][0].value == -5.3

    def test_percentage_unit(self):
        entries = [_make_entry(message="humidity=78%")]
        result = extract_numeric_fields(entries)
        assert result["humidity"][0].value == 78.0
        assert result["humidity"][0].unit == "%"

    def test_no_numeric_content(self):
        entries = [_make_entry(message="Server started successfully")]
        result = extract_numeric_fields(entries)
        # Should return empty dict, not crash
        assert result == {}

    def test_multiple_entries_same_field(self):
        entries = [
            _make_entry(message="temperature=22.5°C", line_number=1),
            _make_entry(message="temperature=23.1°C", line_number=2),
            _make_entry(message="temperature=85.2°C", line_number=3),
        ]
        result = extract_numeric_fields(entries)
        assert len(result["temperature"]) == 3
        assert [p.value for p in result["temperature"]] == [22.5, 23.1, 85.2]


class TestExtractTopLevelFields:
    """Test extraction of known top-level entry fields like duration_ms."""

    def test_duration_ms_field(self):
        entries = [_make_entry(duration_ms=45.2)]
        result = extract_numeric_fields(entries)
        assert "duration_ms" in result
        assert result["duration_ms"][0].value == 45.2
        assert result["duration_ms"][0].unit == "ms"


class TestExtractFromFixtureFile:
    """Test extraction against the deterministic sensor fixture."""

    def _load_sensor_entries(self) -> list[dict]:
        """Load sensor fixture as entry dicts for testing."""
        fixture_path = FIXTURE_DIR / "numeric_sensor.log"
        entries = []
        with open(fixture_path) as f:
            for i, line in enumerate(f, 1):
                line = line.rstrip()
                if not line or line.startswith("#"):
                    continue
                entries.append(
                    {
                        "message": line,
                        "raw": line,
                        "file": str(fixture_path),
                        "line_number": i,
                        "timestamp": line[:24] if line[:4].isdigit() else None,
                        "fields": {},
                    }
                )
        return entries

    def test_extracts_all_three_fields(self):
        entries = self._load_sensor_entries()
        result = extract_numeric_fields(entries)
        assert "temperature" in result, f"Fields found: {list(result.keys())}"
        assert "pressure" in result
        assert "humidity" in result

    def test_temperature_count(self):
        entries = self._load_sensor_entries()
        result = extract_numeric_fields(entries)
        assert len(result["temperature"]) == 20

    def test_temperature_values_exact(self):
        """Assert the EXACT extracted temperature values match the fixture."""
        expected_temps = [
            22.5,
            22.7,
            23.1,
            22.9,
            23.0,
            22.8,
            85.2,
            22.6,
            22.4,
            22.5,
            22.7,
            22.9,
            23.0,
            22.8,
            23.1,
            22.6,
            120.0,
            22.5,
            22.7,
            22.9,
        ]
        entries = self._load_sensor_entries()
        result = extract_numeric_fields(entries)
        actual_temps = [p.value for p in result["temperature"]]
        assert actual_temps == expected_temps

    def test_pressure_values_exact(self):
        expected = [
            101.3,
            101.2,
            101.1,
            101.3,
            101.2,
            101.1,
            98.1,
            101.3,
            101.2,
            101.1,
            101.3,
            101.2,
            101.1,
            101.3,
            101.2,
            101.1,
            95.0,
            101.3,
            101.2,
            101.1,
        ]
        entries = self._load_sensor_entries()
        result = extract_numeric_fields(entries)
        actual = [p.value for p in result["pressure"]]
        assert actual == expected

    def test_humidity_min_max(self):
        entries = self._load_sensor_entries()
        result = extract_numeric_fields(entries)
        values = [p.value for p in result["humidity"]]
        assert min(values) == 45.0
        assert max(values) == 78.0

    def test_units_detected(self):
        entries = self._load_sensor_entries()
        result = extract_numeric_fields(entries)
        temp_units = {p.unit for p in result["temperature"]}
        pressure_units = {p.unit for p in result["pressure"]}
        humidity_units = {p.unit for p in result["humidity"]}
        assert temp_units == {"°C"}
        assert pressure_units == {"kPa"}
        assert humidity_units == {"%"}


class TestMultiFileExtraction:
    """Test extraction across multiple files."""

    def test_merges_fields_across_files(self):
        entries = [
            _make_entry(
                message="temperature=22.5°C",
                file="sensor1.log",
                line_number=1,
                timestamp="2024-01-15T10:00:00Z",
            ),
            _make_entry(
                message="temperature=23.0°C",
                file="sensor2.log",
                line_number=1,
                timestamp="2024-01-15T10:00:01Z",
            ),
            _make_entry(
                message="pressure=101.3kPa",
                file="sensor2.log",
                line_number=2,
                timestamp="2024-01-15T10:00:02Z",
            ),
        ]
        result = extract_numeric_fields(entries)
        assert len(result["temperature"]) == 2
        assert result["temperature"][0].file == "sensor1.log"
        assert result["temperature"][1].file == "sensor2.log"
        assert len(result["pressure"]) == 1
        assert result["pressure"][0].file == "sensor2.log"


# ============================================================================
# compute_series_stats — exact statistical assertions
# ============================================================================


class TestSeriesStats:
    """Test statistics computation with known exact values."""

    def test_known_five_values(self):
        """[10, 20, 30, 40, 50] — all stats computable by hand."""
        points = _make_points([10, 20, 30, 40, 50])
        stats = compute_series_stats(points)
        assert stats.count == 5
        assert stats.min == 10.0
        assert stats.max == 50.0
        assert stats.mean == 30.0
        assert stats.median == 30.0
        # Population stddev: sqrt(((20^2 + 10^2 + 0 + 10^2 + 20^2) / 5))
        # = sqrt((400+100+0+100+400)/5) = sqrt(200) = 14.142135...
        assert abs(stats.stddev - math.sqrt(200)) < 0.001

    def test_single_value(self):
        points = _make_points([42.0])
        stats = compute_series_stats(points)
        assert stats.count == 1
        assert stats.min == 42.0
        assert stats.max == 42.0
        assert stats.mean == 42.0
        assert stats.median == 42.0
        assert stats.stddev == 0.0
        assert stats.p95 == 42.0
        assert stats.p99 == 42.0
        assert stats.anomalies == []

    def test_two_values(self):
        points = _make_points([10.0, 20.0])
        stats = compute_series_stats(points)
        assert stats.mean == 15.0
        assert stats.median == 15.0
        assert stats.min == 10.0
        assert stats.max == 20.0

    def test_identical_values_no_anomalies(self):
        """All same values → stddev=0, no anomalies possible."""
        points = _make_points([100.0] * 10)
        stats = compute_series_stats(points)
        assert stats.mean == 100.0
        assert stats.stddev == 0.0
        assert stats.anomalies == []

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            compute_series_stats([])

    def test_percentiles_on_100_values(self):
        """Values 1..100, p95=95.05, p99=99.01 (linear interpolation)."""
        points = _make_points([float(i) for i in range(1, 101)])
        stats = compute_series_stats(points)
        assert stats.count == 100
        assert stats.min == 1.0
        assert stats.max == 100.0
        assert stats.mean == 50.5
        assert stats.median == 50.5
        # p95: index = 0.95 * 99 = 94.05, between 95 and 96
        assert abs(stats.p95 - 95.05) < 0.01
        # p99: index = 0.99 * 99 = 98.01, between 99 and 100
        assert abs(stats.p99 - 99.01) < 0.01


class TestAnomalyDetection:
    """Test z-score anomaly detection with exact expectations."""

    def test_one_clear_outlier(self):
        """Series of ~100 with one 1000 → exactly 1 anomaly with z > 2."""
        values = [100.0] * 19 + [1000.0]
        points = _make_points(values)
        stats = compute_series_stats(points, anomaly_threshold=2.0)
        assert len(stats.anomalies) == 1
        assert stats.anomalies[0].value == 1000.0
        assert stats.anomalies[0].z_score > 2.0
        # Exact z-score:
        # mean = (19*100 + 1000)/20 = 2900/20 = 145
        # var = (19*(100-145)^2 + (1000-145)^2)/20
        #     = (19*2025 + 731025)/20 = (38475 + 731025)/20 = 769500/20 = 38475
        # stddev = sqrt(38475) ≈ 196.15
        # z = (1000 - 145) / 196.15 ≈ 4.36
        assert stats.anomalies[0].z_score > 4.0

    def test_no_anomalies_in_uniform_data(self):
        """Uniformly distributed values within normal range → no anomalies."""
        points = _make_points([100, 102, 98, 101, 99, 103, 97, 100, 101, 99])
        stats = compute_series_stats(points, anomaly_threshold=2.0)
        assert len(stats.anomalies) == 0

    def test_two_outliers(self):
        """Two extreme outliers both above z=2 threshold.

        values: [100]*18 + [2000, -1500]
        mean = (18*100 + 2000 + (-1500)) / 20 = 2300/20 = 115
        var = (18*(100-115)^2 + (2000-115)^2 + (-1500-115)^2) / 20
            = (18*225 + 3553225 + 2610225) / 20
            = (4050 + 3553225 + 2610225) / 20 = 6167500/20 = 308375
        stddev = sqrt(308375) ≈ 555.3
        z(2000) = |2000-115|/555.3 ≈ 3.39 → anomaly
        z(-1500) = |-1500-115|/555.3 ≈ 2.91 → anomaly
        """
        values = [100.0] * 18 + [2000.0, -1500.0]
        points = _make_points(values)
        stats = compute_series_stats(points, anomaly_threshold=2.0)
        anomaly_values = sorted([a.value for a in stats.anomalies])
        assert len(anomaly_values) == 2
        assert -1500.0 in anomaly_values
        assert 2000.0 in anomaly_values

    def test_anomaly_preserves_metadata(self):
        """Need enough normal points that the outlier's z-score exceeds 2.0.

        9 points at 100.0, 1 point at 9999.0.
        mean = (9*100 + 9999)/10 = 10899/10 = 1089.9
        var = (9*(100-1089.9)^2 + (9999-1089.9)^2)/10
            = (9*979020.01 + 79443020.01)/10 ≈ 87831+79443020)/10 = 88254201/10
        stddev ≈ 2970.6
        z(9999) = |9999-1089.9|/2970.6 ≈ 3.0 → anomaly
        """
        points = [
            DataPoint(
                timestamp=f"2024-01-15T10:00:0{i}Z",
                value=100.0,
                file="app.log",
                line_number=i + 1,
            )
            for i in range(9)
        ] + [
            DataPoint(
                timestamp="2024-01-15T10:00:09Z",
                value=9999.0,
                file="sensor.log",
                line_number=42,
            ),
        ]
        stats = compute_series_stats(points, anomaly_threshold=2.0)
        assert len(stats.anomalies) == 1
        assert stats.anomalies[0].file == "sensor.log"
        assert stats.anomalies[0].line_number == 42
        assert stats.anomalies[0].timestamp == "2024-01-15T10:00:09Z"


# ============================================================================
# aggregate_time_buckets — exact bucket assertions
# ============================================================================


class TestTimeBucketing:
    """Test time-series bucketing with exact expected results."""

    def test_10_points_in_10s_with_5s_buckets(self):
        """10 data points across 10 seconds → exactly 2 buckets of 5s."""
        points = [
            DataPoint(
                timestamp=f"2024-01-15T10:00:0{i}Z",
                value=float(i * 10),
                file="test.log",
                line_number=i + 1,
            )
            for i in range(10)
        ]
        buckets = aggregate_time_buckets(points, bucket_size="5s")
        assert len(buckets) == 2

        # Bucket 0: seconds 0-4 → values [0, 10, 20, 30, 40]
        assert buckets[0].count == 5
        assert buckets[0].min == 0.0
        assert buckets[0].max == 40.0
        assert buckets[0].avg == 20.0  # (0+10+20+30+40)/5

        # Bucket 1: seconds 5-9 → values [50, 60, 70, 80, 90]
        assert buckets[1].count == 5
        assert buckets[1].min == 50.0
        assert buckets[1].max == 90.0
        assert buckets[1].avg == 70.0  # (50+60+70+80+90)/5

    def test_single_point_single_bucket(self):
        points = [
            DataPoint(
                timestamp="2024-01-15T10:00:00Z",
                value=42.0,
                file="test.log",
                line_number=1,
            )
        ]
        buckets = aggregate_time_buckets(points, bucket_size="1s")
        assert len(buckets) == 1
        assert buckets[0].count == 1
        assert buckets[0].avg == 42.0
        assert buckets[0].min == 42.0
        assert buckets[0].max == 42.0

    def test_no_timestamps_returns_empty(self):
        points = [
            DataPoint(
                timestamp=None,
                value=42.0,
                file="test.log",
                line_number=1,
            )
        ]
        buckets = aggregate_time_buckets(points, bucket_size="1s")
        assert buckets == []

    def test_empty_input_returns_empty(self):
        assert aggregate_time_buckets([], bucket_size="1s") == []

    def test_millisecond_bucket_size(self):
        """500ms buckets over 1 second of data."""
        points = [
            DataPoint(
                timestamp="2024-01-15T10:00:00.000Z",
                value=10.0,
                file="test.log",
                line_number=1,
            ),
            DataPoint(
                timestamp="2024-01-15T10:00:00.250Z",
                value=20.0,
                file="test.log",
                line_number=2,
            ),
            DataPoint(
                timestamp="2024-01-15T10:00:00.500Z",
                value=30.0,
                file="test.log",
                line_number=3,
            ),
            DataPoint(
                timestamp="2024-01-15T10:00:00.750Z",
                value=40.0,
                file="test.log",
                line_number=4,
            ),
        ]
        buckets = aggregate_time_buckets(points, bucket_size="500ms")
        assert len(buckets) == 2
        assert buckets[0].count == 2
        assert buckets[0].avg == 15.0  # (10+20)/2
        assert buckets[1].count == 2
        assert buckets[1].avg == 35.0  # (30+40)/2

    def test_invalid_bucket_size_raises(self):
        points = _make_points([1.0])
        with pytest.raises(ValueError, match="Invalid bucket size"):
            aggregate_time_buckets(points, bucket_size="bogus")

    def test_bucket_boundaries_are_iso(self):
        points = [
            DataPoint(
                timestamp="2024-01-15T10:00:00+00:00",
                value=1.0,
                file="test.log",
                line_number=1,
            )
        ]
        buckets = aggregate_time_buckets(points, bucket_size="1s")
        assert len(buckets) == 1
        # Verify start/end are valid ISO strings
        from datetime import datetime

        datetime.fromisoformat(buckets[0].start)
        datetime.fromisoformat(buckets[0].end)


# ============================================================================
# extract_metrics (high-level API) — integration tests
# ============================================================================


class TestExtractMetrics:
    """Test the full metrics pipeline."""

    def test_full_pipeline_with_fixture_entries(self):
        entries = [
            _make_entry(
                message="temperature=22.5°C pressure=101.3kPa",
                timestamp="2024-01-15T10:00:00Z",
                line_number=1,
            ),
            _make_entry(
                message="temperature=23.0°C pressure=101.2kPa",
                timestamp="2024-01-15T10:00:01Z",
                line_number=2,
            ),
        ]
        result = extract_metrics(entries)
        assert result["entries_scanned"] == 2
        assert "temperature" in result["fields"]
        assert "pressure" in result["fields"]

        temp = result["fields"]["temperature"]
        assert temp["count"] == 2
        assert temp["stats"]["min"] == 22.5
        assert temp["stats"]["max"] == 23.0
        assert temp["stats"]["mean"] == 22.75
        assert temp["unit"] == "°C"

    def test_field_filter(self):
        entries = [
            _make_entry(message="temperature=22.5°C pressure=101.3kPa"),
        ]
        result = extract_metrics(entries, fields=["temperature"])
        assert "temperature" in result["fields"]
        assert "pressure" not in result["fields"]

    def test_with_buckets(self):
        entries = [
            _make_entry(
                message="temperature=22.5°C",
                timestamp="2024-01-15T10:00:00Z",
                line_number=1,
            ),
            _make_entry(
                message="temperature=23.0°C",
                timestamp="2024-01-15T10:00:05Z",
                line_number=2,
            ),
        ]
        result = extract_metrics(entries, bucket_size="5s")
        temp = result["fields"]["temperature"]
        assert "buckets" in temp
        assert len(temp["buckets"]) == 2

    def test_empty_entries(self):
        result = extract_metrics([])
        assert result["fields"] == {}
        assert result["entries_scanned"] == 0

    def test_no_numeric_entries(self):
        entries = [_make_entry(message="Just a plain log message")]
        result = extract_metrics(entries)
        assert result["fields"] == {}
        assert result["entries_scanned"] == 1

    def test_anomalies_in_output(self):
        entries = [
            _make_entry(
                message="val=100",
                timestamp=f"2024-01-15T10:00:0{i}Z",
                line_number=i + 1,
            )
            for i in range(9)
        ] + [
            _make_entry(
                message="val=10000",
                timestamp="2024-01-15T10:00:09Z",
                line_number=10,
            ),
        ]
        result = extract_metrics(entries)
        assert len(result["fields"]["val"]["anomalies"]) == 1
        assert result["fields"]["val"]["anomalies"][0]["value"] == 10000.0

    def test_fields_dict_and_message_both_contribute(self):
        """Structured fields AND message patterns both extracted."""
        entries = [
            _make_entry(
                message="latency=50ms",
                fields={"cpu_percent": 85.0},
            )
        ]
        result = extract_metrics(entries)
        assert "latency" in result["fields"]
        assert "cpu_percent" in result["fields"]
        assert result["fields"]["latency"]["stats"]["min"] == 50.0
        assert result["fields"]["cpu_percent"]["stats"]["min"] == 85.0
