"""Tests for cross-file event correlation (M3.1-M3.3)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from logler.event_correlator import (
    correlate_events,
    find_trigger_events,
    search_around_timestamp,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def multi_file_logs(tmp_path: Path) -> dict:
    """Create realistic multi-file log data for cross-file correlation."""
    sensor_log = tmp_path / "sensor_pressure.log"
    sensor_log.write_text(
        textwrap.dedent(
            """\
        2024-01-15T10:00:00Z INFO pressure=3.5 Pressure nominal
        2024-01-15T10:00:05Z INFO pressure=3.2 Pressure nominal
        2024-01-15T10:00:10Z WARN pressure=1.8 Pressure below threshold
        2024-01-15T10:00:15Z ERROR pressure=0.5 Pressure critical
        2024-01-15T10:00:20Z INFO pressure=2.1 Pressure recovering
        """
        )
    )

    plc_log = tmp_path / "plc_motor.log"
    plc_log.write_text(
        textwrap.dedent(
            """\
        2024-01-15T10:00:02Z INFO Motor speed=1500rpm
        2024-01-15T10:00:08Z INFO Motor speed=1200rpm
        2024-01-15T10:00:12Z WARN Motor speed=400rpm deceleration detected
        2024-01-15T10:00:14Z ERROR Motor stalled
        2024-01-15T10:00:22Z INFO Motor speed=800rpm restarting
        """
        )
    )

    mes_log = tmp_path / "mes_batch.log"
    mes_log.write_text(
        textwrap.dedent(
            """\
        2024-01-15T09:55:00Z INFO Batch B-042 started
        2024-01-15T10:00:13Z WARN Batch B-042 quality check triggered
        2024-01-15T10:00:16Z ERROR Batch B-042 production halted
        2024-01-15T10:00:30Z INFO Batch B-042 resumed
        """
        )
    )

    return {
        "sensor_log": str(sensor_log),
        "plc_log": str(plc_log),
        "mes_log": str(mes_log),
        "all_files": [str(sensor_log), str(plc_log), str(mes_log)],
    }


def _make_mock_search(log_data: dict):
    """Create a mock search function that returns entries based on time range."""
    # Pre-build entries for each file
    from datetime import datetime

    file_entries = {}
    for log_path, lines in log_data.items():
        entries = []
        for i, line in enumerate(lines.strip().split("\n"), start=1):
            parts = line.split(" ", 2)
            ts = parts[0] if len(parts) > 0 else ""
            level = parts[1] if len(parts) > 1 else "INFO"
            message = parts[2] if len(parts) > 2 else ""
            entries.append(
                {
                    "entry": {
                        "file": log_path,
                        "line_number": i,
                        "timestamp": ts.replace("Z", "+00:00"),
                        "level": level,
                        "message": message,
                        "raw": line,
                    }
                }
            )
        file_entries[log_path] = entries

    def mock_search(files, time_start=None, time_end=None, **kwargs):
        results = []
        for fp in files:
            for item in file_entries.get(fp, []):
                entry = item["entry"]
                ts_str = entry.get("timestamp", "")
                if ts_str and time_start and time_end:
                    try:
                        entry_ts = datetime.fromisoformat(ts_str)
                        start_ts = datetime.fromisoformat(time_start)
                        end_ts = datetime.fromisoformat(time_end)
                        if not (start_ts <= entry_ts <= end_ts):
                            continue
                    except ValueError:
                        continue
                # Level filter
                level_filter = kwargs.get("level")
                if level_filter:
                    if entry.get("level", "").upper() != level_filter.upper():
                        continue
                # Query filter
                query = kwargs.get("query")
                if query:
                    msg = entry.get("message", "") + entry.get("raw", "")
                    if query.lower() not in msg.lower():
                        continue
                results.append(item)
        return {"results": results, "total": len(results)}

    return mock_search


# =============================================================================
# search_around_timestamp
# =============================================================================


class TestSearchAroundTimestamp:
    """Test windowed search around a reference timestamp."""

    def test_finds_entries_within_window(self, multi_file_logs):
        """Entries within 5s of anchor are returned."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = search_around_timestamp(
                files=multi_file_logs["all_files"],
                anchor_timestamp="2024-01-15T10:00:13+00:00",
                window="5s",
            )

        assert result["anchor_timestamp"] == "2024-01-15T10:00:13+00:00"
        assert result["window"] == "5s"
        assert len(result["results"]) > 0

        # All results should be within [10:00:08, 10:00:18]
        for item in result["results"]:
            entry = item["entry"]
            ts = entry["timestamp"]
            assert "10:00:" in ts

    def test_narrow_window_limits_results(self, multi_file_logs):
        """A 1s window returns fewer results than 5s."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            narrow = search_around_timestamp(
                files=multi_file_logs["all_files"],
                anchor_timestamp="2024-01-15T10:00:13+00:00",
                window="1s",
            )
            wide = search_around_timestamp(
                files=multi_file_logs["all_files"],
                anchor_timestamp="2024-01-15T10:00:13+00:00",
                window="10s",
            )

        assert len(narrow["results"]) <= len(wide["results"])

    def test_metadata_in_response(self, multi_file_logs):
        """Response includes window metadata."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = search_around_timestamp(
                files=multi_file_logs["all_files"],
                anchor_timestamp="2024-01-15T10:00:10+00:00",
                window="3s",
            )

        assert "time_start" in result
        assert "time_end" in result
        assert "anchor_timestamp" in result
        assert "window" in result


# =============================================================================
# find_trigger_events
# =============================================================================


class TestFindTriggerEvents:
    """Test trigger event detection."""

    def test_find_by_level(self):
        """Finds entries matching a specific level."""
        entries = [
            {"level": "INFO", "message": "ok", "file": "a.log"},
            {"level": "ERROR", "message": "fail", "file": "a.log"},
            {"level": "WARN", "message": "slow", "file": "a.log"},
            {"level": "ERROR", "message": "crash", "file": "a.log"},
        ]
        triggers = find_trigger_events(entries, {"level": "ERROR"})
        assert len(triggers) == 2
        assert all(e["level"] == "ERROR" for e in triggers)

    def test_find_by_pattern(self):
        """Finds entries matching a regex pattern."""
        entries = [
            {"level": "INFO", "message": "Motor speed=1500rpm", "file": "m.log"},
            {"level": "WARN", "message": "Motor stalled", "file": "m.log"},
            {"level": "INFO", "message": "Pressure nominal", "file": "s.log"},
        ]
        triggers = find_trigger_events(entries, {"pattern": "stalled"})
        assert len(triggers) == 1
        assert "stalled" in triggers[0]["message"]

    def test_find_by_level_and_pattern(self):
        """Level and pattern must both match."""
        entries = [
            {"level": "INFO", "message": "Motor stalled", "file": "m.log"},
            {"level": "WARN", "message": "Motor stalled", "file": "m.log"},
            {"level": "WARN", "message": "Motor ok", "file": "m.log"},
        ]
        triggers = find_trigger_events(entries, {"level": "WARN", "pattern": "stalled"})
        assert len(triggers) == 1
        assert triggers[0]["level"] == "WARN"
        assert "stalled" in triggers[0]["message"]

    def test_empty_trigger_returns_nothing(self):
        """Empty trigger dict returns no results."""
        entries = [
            {"level": "ERROR", "message": "fail", "file": "a.log"},
        ]
        triggers = find_trigger_events(entries, {})
        assert len(triggers) == 0

    def test_find_by_file_pattern(self):
        """File pattern glob filters entries."""
        entries = [
            {"level": "ERROR", "message": "fail", "file": "/logs/sensor_01.log"},
            {"level": "ERROR", "message": "fail", "file": "/logs/plc_motor.log"},
            {"level": "ERROR", "message": "fail", "file": "/logs/sensor_02.log"},
        ]
        triggers = find_trigger_events(entries, {"level": "ERROR", "file_pattern": "sensor_*.log"})
        assert len(triggers) == 2
        assert all("sensor_" in t["file"] for t in triggers)


# =============================================================================
# correlate_events
# =============================================================================


class TestCorrelateEvents:
    """Test the main cross-file event correlation API."""

    def test_correlate_around_entry(self, multi_file_logs):
        """Correlating around a specific entry returns a cluster."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)
        anchor = {
            "file": multi_file_logs["sensor_log"],
            "line_number": 4,
            "timestamp": "2024-01-15T10:00:15+00:00",
            "level": "ERROR",
            "message": "Pressure critical",
        }

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = correlate_events(
                files=multi_file_logs["all_files"],
                anchor_entry=anchor,
                window="5s",
            )

        assert result["total_clusters"] == 1
        assert result["files_searched"] == 3
        assert result["window"] == "5s"

        cluster = result["clusters"][0]
        assert cluster["rule_type"] == "event_window"
        assert cluster["virtual_trace_id"].startswith("vt-")
        assert cluster["entry_count"] > 1
        assert cluster["anchor_message"] == "Pressure critical"

    def test_correlate_around_timestamp(self, multi_file_logs):
        """Correlating around a timestamp returns a cluster."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = correlate_events(
                files=multi_file_logs["all_files"],
                anchor_timestamp="2024-01-15T10:00:13+00:00",
                window="5s",
            )

        assert result["total_clusters"] == 1
        cluster = result["clusters"][0]
        assert cluster["rule_type"] == "event_window"
        assert cluster["entry_count"] > 0

    def test_correlate_by_trigger(self, multi_file_logs):
        """Trigger-based correlation finds events around trigger fires."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = correlate_events(
                files=multi_file_logs["all_files"],
                trigger={"level": "ERROR"},
                window="3s",
            )

        assert result["total_clusters"] >= 1
        for cluster in result["clusters"]:
            assert cluster["rule_type"] == "event_trigger"
            assert cluster["virtual_trace_id"].startswith("vt-")
            assert cluster["entry_count"] > 1

    def test_no_args_returns_error(self, multi_file_logs):
        """Must provide at least one of anchor_entry, anchor_timestamp, trigger."""
        result = correlate_events(files=multi_file_logs["all_files"])
        assert "error" in result
        assert result["total_clusters"] == 0

    def test_anchor_entry_without_timestamp(self, multi_file_logs):
        """Anchor entry without timestamp returns empty clusters."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = correlate_events(
                files=multi_file_logs["all_files"],
                anchor_entry={"message": "no timestamp"},
                window="5s",
            )

        assert result["total_clusters"] == 0

    def test_limit_clusters(self, multi_file_logs):
        """Limit restricts the number of returned clusters."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = correlate_events(
                files=multi_file_logs["all_files"],
                trigger={"level": "ERROR"},
                window="3s",
                limit=1,
            )

        assert len(result["clusters"]) <= 1
        # total_clusters may be larger than returned clusters
        assert result["total_clusters"] >= len(result["clusters"])

    def test_virtual_trace_ids_are_deterministic(self, multi_file_logs):
        """Same input produces same virtual trace IDs."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result1 = correlate_events(
                files=multi_file_logs["all_files"],
                anchor_timestamp="2024-01-15T10:00:13+00:00",
                window="5s",
            )
            result2 = correlate_events(
                files=multi_file_logs["all_files"],
                anchor_timestamp="2024-01-15T10:00:13+00:00",
                window="5s",
            )

        assert len(result1["clusters"]) == len(result2["clusters"])
        for c1, c2 in zip(result1["clusters"], result2["clusters"]):
            assert c1["virtual_trace_id"] == c2["virtual_trace_id"]

    def test_entries_from_multiple_files(self, multi_file_logs):
        """Correlation includes entries from all files within the window."""
        log_data = {}
        for key in ("sensor_log", "plc_log", "mes_log"):
            path = multi_file_logs[key]
            with open(path) as f:
                log_data[path] = f.read()

        mock_search = _make_mock_search(log_data)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = correlate_events(
                files=multi_file_logs["all_files"],
                anchor_timestamp="2024-01-15T10:00:13+00:00",
                window="5s",
            )

        cluster = result["clusters"][0]
        files_in_cluster = {e.get("file") for e in cluster["entries"]}
        # Should include entries from at least 2 files (sensor + plc or mes)
        assert len(files_in_cluster) >= 2
