"""Tests for logler.config - BYOLF config file loader."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from logler.config import (
    FormatConfig,
    LoglerConfig,
    find_config,
    get_format_for_file,
    load_config,
)


# =============================================================================
# Valid Config Loading
# =============================================================================


class TestLoadValidConfig:
    """Test loading well-formed .logler/formats.yaml files."""

    def test_load_multiple_manufacturing_formats(self, tmp_path: Path) -> None:
        """Load a config with multiple realistic manufacturing log formats."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            formats:
              siemens_plc:
                regex: '(?P<timestamp>[\\d/]+ [\\d:.]+) (?P<level>\\w+) (?P<message>.*)'
                timestamp_format: "%Y/%m/%d %H:%M:%S.%f"
                file_patterns:
                  - "plc_*.log"
                  - "siemens_*.log"
              fanuc_robot:
                regex: '(?P<timestamp>[\\d-]+ [\\d:]+) (?P<axis>[A-Z]\\d) (?P<level>ALARM|WARN|INFO) (?P<message>.*)'
                file_patterns:
                  - "robot_*.log"
                  - "fanuc_*.log"
        """
            )
        )

        config = load_config(config_file)

        assert len(config.formats) == 2
        assert "siemens_plc" in config.formats
        assert "fanuc_robot" in config.formats

        plc = config.formats["siemens_plc"]
        assert plc.timestamp_format == "%Y/%m/%d %H:%M:%S.%f"
        assert plc.file_patterns == ["plc_*.log", "siemens_*.log"]

        robot = config.formats["fanuc_robot"]
        assert robot.timestamp_format is None
        assert robot.file_patterns == ["robot_*.log", "fanuc_*.log"]

    def test_load_sensor_format_with_named_groups(self, tmp_path: Path) -> None:
        """Regex named groups are validated and preserved."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            formats:
              temperature_sensor:
                regex: '(?P<timestamp>[\\d.]+) SENSOR (?P<sensor_id>[\\w-]+) temp=(?P<value>[\\d.]+)C (?P<level>OK|WARN|CRIT)'
                file_patterns: ["sensor_*.csv"]
        """
            )
        )

        config = load_config(config_file)
        fmt = config.formats["temperature_sensor"]

        compiled = re.compile(fmt.regex)
        match = compiled.match("1706140800.123 SENSOR TH-042 temp=85.3C WARN")
        assert match is not None
        assert match.group("sensor_id") == "TH-042"
        assert match.group("value") == "85.3"
        assert match.group("level") == "WARN"

    def test_load_format_without_file_patterns(self, tmp_path: Path) -> None:
        """Formats without file_patterns get an empty list by default."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            formats:
              generic:
                regex: '(?P<message>.+)'
        """
            )
        )

        config = load_config(config_file)
        assert config.formats["generic"].file_patterns == []

    def test_load_empty_file_returns_empty_config(self, tmp_path: Path) -> None:
        """An empty YAML file returns a LoglerConfig with no formats."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("")

        config = load_config(config_file)
        assert isinstance(config, LoglerConfig)
        assert config.formats == {}

    def test_load_empty_formats_returns_empty_config(self, tmp_path: Path) -> None:
        """A YAML file with formats: {} returns an empty formats dict."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("formats: {}\n")

        config = load_config(config_file)
        assert config.formats == {}


# =============================================================================
# find_config - Parent Directory Walking
# =============================================================================


class TestFindConfig:
    """Test .logler/formats.yaml discovery via parent directory walking."""

    def test_find_in_current_directory(self, tmp_path: Path) -> None:
        """Config is found in the start directory itself."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("formats: {}\n")

        result = find_config(tmp_path)
        assert result is not None
        assert result == config_file

    def test_find_in_parent_directory(self, tmp_path: Path) -> None:
        """Config is found by walking up to a parent directory."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("formats: {}\n")

        nested = tmp_path / "project" / "logs" / "2024"
        nested.mkdir(parents=True)

        result = find_config(nested)
        assert result is not None
        assert result == config_file

    def test_find_in_grandparent_directory(self, tmp_path: Path) -> None:
        """Config discovery walks multiple levels up."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("formats: {}\n")

        deep = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)

        result = find_config(deep)
        assert result is not None
        assert result == config_file

    def test_returns_none_when_no_config_exists(self, tmp_path: Path) -> None:
        """Returns None when no .logler/formats.yaml exists anywhere."""
        nested = tmp_path / "project" / "src"
        nested.mkdir(parents=True)

        result = find_config(nested)
        assert result is None

    def test_finds_nearest_config(self, tmp_path: Path) -> None:
        """When configs exist at multiple levels, the nearest one wins."""
        parent_config = tmp_path / ".logler" / "formats.yaml"
        parent_config.parent.mkdir(parents=True)
        parent_config.write_text("formats: {}\n")

        child_dir = tmp_path / "project"
        child_config = child_dir / ".logler" / "formats.yaml"
        child_config.parent.mkdir(parents=True)
        child_config.write_text("formats: {}\n")

        start = child_dir / "src"
        start.mkdir(parents=True)

        result = find_config(start)
        assert result == child_config


# =============================================================================
# File Pattern Matching
# =============================================================================


class TestGetFormatForFile:
    """Test matching filenames against format file_patterns."""

    def test_plc_log_matches_plc_pattern(self) -> None:
        """plc_001.log matches the plc_*.log glob pattern."""
        config = LoglerConfig(
            formats={
                "siemens_plc": FormatConfig(
                    regex=r"(?P<message>.+)",
                    file_patterns=["plc_*.log"],
                ),
            }
        )

        result = get_format_for_file(config, "plc_001.log")
        assert result is not None
        assert result.file_patterns == ["plc_*.log"]

    def test_robot_log_matches_fanuc_pattern(self) -> None:
        """robot_arm_3.log matches robot_*.log."""
        config = LoglerConfig(
            formats={
                "fanuc": FormatConfig(
                    regex=r"(?P<level>\w+) (?P<message>.+)",
                    file_patterns=["robot_*.log", "fanuc_*.log"],
                ),
            }
        )

        result = get_format_for_file(config, "robot_arm_3.log")
        assert result is not None

    def test_no_match_returns_none(self) -> None:
        """A file that matches no patterns returns None."""
        config = LoglerConfig(
            formats={
                "plc": FormatConfig(
                    regex=r"(?P<message>.+)",
                    file_patterns=["plc_*.log"],
                ),
            }
        )

        result = get_format_for_file(config, "application.log")
        assert result is None

    def test_empty_config_returns_none(self) -> None:
        """An empty config matches nothing."""
        config = LoglerConfig()
        result = get_format_for_file(config, "anything.log")
        assert result is None

    def test_full_path_uses_filename_only(self) -> None:
        """Only the filename part of the path is matched."""
        config = LoglerConfig(
            formats={
                "sensor": FormatConfig(
                    regex=r"(?P<value>\d+)",
                    file_patterns=["sensor_*.csv"],
                ),
            }
        )

        result = get_format_for_file(config, "/var/log/factory/sensor_temp.csv")
        assert result is not None

    def test_first_matching_format_wins(self) -> None:
        """When multiple formats match, the first one in iteration order wins."""
        config = LoglerConfig(
            formats={
                "format_a": FormatConfig(
                    regex=r"(?P<msg_a>.+)",
                    file_patterns=["*.log"],
                ),
                "format_b": FormatConfig(
                    regex=r"(?P<msg_b>.+)",
                    file_patterns=["*.log"],
                ),
            }
        )

        result = get_format_for_file(config, "any.log")
        assert result is not None
        assert "msg_a" in re.compile(result.regex).groupindex


# =============================================================================
# Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error cases: invalid YAML, bad regex, missing files."""

    def test_invalid_yaml_raises_valueerror(self, tmp_path: Path) -> None:
        """Malformed YAML produces a clear ValueError."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("formats:\n  bad:\n    - [invalid yaml {{{\n")

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config(config_file)

    def test_invalid_regex_raises_validation_error(self, tmp_path: Path) -> None:
        """A regex that fails to compile raises a pydantic ValidationError."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            formats:
              broken:
                regex: '(?P<ts>[unclosed'
        """
            )
        )

        with pytest.raises(ValidationError):
            load_config(config_file)

    def test_regex_without_named_groups_raises_validation_error(self, tmp_path: Path) -> None:
        """A regex with no named groups raises a ValidationError."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            formats:
              no_groups:
                regex: '\\d{4}-\\d{2}-\\d{2} .+'
        """
            )
        )

        with pytest.raises(ValidationError, match="named group"):
            load_config(config_file)

    def test_missing_file_raises_filenotfounderror(self, tmp_path: Path) -> None:
        """Loading a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(tmp_path / "does_not_exist.yaml")

    def test_non_dict_yaml_raises_valueerror(self, tmp_path: Path) -> None:
        """YAML that parses to a non-dict (e.g., a list) raises ValueError."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("- item1\n- item2\n")

        with pytest.raises(ValueError, match="Expected a YAML mapping"):
            load_config(config_file)

    def test_extra_fields_rejected(self, tmp_path: Path) -> None:
        """Unknown fields in the config are rejected (extra=forbid)."""
        config_file = tmp_path / ".logler" / "formats.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            textwrap.dedent(
                """\
            formats:
              test:
                regex: '(?P<message>.+)'
                unknown_field: "should fail"
        """
            )
        )

        with pytest.raises(ValidationError):
            load_config(config_file)


# =============================================================================
# Realistic Manufacturing Scenarios
# =============================================================================


class TestManufacturingScenarios:
    """End-to-end tests with realistic industrial log format examples."""

    def test_plc_log_format_parses_real_line(self) -> None:
        """Siemens PLC format regex matches a realistic PLC log line."""
        plc_regex = (
            r"^\[(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\] "
            r"(?P<level>\w+) \| (?P<device>[^|]+)\| (?P<message>.*)"
        )
        fmt = FormatConfig(
            regex=plc_regex,
            timestamp_format="%Y/%m/%d %H:%M:%S.%f",
            file_patterns=["plc_*.log"],
        )

        compiled = re.compile(fmt.regex)
        line = "[2024/01/15 14:30:22.456] ERROR | PLC-S7-1500-01| Conveyor belt motor overload detected"
        match = compiled.match(line)

        assert match is not None
        assert match.group("timestamp") == "2024/01/15 14:30:22.456"
        assert match.group("level") == "ERROR"
        assert match.group("device") == "PLC-S7-1500-01"
        assert match.group("message") == "Conveyor belt motor overload detected"

    def test_robot_arm_format_parses_alarm(self) -> None:
        """FANUC robot arm format regex matches alarm lines."""
        robot_regex = (
            r"(?P<timestamp>\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}) "
            r"(?P<axis>[A-Z]\d) (?P<level>ALARM|WARN|INFO) (?P<message>.*)"
        )
        fmt = FormatConfig(
            regex=robot_regex,
            file_patterns=["robot_*.log", "fanuc_*.log"],
        )

        compiled = re.compile(fmt.regex)
        line = (
            "15-01-2024 14:30:22 J2 ALARM Servo overload on axis J2 - current 15.2A exceeds limit"
        )
        match = compiled.match(line)

        assert match is not None
        assert match.group("axis") == "J2"
        assert match.group("level") == "ALARM"
        assert "Servo overload" in match.group("message")

    def test_sensor_csv_format_parses_data_line(self) -> None:
        """Industrial sensor CSV format with temperature readings."""
        sensor_regex = (
            r"(?P<timestamp>[\d.]+),(?P<sensor_id>[\w-]+),"
            r"(?P<value>[\d.]+),(?P<unit>\w+),(?P<level>OK|WARN|CRIT)"
        )
        fmt = FormatConfig(
            regex=sensor_regex,
            file_patterns=["sensor_*.csv"],
        )

        compiled = re.compile(fmt.regex)
        line = "1706140822.500,TH-042,92.7,celsius,CRIT"
        match = compiled.match(line)

        assert match is not None
        assert match.group("sensor_id") == "TH-042"
        assert match.group("value") == "92.7"
        assert match.group("unit") == "celsius"
        assert match.group("level") == "CRIT"

    def test_full_workflow_find_load_match(self, tmp_path: Path) -> None:
        """Full workflow: find config, load it, match a file, use the regex."""
        config_dir = tmp_path / "factory" / ".logler"
        config_dir.mkdir(parents=True)
        (config_dir / "formats.yaml").write_text(
            textwrap.dedent(
                """\
            formats:
              cnc_machine:
                regex: '(?P<timestamp>[\\d:]+) \\[(?P<machine>CNC-[\\w-]+)\\] (?P<level>\\w+): (?P<message>.*)'
                timestamp_format: "%H:%M:%S"
                file_patterns: ["cnc_*.log"]
        """
            )
        )

        work_dir = tmp_path / "factory" / "line_3" / "logs"
        work_dir.mkdir(parents=True)

        config_path = find_config(work_dir)
        assert config_path is not None

        config = load_config(config_path)
        assert "cnc_machine" in config.formats

        fmt = get_format_for_file(config, "cnc_lathe_001.log")
        assert fmt is not None
        assert fmt.timestamp_format == "%H:%M:%S"

        compiled = re.compile(fmt.regex)
        match = compiled.match("14:30:22 [CNC-LATHE-01] WARN: Tool wear threshold 80% reached")
        assert match is not None
        assert match.group("machine") == "CNC-LATHE-01"
        assert match.group("level") == "WARN"
        assert "Tool wear" in match.group("message")
