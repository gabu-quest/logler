"""Tests for LLM CLI correlation commands (M2.4)."""

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
EXIT_INTERNAL_ERROR = 3


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def correlations_dir(tmp_path: Path) -> Path:
    """Create a .logler directory with a correlations.yaml config."""
    config_dir = tmp_path / ".logler"
    config_dir.mkdir()
    (config_dir / "correlations.yaml").write_text(
        textwrap.dedent(
            """\
        correlations:
          batch-tracking:
            description: "Link MES batch IDs to PLC lot numbers"
            rules:
              - type: field_match
                source:
                  file_pattern: "mes_*.log"
                  field: batch_id
                target:
                  file_pattern: "plc_*.log"
                  field: lot_number
          pressure-alarm:
            description: "Correlate pressure drops with events"
            rules:
              - type: temporal
                anchor:
                  file_pattern: "sensor_*.log"
                  field: pressure
                  condition: "< 2.0"
                window: "5s"
    """
        )
    )
    return tmp_path


@pytest.fixture
def empty_correlations_dir(tmp_path: Path) -> Path:
    """Create a .logler directory with empty correlations config."""
    config_dir = tmp_path / ".logler"
    config_dir.mkdir()
    (config_dir / "correlations.yaml").write_text("correlations: {}\n")
    return tmp_path


# =============================================================================
# correlation list
# =============================================================================


class TestCorrelationList:
    """Test 'logler llm correlation list' command."""

    def test_list_groups(self, runner, correlations_dir):
        """Lists all correlation groups with rule summaries."""
        result = runner.invoke(
            llm,
            ["correlation", "list", "--config-dir", str(correlations_dir), "--pretty"],
        )
        assert result.exit_code == EXIT_SUCCESS
        data = json.loads(result.output)

        assert data["config_path"] is not None
        assert "batch-tracking" in data["groups"]
        assert "pressure-alarm" in data["groups"]

        batch = data["groups"]["batch-tracking"]
        assert batch["description"] == "Link MES batch IDs to PLC lot numbers"
        assert batch["rule_count"] == 1
        assert batch["rules"][0]["type"] == "field_match"
        assert batch["rules"][0]["source_field"] == "batch_id"
        assert batch["rules"][0]["target_field"] == "lot_number"

        pressure = data["groups"]["pressure-alarm"]
        assert pressure["rule_count"] == 1
        assert pressure["rules"][0]["type"] == "temporal"
        assert pressure["rules"][0]["window"] == "5s"
        assert pressure["rules"][0]["anchor"]["field"] == "pressure"
        assert pressure["rules"][0]["anchor"]["condition"] == "< 2.0"

    def test_list_no_config_found(self, runner, tmp_path):
        """Returns no-results when no correlations.yaml exists."""
        result = runner.invoke(
            llm,
            ["correlation", "list", "--config-dir", str(tmp_path)],
        )
        assert result.exit_code == EXIT_NO_RESULTS
        data = json.loads(result.output)
        assert "error" in data
        assert "No .logler/correlations.yaml found" in data["error"]

    def test_list_empty_config(self, runner, empty_correlations_dir):
        """Returns no-results when config has no correlation groups."""
        result = runner.invoke(
            llm,
            ["correlation", "list", "--config-dir", str(empty_correlations_dir)],
        )
        assert result.exit_code == EXIT_NO_RESULTS
        data = json.loads(result.output)
        assert data["groups"] == {}

    def test_list_invalid_config(self, runner, tmp_path):
        """Returns error when correlations.yaml is malformed."""
        config_dir = tmp_path / ".logler"
        config_dir.mkdir()
        (config_dir / "correlations.yaml").write_text("not: valid: yaml: {{{\n")

        result = runner.invoke(
            llm,
            ["correlation", "list", "--config-dir", str(tmp_path)],
        )
        assert result.exit_code == EXIT_USER_ERROR
        data = json.loads(result.output)
        assert "config_error" in data


# =============================================================================
# correlation run
# =============================================================================


class TestCorrelationRun:
    """Test 'logler llm correlation run' command."""

    def test_run_no_config(self, runner, tmp_path):
        """Returns error when no correlations.yaml exists."""
        # Create a dummy log file
        log_file = tmp_path / "test.log"
        log_file.write_text("2024-01-15T10:00:00Z INFO test\n")

        result = runner.invoke(
            llm,
            [
                "correlation",
                "run",
                "-f",
                str(log_file),
                "--config-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == EXIT_USER_ERROR
        data = json.loads(result.output)
        assert "error" in data

    def test_run_no_matching_files(self, runner, correlations_dir):
        """Returns error when no files match the glob."""
        result = runner.invoke(
            llm,
            [
                "correlation",
                "run",
                "-f",
                str(correlations_dir / "nonexistent_*.log"),
                "--config-dir",
                str(correlations_dir),
            ],
        )
        assert result.exit_code == EXIT_USER_ERROR
        data = json.loads(result.output)
        assert "error" in data

    def test_run_with_entries(self, runner, correlations_dir):
        """Run correlation with mocked entries to verify output structure."""
        # Create log files
        mes_log = correlations_dir / "mes_prod.log"
        mes_log.write_text(
            "2024-01-15T10:00:00Z INFO Batch B-042 started\n"
            "2024-01-15T10:05:00Z INFO Batch B-042 completed\n"
        )
        plc_log = correlations_dir / "plc_motor.log"
        plc_log.write_text("2024-01-15T10:01:00Z INFO Motor running for lot B-042\n")

        # Mock investigate.search to return entries with the needed fields
        mock_entries = {
            str(mes_log): [
                {
                    "entry": {
                        "file": str(mes_log),
                        "line_number": 1,
                        "timestamp": "2024-01-15T10:00:00+00:00",
                        "level": "INFO",
                        "message": "Batch B-042 started",
                        "fields": {"batch_id": "B-042"},
                    }
                },
                {
                    "entry": {
                        "file": str(mes_log),
                        "line_number": 2,
                        "timestamp": "2024-01-15T10:05:00+00:00",
                        "level": "INFO",
                        "message": "Batch B-042 completed",
                        "fields": {"batch_id": "B-042"},
                    }
                },
            ],
            str(plc_log): [
                {
                    "entry": {
                        "file": str(plc_log),
                        "line_number": 1,
                        "timestamp": "2024-01-15T10:01:00+00:00",
                        "level": "INFO",
                        "message": "Motor running for lot B-042",
                        "fields": {"lot_number": "B-042"},
                    }
                },
            ],
        }

        def mock_search(files, **kwargs):
            file_path = files[0]
            return {"results": mock_entries.get(file_path, [])}

        with patch("logler.investigate.search", side_effect=mock_search):
            result = runner.invoke(
                llm,
                [
                    "correlation",
                    "run",
                    "-f",
                    str(mes_log),
                    "-f",
                    str(plc_log),
                    "--config-dir",
                    str(correlations_dir),
                    "--rule",
                    "batch-tracking",
                    "--pretty",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS, f"Output: {result.output}"
        data = json.loads(result.output)

        assert data["files_searched"] == 2
        assert data["entries_loaded"] == 3
        assert data["groups_applied"] == ["batch-tracking"]
        assert data["total_clusters"] == 1
        assert data["total_entries_correlated"] == 3

        cluster = data["clusters"][0]
        assert cluster["rule_type"] == "field_match"
        assert cluster["shared_value"] == "B-042"
        assert cluster["source_count"] == 2
        assert cluster["target_count"] == 1
        assert cluster["virtual_trace_id"].startswith("vt-")

        # Entries should have condensed format
        for entry in cluster["entries"]:
            assert "file" in entry
            assert "level" in entry
            assert "/" not in entry["file"]  # filename only

    def test_run_with_limit(self, runner, correlations_dir):
        """The --limit flag restricts cluster count."""
        mes_log = correlations_dir / "mes_prod.log"
        mes_log.write_text("2024-01-15T10:00:00Z INFO test\n")
        plc_log = correlations_dir / "plc_motor.log"
        plc_log.write_text("2024-01-15T10:00:00Z INFO test\n")

        # Mock 3 clusters
        mock_entries = {
            str(mes_log): [
                {"entry": {"file": str(mes_log), "fields": {"batch_id": f"B-{i}"}}}
                for i in range(3)
            ],
            str(plc_log): [
                {"entry": {"file": str(plc_log), "fields": {"lot_number": f"B-{i}"}}}
                for i in range(3)
            ],
        }

        def mock_search(files, **kwargs):
            return {"results": mock_entries.get(files[0], [])}

        with patch("logler.investigate.search", side_effect=mock_search):
            result = runner.invoke(
                llm,
                [
                    "correlation",
                    "run",
                    "-f",
                    str(mes_log),
                    "-f",
                    str(plc_log),
                    "--config-dir",
                    str(correlations_dir),
                    "--rule",
                    "batch-tracking",
                    "--limit",
                    "1",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        data = json.loads(result.output)
        assert len(data["clusters"]) == 1
        assert data["total_clusters"] == 3  # Total is still 3

    def test_run_empty_config(self, runner, empty_correlations_dir):
        """Returns error when config has no rules."""
        log = empty_correlations_dir / "test.log"
        log.write_text("2024-01-15T10:00:00Z INFO test\n")

        result = runner.invoke(
            llm,
            [
                "correlation",
                "run",
                "-f",
                str(log),
                "--config-dir",
                str(empty_correlations_dir),
            ],
        )
        assert result.exit_code == EXIT_USER_ERROR
        data = json.loads(result.output)
        assert "error" in data
