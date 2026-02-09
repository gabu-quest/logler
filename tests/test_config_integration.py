"""Integration tests for config auto-detection in the investigation pipeline.

Tests that _auto_detect_format_from_config correctly discovers and applies
.logler/formats.yaml when loading files.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from logler.investigate import _auto_detect_format_from_config


class TestAutoDetectFormatFromConfig:
    """Test _auto_detect_format_from_config used by _load_files_with_config."""

    def test_returns_regex_when_config_matches(self, tmp_path: Path) -> None:
        """Returns the regex from a matching format config."""
        config_dir = tmp_path / ".logler"
        config_dir.mkdir()
        (config_dir / "formats.yaml").write_text(
            textwrap.dedent(
                """\
            formats:
              plc:
                regex: '(?P<timestamp>[\\d/]+ [\\d:.]+) (?P<level>\\w+) (?P<message>.*)'
                file_patterns: ["plc_*.log"]
        """
            )
        )

        log_file = tmp_path / "plc_001.log"
        log_file.write_text("test\n")

        result = _auto_detect_format_from_config([str(log_file)])
        assert result is not None
        assert "(?P<timestamp>" in result

    def test_returns_none_when_no_config(self, tmp_path: Path) -> None:
        """Returns None when no .logler/formats.yaml exists."""
        log_file = tmp_path / "app.log"
        log_file.write_text("test\n")

        result = _auto_detect_format_from_config([str(log_file)])
        assert result is None

    def test_returns_none_when_no_match(self, tmp_path: Path) -> None:
        """Returns None when config exists but no format matches the file."""
        config_dir = tmp_path / ".logler"
        config_dir.mkdir()
        (config_dir / "formats.yaml").write_text(
            textwrap.dedent(
                """\
            formats:
              plc:
                regex: '(?P<message>.+)'
                file_patterns: ["plc_*.log"]
        """
            )
        )

        log_file = tmp_path / "application.log"
        log_file.write_text("test\n")

        result = _auto_detect_format_from_config([str(log_file)])
        assert result is None

    def test_returns_none_when_files_match_different_formats(self, tmp_path: Path) -> None:
        """Returns None when multiple files match different formats."""
        config_dir = tmp_path / ".logler"
        config_dir.mkdir()
        (config_dir / "formats.yaml").write_text(
            textwrap.dedent(
                """\
            formats:
              plc:
                regex: '(?P<plc_msg>.+)'
                file_patterns: ["plc_*.log"]
              sensor:
                regex: '(?P<sensor_msg>.+)'
                file_patterns: ["sensor_*.log"]
        """
            )
        )

        plc_file = tmp_path / "plc_001.log"
        plc_file.write_text("test\n")
        sensor_file = tmp_path / "sensor_temp.log"
        sensor_file.write_text("test\n")

        result = _auto_detect_format_from_config([str(plc_file), str(sensor_file)])
        assert result is None

    def test_returns_regex_when_all_files_match_same_format(self, tmp_path: Path) -> None:
        """Returns regex when all files match the same format."""
        config_dir = tmp_path / ".logler"
        config_dir.mkdir()
        (config_dir / "formats.yaml").write_text(
            textwrap.dedent(
                """\
            formats:
              plc:
                regex: '(?P<plc_msg>.+)'
                file_patterns: ["plc_*.log"]
        """
            )
        )

        f1 = tmp_path / "plc_001.log"
        f1.write_text("test\n")
        f2 = tmp_path / "plc_002.log"
        f2.write_text("test\n")

        result = _auto_detect_format_from_config([str(f1), str(f2)])
        assert result is not None
        assert "(?P<plc_msg>" in result

    def test_returns_none_on_empty_file_list(self) -> None:
        """Returns None for an empty file list."""
        result = _auto_detect_format_from_config([])
        assert result is None

    def test_handles_config_errors_gracefully(self, tmp_path: Path) -> None:
        """Config errors don't crash file loading — returns None."""
        config_dir = tmp_path / ".logler"
        config_dir.mkdir()
        (config_dir / "formats.yaml").write_text("not: valid: yaml: {{{")

        log_file = tmp_path / "plc_001.log"
        log_file.write_text("test\n")

        # Should return None, not raise
        result = _auto_detect_format_from_config([str(log_file)])
        assert result is None

    def test_unmatched_files_are_ignored(self, tmp_path: Path) -> None:
        """Files that don't match any format are ignored (only matched files count)."""
        config_dir = tmp_path / ".logler"
        config_dir.mkdir()
        (config_dir / "formats.yaml").write_text(
            textwrap.dedent(
                """\
            formats:
              plc:
                regex: '(?P<plc_msg>.+)'
                file_patterns: ["plc_*.log"]
        """
            )
        )

        plc_file = tmp_path / "plc_001.log"
        plc_file.write_text("test\n")
        other_file = tmp_path / "random.txt"
        other_file.write_text("test\n")

        # plc_001.log matches plc format, random.txt has no match
        # Since all matched files agree (only one matched), return the regex
        result = _auto_detect_format_from_config([str(plc_file), str(other_file)])
        assert result is not None
