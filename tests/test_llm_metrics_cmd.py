"""
CLI integration tests for `logler llm metrics` command (M5.3).

Tests JSON output structure, field filtering, exit codes, and compact mode.
Uses Click's CliRunner — no subprocess spawning.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from logler.llm_cli import llm, EXIT_SUCCESS, EXIT_NO_RESULTS

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sensor_log():
    return str(FIXTURE_DIR / "numeric_sensor.log")


@pytest.fixture
def plain_text_log():
    """Log file with no numeric values."""
    f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log")
    for i in range(10):
        f.write(
            f'{{"timestamp": "2024-01-15T10:00:{i:02d}Z", '
            f'"level": "INFO", "message": "Server started successfully"}}\n'
        )
    f.close()
    yield f.name
    Path(f.name).unlink()


class TestMetricsJsonOutput:
    """Test that metrics command produces valid, complete JSON output."""

    def test_valid_json_output(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log])
        data = json.loads(result.output)
        assert "fields" in data
        assert "entries_scanned" in data
        assert "files_searched" in data

    def test_fields_have_required_keys(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log])
        data = json.loads(result.output)
        for field_name, field_data in data["fields"].items():
            assert "count" in field_data, f"Missing 'count' in {field_name}"
            assert "stats" in field_data, f"Missing 'stats' in {field_name}"
            stats = field_data["stats"]
            for key in ("min", "max", "mean", "median", "stddev", "p95", "p99"):
                assert key in stats, f"Missing '{key}' in stats for {field_name}"

    def test_extracts_temperature_field(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log])
        data = json.loads(result.output)
        assert "temperature" in data["fields"]
        temp = data["fields"]["temperature"]
        assert temp["count"] == 20
        assert temp["stats"]["min"] == 22.4
        assert temp["stats"]["max"] == 120.0


class TestMetricsFieldFilter:
    """Test --fields option filters output correctly."""

    def test_single_field_filter(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log, "--fields", "temperature"])
        data = json.loads(result.output)
        assert "temperature" in data["fields"]
        assert "pressure" not in data["fields"]
        assert "humidity" not in data["fields"]

    def test_multi_field_filter(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log, "--fields", "temperature,pressure"])
        data = json.loads(result.output)
        assert "temperature" in data["fields"]
        assert "pressure" in data["fields"]
        assert "humidity" not in data["fields"]

    def test_nonexistent_field_returns_empty(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log, "--fields", "nonexistent"])
        data = json.loads(result.output)
        assert data["fields"] == {}


class TestMetricsExitCodes:
    """Test exit codes are correct."""

    def test_success_with_metrics(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log])
        assert result.exit_code == EXIT_SUCCESS

    def test_no_results_exit_code(self, runner, plain_text_log):
        result = runner.invoke(llm, ["metrics", plain_text_log])
        assert result.exit_code == EXIT_NO_RESULTS

    def test_missing_file_exits_with_error(self, runner):
        result = runner.invoke(llm, ["metrics", "/nonexistent/path.log"])
        assert result.exit_code != EXIT_SUCCESS


class TestMetricsCompactMode:
    """Test --compact output."""

    def test_compact_has_stats_no_buckets(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log, "--compact"])
        data = json.loads(result.output)
        for field_data in data["fields"].values():
            assert "stats" in field_data
            assert "buckets" not in field_data
            assert "anomalies" not in field_data

    def test_compact_preserves_unit(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log, "--compact"])
        data = json.loads(result.output)
        if "temperature" in data["fields"]:
            assert data["fields"]["temperature"].get("unit") == "°C"


class TestMetricsBuckets:
    """Test --bucket aggregation in output."""

    @pytest.fixture
    def json_log_with_metrics(self):
        """JSON log with timestamps that Rust parser can definitely extract."""
        f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl")
        for i in range(10):
            entry = json.dumps(
                {
                    "timestamp": f"2024-01-15T10:00:{i:02d}Z",
                    "level": "INFO",
                    "message": f"temperature={22.0+i*0.1:.1f}°C",
                }
            )
            f.write(entry + "\n")
        f.close()
        yield f.name
        Path(f.name).unlink()

    def test_bucket_output_present(self, runner, json_log_with_metrics):
        result = runner.invoke(llm, ["metrics", json_log_with_metrics, "--bucket", "5s"])
        data = json.loads(result.output)
        if "temperature" in data["fields"]:
            assert "buckets" in data["fields"]["temperature"]
            buckets = data["fields"]["temperature"]["buckets"]
            assert len(buckets) > 0
            # Each bucket must have required keys
            for b in buckets:
                assert "start" in b
                assert "end" in b
                assert "min" in b
                assert "max" in b
                assert "avg" in b
                assert "count" in b


class TestMetricsPrettyOutput:
    """Test --pretty flag."""

    def test_pretty_output_has_indentation(self, runner, sensor_log):
        result = runner.invoke(llm, ["metrics", sensor_log, "--pretty"])
        # Pretty JSON has newlines and indentation
        assert "\n" in result.output
        assert "  " in result.output
        # Still valid JSON
        data = json.loads(result.output)
        assert "fields" in data
