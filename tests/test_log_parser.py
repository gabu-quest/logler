"""Tests for log parser."""

import pytest
import json
from logler.log_parser import LogParser, LogFormat, LogLevel


class TestLogParser:
    """Test LogParser class."""

    def test_init_with_colors(self):
        """Test parser initialization with colors enabled."""
        parser = LogParser(use_colors=True)
        assert parser.use_colors is True
        assert parser.format_type is None

    def test_init_without_colors(self):
        """Test parser initialization with colors disabled."""
        parser = LogParser(use_colors=False)
        assert parser.use_colors is False

    def test_detect_json_format(self):
        """Test JSON format detection."""
        parser = LogParser()
        line = '{"timestamp": "2024-01-01", "level": "INFO", "message": "test"}'
        assert parser._detect_format(line) == LogFormat.JSON

    def test_detect_plain_format(self):
        """Test plain format detection."""
        parser = LogParser()
        line = "2024-01-01 12:00:00 INFO This is a test"
        assert parser._detect_format(line) == LogFormat.PLAIN

    def test_detect_syslog_format(self):
        """Test syslog format detection."""
        parser = LogParser()
        line = "<134>Jan 1 12:00:00 hostname test message"
        assert parser._detect_format(line) == LogFormat.SYSLOG

    def test_parse_json_with_timestamp(self):
        """Test parsing JSON log with timestamp."""
        parser = LogParser(use_colors=False)
        data = {
            "timestamp": "2024-01-01T12:00:00Z",
            "level": "INFO",
            "message": "Test message"
        }
        line = json.dumps(data)
        result = parser.parse(line)
        assert "2024-01-01T12:00:00Z" in result
        assert "INFO" in result
        assert "Test message" in result

    def test_parse_json_with_extra_fields(self):
        """Test parsing JSON log with extra fields."""
        parser = LogParser(use_colors=False)
        data = {
            "timestamp": "2024-01-01T12:00:00Z",
            "level": "ERROR",
            "message": "Error occurred",
            "user_id": 123,
            "trace_id": "abc-def"
        }
        line = json.dumps(data)
        result = parser.parse(line)
        assert "user_id=123" in result
        assert "trace_id=abc-def" in result

    def test_parse_plain_log(self):
        """Test parsing plain text log."""
        parser = LogParser(use_colors=False)
        line = "2024-01-01 12:00:00 INFO Test message"
        result = parser.parse(line)
        assert "2024-01-01 12:00:00" in result
        assert "INFO" in result
        assert "Test message" in result

    def test_extract_level_from_plain(self):
        """Test extracting log level from plain text."""
        parser = LogParser()
        line = "2024-01-01 12:00:00 ERROR Something went wrong"
        level = parser.extract_level(line)
        assert level == "ERROR"

    def test_extract_level_from_json(self):
        """Test extracting log level from JSON."""
        parser = LogParser()
        data = {"level": "warn", "message": "Warning message"}
        line = json.dumps(data)
        level = parser.extract_level(line)
        assert level == "WARN"

    def test_extract_level_none(self):
        """Test extracting level when none exists."""
        parser = LogParser()
        line = "Just a plain message without level"
        level = parser.extract_level(line)
        assert level is None

    def test_colorize_disabled(self):
        """Test that colorize returns plain text when colors disabled."""
        parser = LogParser(use_colors=False)
        result = parser._colorize("test", "info")
        assert result == "test"
        assert "\033[" not in result

    def test_colorize_enabled(self):
        """Test that colorize adds ANSI codes when enabled."""
        parser = LogParser(use_colors=True)
        result = parser._colorize("test", "info")
        assert "\033[" in result
        assert "test" in result

    def test_get_level_color(self):
        """Test level color mapping."""
        parser = LogParser()
        assert parser._get_level_color("DEBUG") == "debug"
        assert parser._get_level_color("INFO") == "info"
        assert parser._get_level_color("WARN") == "warn"
        assert parser._get_level_color("ERROR") == "error"
        assert parser._get_level_color("CRITICAL") == "critical"

    def test_parse_empty_line(self):
        """Test parsing empty line."""
        parser = LogParser()
        result = parser.parse("")
        assert result == ""

    def test_parse_malformed_json(self):
        """Test parsing malformed JSON falls back to plain."""
        parser = LogParser(use_colors=False)
        line = '{"incomplete": "json"'
        result = parser.parse(line)
        assert result == line

    def test_forced_format(self):
        """Test forcing a specific format."""
        parser = LogParser(format_type=LogFormat.PLAIN, use_colors=False)
        line = '{"timestamp": "2024-01-01", "level": "INFO"}'
        # Should be parsed as plain, not JSON
        result = parser.parse(line)
        # Plain parsing doesn't extract JSON fields, so result should equal input
        assert '"timestamp"' in result
        assert '"level"' in result
        assert '"INFO"' in result

    def test_parse_common_log_format(self):
        """Test parsing Apache common log format."""
        parser = LogParser(use_colors=False)
        line = '192.168.1.1 - - [01/Jan/2024:12:00:00 +0000] "GET /index.html HTTP/1.1" 200 1234'
        result = parser.parse(line)
        assert "192.168.1.1" in result
        assert "01/Jan/2024:12:00:00 +0000" in result
        assert "200" in result
