"""Log parsing and formatting module."""

import re
import json
from typing import Optional, Dict, Any
from enum import Enum


class LogLevel(Enum):
    """Common log levels."""
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


class LogFormat(Enum):
    """Supported log formats."""
    PLAIN = "plain"
    JSON = "json"
    SYSLOG = "syslog"
    COMMON_LOG = "common"


class LogParser:
    """Parser for different log formats with syntax highlighting."""

    # ANSI color codes
    COLORS = {
        "reset": "\033[0m",
        "timestamp": "\033[36m",      # Cyan
        "debug": "\033[37m",           # White
        "info": "\033[32m",            # Green
        "warn": "\033[33m",            # Yellow
        "error": "\033[31m",           # Red
        "critical": "\033[35m",        # Magenta
        "level": "\033[1m",            # Bold
        "field": "\033[34m",           # Blue
    }

    # Common log patterns
    PATTERNS = {
        # ISO 8601 timestamp
        "timestamp": r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?',
        # Log level
        "level": r'\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL|FATAL)\b',
        # Syslog priority
        "syslog_priority": r'^<\d+>',
        # Common log format (Apache style)
        "common_log": r'^(\S+) \S+ \S+ \[([^\]]+)\] "([^"]+)" (\d+) (\S+)',
    }

    def __init__(self, use_colors: bool = True, format_type: Optional[LogFormat] = None):
        """
        Initialize the log parser.

        Args:
            use_colors: Whether to use ANSI colors for output
            format_type: Force a specific log format, or None to auto-detect
        """
        self.use_colors = use_colors
        self.format_type = format_type

    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled."""
        if not self.use_colors:
            return text
        return f"{self.COLORS[color]}{text}{self.COLORS['reset']}"

    def _detect_format(self, line: str) -> LogFormat:
        """Detect the log format of a line."""
        if self.format_type:
            return self.format_type

        line_stripped = line.strip()

        # Check for JSON
        if line_stripped.startswith('{'):
            try:
                json.loads(line_stripped)
                return LogFormat.JSON
            except (json.JSONDecodeError, ValueError):
                pass

        # Check for common log format
        if re.match(self.PATTERNS["common_log"], line):
            return LogFormat.COMMON_LOG

        # Check for syslog
        if re.match(self.PATTERNS["syslog_priority"], line):
            return LogFormat.SYSLOG

        return LogFormat.PLAIN

    def _get_level_color(self, level: str) -> str:
        """Get the color for a log level."""
        level_upper = level.upper()
        if level_upper in ["DEBUG", "TRACE"]:
            return "debug"
        elif level_upper in ["INFO"]:
            return "info"
        elif level_upper in ["WARN", "WARNING"]:
            return "warn"
        elif level_upper in ["ERROR"]:
            return "error"
        elif level_upper in ["CRITICAL", "FATAL"]:
            return "critical"
        return "reset"

    def _parse_json(self, line: str) -> str:
        """Parse and format JSON log line."""
        try:
            data = json.loads(line.strip())

            # Common JSON log fields
            parts = []

            # Timestamp
            for ts_field in ["timestamp", "time", "ts", "@timestamp", "datetime"]:
                if ts_field in data:
                    parts.append(self._colorize(str(data[ts_field]), "timestamp"))
                    break

            # Level
            for level_field in ["level", "severity", "loglevel"]:
                if level_field in data:
                    level = str(data[level_field])
                    color = self._get_level_color(level)
                    parts.append(self._colorize(f"[{level}]", color))
                    break

            # Message
            for msg_field in ["message", "msg", "text"]:
                if msg_field in data:
                    parts.append(str(data[msg_field]))
                    break

            # Other fields
            skip_fields = {"timestamp", "time", "ts", "@timestamp", "datetime",
                          "level", "severity", "loglevel", "message", "msg", "text"}
            other_fields = {k: v for k, v in data.items() if k not in skip_fields}

            if other_fields:
                formatted_fields = []
                for k, v in other_fields.items():
                    formatted_fields.append(
                        f"{self._colorize(k, 'field')}={json.dumps(v) if isinstance(v, (dict, list)) else v}"
                    )
                parts.append(" ".join(formatted_fields))

            return " ".join(parts)

        except (json.JSONDecodeError, ValueError):
            return line

    def _parse_plain(self, line: str) -> str:
        """Parse and format plain text log line."""
        # Highlight timestamps
        line = re.sub(
            self.PATTERNS["timestamp"],
            lambda m: self._colorize(m.group(0), "timestamp"),
            line
        )

        # Highlight log levels
        def colorize_level(match):
            level = match.group(1)
            color = self._get_level_color(level)
            return self._colorize(match.group(0), color)

        line = re.sub(self.PATTERNS["level"], colorize_level, line)

        return line

    def _parse_syslog(self, line: str) -> str:
        """Parse and format syslog line."""
        # Remove priority if present
        line = re.sub(self.PATTERNS["syslog_priority"], "", line)
        return self._parse_plain(line)

    def _parse_common_log(self, line: str) -> str:
        """Parse and format common log format (Apache style)."""
        match = re.match(self.PATTERNS["common_log"], line)
        if match:
            ip, timestamp, request, status, size = match.groups()

            # Colorize based on HTTP status code
            status_int = int(status)
            if status_int >= 500:
                status_color = "error"
            elif status_int >= 400:
                status_color = "warn"
            elif status_int >= 300:
                status_color = "info"
            else:
                status_color = "info"

            parts = [
                self._colorize(ip, "field"),
                self._colorize(f"[{timestamp}]", "timestamp"),
                f'"{request}"',
                self._colorize(status, status_color),
                size,
            ]

            return " ".join(parts)

        return line

    def parse(self, line: str) -> str:
        """
        Parse and format a log line.

        Args:
            line: Raw log line

        Returns:
            Formatted log line with colors
        """
        if not line.strip():
            return line

        format_type = self._detect_format(line)

        if format_type == LogFormat.JSON:
            return self._parse_json(line)
        elif format_type == LogFormat.SYSLOG:
            return self._parse_syslog(line)
        elif format_type == LogFormat.COMMON_LOG:
            return self._parse_common_log(line)
        else:
            return self._parse_plain(line)

    def extract_level(self, line: str) -> Optional[str]:
        """
        Extract log level from a line.

        Args:
            line: Log line

        Returns:
            Log level string or None if not found
        """
        # Try JSON first
        if line.strip().startswith('{'):
            try:
                data = json.loads(line.strip())
                for field in ["level", "severity", "loglevel"]:
                    if field in data:
                        return str(data[field]).upper()
            except (json.JSONDecodeError, ValueError):
                pass

        # Try pattern matching
        match = re.search(self.PATTERNS["level"], line)
        if match:
            return match.group(1).upper()

        return None
