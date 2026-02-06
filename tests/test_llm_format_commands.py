"""Tests for the LLM CLI format command group (M1.3).

Tests format list, format test, and format validate subcommands.
"""

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from logler.llm_cli import llm


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_log(tmp_path):
    """Create a sample nginx-style log file."""
    log_file = tmp_path / "access.log"
    log_file.write_text(
        textwrap.dedent(
            """\
        192.168.1.1 - admin [10/Oct/2024:13:55:36 +0000] "GET /api/health HTTP/1.1" 200 524 "-" "curl/7.88.1"
        192.168.1.2 - - [10/Oct/2024:13:55:37 +0000] "POST /api/login HTTP/1.1" 401 128 "-" "Mozilla/5.0"
        192.168.1.1 - admin [10/Oct/2024:13:55:38 +0000] "GET /api/users HTTP/1.1" 200 2048 "-" "curl/7.88.1"
        """
        )
    )
    return str(log_file)


@pytest.fixture
def config_dir(tmp_path):
    """Create a .logler/formats.yaml config directory."""
    logler_dir = tmp_path / ".logler"
    logler_dir.mkdir()
    config_file = logler_dir / "formats.yaml"
    config_file.write_text(
        textwrap.dedent(
            """\
        formats:
          plc_alarm:
            regex: '\\[(?P<timestamp>[\\d/]+ [\\d:.]+)\\] (?P<level>\\w+) \\| (?P<device>[^|]+)\\| (?P<message>.*)'
            timestamp_format: "%Y/%m/%d %H:%M:%S.%f"
            file_patterns: ["plc_*.log"]
          sensor_csv:
            regex: '(?P<timestamp>[\\d-]+ [\\d:]+),(?P<sensor_id>[\\w-]+),(?P<message>.*)'
            file_patterns: ["sensor_*.csv"]
    """
        )
    )
    return str(tmp_path)


class TestFormatList:
    """Tests for `logler llm format list`."""

    def test_list_builtin_formats(self, runner):
        result = runner.invoke(llm, ["format", "list", "--pretty"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "builtin_formats" in data
        assert len(data["builtin_formats"]) >= 10  # We have 14 built-ins
        assert "nginx_access" in data["builtin_formats"]
        assert "log4j" in data["builtin_formats"]

    def test_list_builtin_has_regex_and_patterns(self, runner):
        result = runner.invoke(llm, ["format", "list"])
        data = json.loads(result.output)
        nginx = data["builtin_formats"]["nginx_access"]
        assert "regex" in nginx
        assert "file_patterns" in nginx
        assert len(nginx["file_patterns"]) > 0

    def test_list_no_builtin(self, runner):
        result = runner.invoke(llm, ["format", "list", "--no-builtin"])
        data = json.loads(result.output)
        assert data["builtin_formats"] == {}

    def test_list_with_user_config(self, runner, config_dir):
        result = runner.invoke(llm, ["format", "list", "--config-dir", config_dir, "--pretty"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["config_path"] is not None
        assert "plc_alarm" in data["user_formats"]
        assert "sensor_csv" in data["user_formats"]

    def test_list_no_config_returns_empty_user_formats(self, runner, tmp_path):
        result = runner.invoke(llm, ["format", "list", "--config-dir", str(tmp_path)])
        data = json.loads(result.output)
        assert data["user_formats"] == {}
        assert data["config_path"] is None


class TestFormatTest:
    """Tests for `logler llm format test`."""

    def test_test_with_inline_regex(self, runner, sample_log):
        regex = (
            r"(?P<remote_addr>[\d.]+) - (?P<remote_user>\S+) "
            r'\[(?P<timestamp>[^\]]+)\] "(?P<method>\w+) (?P<path>\S+) \S+" '
            r"(?P<status>\d+) (?P<body_bytes>\d+) "
            r'"(?P<referer>[^"]*)" "(?P<message>[^"]*)"'
        )
        result = runner.invoke(llm, ["format", "test", "-f", sample_log, "-r", regex, "--pretty"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["matched_lines"] == 3
        assert data["total_lines"] == 3
        assert data["match_rate_percent"] == 100.0
        assert "remote_addr" in data["named_groups"]
        assert "timestamp" in data["named_groups"]

    def test_test_with_builtin_name(self, runner, sample_log):
        result = runner.invoke(
            llm,
            ["format", "test", "-f", sample_log, "-n", "nginx_access", "--pretty"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["format_source"] == "builtin"
        assert data["matched_lines"] == 3

    def test_test_with_user_format_name(self, runner, config_dir):
        # Create a PLC log file that matches
        plc_log = Path(config_dir) / "plc_001.log"
        plc_log.write_text(
            "[2024/01/15 08:30:22.456] ALARM | PRESS-A1 | Pressure below threshold\n"
            "[2024/01/15 08:30:23.789] INFO | PRESS-A1 | Pressure restored\n"
        )
        result = runner.invoke(
            llm,
            [
                "format",
                "test",
                "-f",
                str(plc_log),
                "-n",
                "plc_alarm",
                "--pretty",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["format_source"] == "user_config"
        assert data["matched_lines"] == 2

    def test_test_no_match(self, runner, tmp_path):
        garbage_log = tmp_path / "garbage.log"
        garbage_log.write_text("just some random text\nanother line\n")
        regex = r"(?P<timestamp>\d{4}-\d{2}-\d{2}) (?P<message>.*)"
        result = runner.invoke(llm, ["format", "test", "-f", str(garbage_log), "-r", regex])
        assert result.exit_code == 1  # EXIT_NO_RESULTS
        data = json.loads(result.output)
        assert data["matched_lines"] == 0

    def test_test_invalid_regex(self, runner, sample_log):
        result = runner.invoke(llm, ["format", "test", "-f", sample_log, "-r", "(?P<broken"])
        assert result.exit_code == 2  # EXIT_USER_ERROR
        data = json.loads(result.output)
        assert "error" in data

    def test_test_unknown_format_name(self, runner, sample_log):
        result = runner.invoke(
            llm, ["format", "test", "-f", sample_log, "-n", "nonexistent_format"]
        )
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert "not found" in data["error"]

    def test_test_requires_files(self, runner):
        result = runner.invoke(llm, ["format", "test", "-r", "(?P<m>.*)"])
        assert result.exit_code != 0  # Click should error on missing -f

    def test_test_results_contain_groups(self, runner, sample_log):
        regex = r"(?P<ip>[\d.]+) - (?P<user>\S+) (?P<rest>.*)"
        result = runner.invoke(llm, ["format", "test", "-f", sample_log, "-r", regex])
        data = json.loads(result.output)
        matched = [r for r in data["results"] if r["matched"]]
        assert len(matched) == 3
        assert matched[0]["groups"]["ip"] == "192.168.1.1"
        assert matched[0]["groups"]["user"] == "admin"


class TestFormatValidate:
    """Tests for `logler llm format validate`."""

    def test_validate_good_regex(self, runner):
        regex = r"(?P<timestamp>\d{4}-\d{2}-\d{2}) (?P<level>\w+) (?P<message>.*)"
        result = runner.invoke(llm, ["format", "validate", "-r", regex, "--pretty"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True
        assert "timestamp" in data["named_groups"]
        assert "level" in data["named_groups"]
        assert "message" in data["named_groups"]
        assert len(data["issues"]) == 0

    def test_validate_regex_missing_recommended(self, runner):
        regex = r"(?P<data>.*)"
        result = runner.invoke(llm, ["format", "validate", "-r", regex])
        data = json.loads(result.output)
        # Still valid but with warnings about missing recommended groups
        assert data["valid"] is True
        assert len(data["issues"]) > 0
        assert any("Missing recommended" in i for i in data["issues"])

    def test_validate_regex_no_named_groups(self, runner):
        regex = r"(\d+) (\w+) (.*)"
        result = runner.invoke(llm, ["format", "validate", "-r", regex])
        data = json.loads(result.output)
        assert data["valid"] is False
        assert any("no named groups" in i for i in data["issues"])

    def test_validate_invalid_regex(self, runner):
        result = runner.invoke(llm, ["format", "validate", "-r", "(?P<broken"])
        assert result.exit_code == 2  # EXIT_USER_ERROR
        data = json.loads(result.output)
        assert data["valid"] is False

    def test_validate_config_file(self, runner, config_dir):
        result = runner.invoke(
            llm,
            ["format", "validate", "--config-dir", config_dir, "--pretty"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["config_path"] is not None
        assert data["format_count"] == 2
        assert "plc_alarm" in data["formats"]
        assert "sensor_csv" in data["formats"]

    def test_validate_no_config_found(self, runner, tmp_path):
        result = runner.invoke(llm, ["format", "validate", "--config-dir", str(tmp_path)])
        assert result.exit_code == 1  # EXIT_NO_RESULTS
        data = json.loads(result.output)
        assert data["valid"] is False
        assert "No .logler/formats.yaml" in data["issues"][0]
