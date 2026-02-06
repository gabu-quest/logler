"""Tests for LLM CLI correlate-events command (M3.4)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from logler.llm_cli import llm

EXIT_SUCCESS = 0
EXIT_NO_RESULTS = 1
EXIT_USER_ERROR = 2


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def log_files(tmp_path: Path) -> dict:
    """Create log files for cross-file correlation testing."""
    sensor = tmp_path / "sensor_01.log"
    sensor.write_text(
        textwrap.dedent(
            """\
        2024-01-15T10:00:00Z INFO pressure=3.5 nominal
        2024-01-15T10:00:05Z INFO pressure=3.2 nominal
        2024-01-15T10:00:10Z WARN pressure=1.8 below threshold
        2024-01-15T10:00:15Z ERROR pressure=0.5 critical
        2024-01-15T10:00:20Z INFO pressure=2.1 recovering
        """
        )
    )

    plc = tmp_path / "plc_motor.log"
    plc.write_text(
        textwrap.dedent(
            """\
        2024-01-15T10:00:02Z INFO Motor running
        2024-01-15T10:00:12Z WARN Motor deceleration
        2024-01-15T10:00:14Z ERROR Motor stalled
        2024-01-15T10:00:22Z INFO Motor restarting
        """
        )
    )

    return {
        "sensor": str(sensor),
        "plc": str(plc),
    }


def _make_mock_search(log_files_dict):
    """Create a mock search that reads from actual files with time filtering."""
    from datetime import datetime

    # Pre-parse entries from files
    file_entries = {}
    for file_path in log_files_dict.values():
        entries = []
        with open(file_path) as f:
            for i, line in enumerate(f.readlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(" ", 2)
                ts = parts[0] if len(parts) > 0 else ""
                level = parts[1] if len(parts) > 1 else "INFO"
                message = parts[2] if len(parts) > 2 else ""
                entries.append(
                    {
                        "entry": {
                            "file": file_path,
                            "line_number": i,
                            "timestamp": ts.replace("Z", "+00:00"),
                            "level": level,
                            "message": message,
                            "raw": line,
                        }
                    }
                )
        file_entries[file_path] = entries

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
                level_filter = kwargs.get("level")
                if level_filter:
                    if entry.get("level", "").upper() != level_filter.upper():
                        continue
                query = kwargs.get("query")
                if query:
                    msg = entry.get("message", "") + entry.get("raw", "")
                    if query.lower() not in msg.lower():
                        continue
                results.append(item)
        return {"results": results, "total": len(results)}

    return mock_search


class TestCorrelateEventsCmd:
    """Test 'logler llm correlate-events' command."""

    def test_anchor_timestamp(self, runner, log_files):
        """Correlating around a timestamp returns events within window."""
        mock_search = _make_mock_search(log_files)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = runner.invoke(
                llm,
                [
                    "correlate-events",
                    "-f",
                    log_files["sensor"],
                    "-f",
                    log_files["plc"],
                    "--anchor-timestamp",
                    "2024-01-15T10:00:13+00:00",
                    "--window",
                    "5s",
                    "--pretty",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS, f"Output: {result.output}"
        data = json.loads(result.output)

        assert data["files_searched"] == 2
        assert data["window"] == "5s"
        assert data["total_clusters"] == 1

        cluster = data["clusters"][0]
        assert cluster["rule_type"] == "event_window"
        assert cluster["virtual_trace_id"].startswith("vt-")
        assert cluster["entry_count"] > 0

    def test_trigger_level(self, runner, log_files):
        """Trigger-based correlation finds events around ERROR entries."""
        mock_search = _make_mock_search(log_files)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = runner.invoke(
                llm,
                [
                    "correlate-events",
                    "-f",
                    log_files["sensor"],
                    "-f",
                    log_files["plc"],
                    "--trigger-level",
                    "ERROR",
                    "--window",
                    "3s",
                    "--pretty",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS, f"Output: {result.output}"
        data = json.loads(result.output)

        assert data["total_clusters"] >= 1
        for cluster in data["clusters"]:
            assert cluster["rule_type"] == "event_trigger"
            assert cluster["entry_count"] > 1

    def test_no_mode_specified(self, runner, log_files):
        """Returns error when no correlation mode is specified."""
        result = runner.invoke(
            llm,
            [
                "correlate-events",
                "-f",
                log_files["sensor"],
            ],
        )

        assert result.exit_code == EXIT_USER_ERROR
        data = json.loads(result.output)
        assert "error" in data

    def test_no_matching_files(self, runner, tmp_path):
        """Returns error when no files match the glob."""
        result = runner.invoke(
            llm,
            [
                "correlate-events",
                "-f",
                str(tmp_path / "nonexistent_*.log"),
                "--anchor-timestamp",
                "2024-01-15T10:00:00+00:00",
            ],
        )

        assert result.exit_code == EXIT_USER_ERROR
        data = json.loads(result.output)
        assert "error" in data

    def test_limit_clusters(self, runner, log_files):
        """The --limit flag restricts cluster count."""
        mock_search = _make_mock_search(log_files)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = runner.invoke(
                llm,
                [
                    "correlate-events",
                    "-f",
                    log_files["sensor"],
                    "-f",
                    log_files["plc"],
                    "--trigger-level",
                    "ERROR",
                    "--window",
                    "3s",
                    "--limit",
                    "1",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS, f"Output: {result.output}"
        data = json.loads(result.output)
        assert len(data["clusters"]) <= 1

    def test_entries_have_condensed_format(self, runner, log_files):
        """Cluster entries use filename-only paths and truncated messages."""
        mock_search = _make_mock_search(log_files)

        with patch("logler.event_correlator.investigate.search", side_effect=mock_search):
            result = runner.invoke(
                llm,
                [
                    "correlate-events",
                    "-f",
                    log_files["sensor"],
                    "-f",
                    log_files["plc"],
                    "--anchor-timestamp",
                    "2024-01-15T10:00:13+00:00",
                    "--window",
                    "5s",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS, f"Output: {result.output}"
        data = json.loads(result.output)

        for cluster in data["clusters"]:
            for entry in cluster["entries"]:
                assert "file" in entry
                assert "level" in entry
                # Should be filename only (no directory separators)
                assert "/" not in entry["file"]
