"""
Log parsing module with support for multiple formats.
"""

import re
import json
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum


class LogLevel(str, Enum):
    """Log levels."""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"
    UNKNOWN = "UNKNOWN"


@dataclass
class LogEntry:
    """Parsed log entry."""

    line_number: int
    raw: str
    timestamp: Optional[datetime] = None
    level: str = "UNKNOWN"
    message: str = ""
    thread_id: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    service_name: Optional[str] = None
    fields: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure message is set."""
        if not self.message and self.raw:
            self.message = self.raw


class LogParser:
    """Parse log entries from various formats."""

    # Regex patterns
    PATTERNS = {
        "timestamp": re.compile(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
        ),
        "log_level": re.compile(
            r"\b(TRACE|DEBUG|INFO|INFORMATION|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL|CRIT)\b",
            re.IGNORECASE,
        ),
        "thread_id": re.compile(r"(?:thread[=:\s]+|tid[=:\s]+|\[)([a-zA-Z0-9_-]+)(?:\])?"),
        "correlation_id": re.compile(
            r"(?:correlation[_-]?id|request[_-]?id|req[_-]?id)[=:\s]+([a-zA-Z0-9_-]+)"
        ),
        "trace_id": re.compile(r"(?:trace[_-]?id|traceId)[=:\s]+([a-fA-F0-9]{16,32})"),
        "span_id": re.compile(r"(?:span[_-]?id|spanId)[=:\s]+([a-fA-F0-9]{8,16})"),
    }

    def parse_line(self, line_number: int, raw: str) -> LogEntry:
        """Parse a single log line."""
        # Try JSON first
        if raw.strip().startswith("{"):
            try:
                data = json.loads(raw.strip())
                return self._parse_json(line_number, raw, data)
            except (json.JSONDecodeError, ValueError):
                pass

        # Parse as plain text
        return self._parse_plain(line_number, raw)

    def _parse_json(self, line_number: int, raw: str, data: dict) -> LogEntry:
        """Parse JSON log entry."""
        entry = LogEntry(line_number=line_number, raw=raw)

        # Extract timestamp
        for ts_field in ["timestamp", "time", "ts", "@timestamp", "datetime"]:
            if ts_field in data:
                try:
                    ts_str = str(data[ts_field])
                    entry.timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass
                break

        # Extract level
        for level_field in ["level", "severity", "loglevel", "lvl"]:
            if level_field in data:
                entry.level = str(data[level_field]).upper()
                break

        # Extract message
        for msg_field in ["message", "msg", "text", "content"]:
            if msg_field in data:
                entry.message = str(data[msg_field])
                break

        # Extract thread ID
        for thread_field in ["thread", "thread_id", "threadId", "tid"]:
            if thread_field in data:
                entry.thread_id = str(data[thread_field])
                break

        # Extract correlation ID
        for corr_field in ["correlation_id", "correlationId", "request_id", "requestId"]:
            if corr_field in data:
                entry.correlation_id = str(data[corr_field])
                break

        # Extract trace/span IDs
        if "trace_id" in data or "traceId" in data:
            entry.trace_id = str(data.get("trace_id") or data.get("traceId"))
        if "span_id" in data or "spanId" in data:
            entry.span_id = str(data.get("span_id") or data.get("spanId"))

        # Extract service name
        for service_field in ["service", "service_name", "serviceName"]:
            if service_field in data:
                entry.service_name = str(data[service_field])
                break

        # Store other fields
        skip_fields = {
            "timestamp",
            "time",
            "ts",
            "@timestamp",
            "datetime",
            "level",
            "severity",
            "loglevel",
            "lvl",
            "message",
            "msg",
            "text",
            "content",
            "thread",
            "thread_id",
            "threadId",
            "tid",
            "correlation_id",
            "correlationId",
            "request_id",
            "requestId",
            "trace_id",
            "traceId",
            "span_id",
            "spanId",
            "service",
            "service_name",
            "serviceName",
        }
        entry.fields = {k: v for k, v in data.items() if k not in skip_fields}

        return entry

    def _parse_plain(self, line_number: int, raw: str) -> LogEntry:
        """Parse plain text log entry."""
        entry = LogEntry(line_number=line_number, raw=raw, message=raw)

        # Extract timestamp
        ts_match = self.PATTERNS["timestamp"].search(raw)
        if ts_match:
            try:
                ts_str = ts_match.group(0)
                entry.timestamp = datetime.fromisoformat(
                    ts_str.replace(" ", "T").replace("Z", "+00:00")
                )
            except ValueError:
                pass

        # Extract log level
        level_match = self.PATTERNS["log_level"].search(raw)
        if level_match:
            entry.level = level_match.group(1).upper()

        # Extract thread ID
        thread_match = self.PATTERNS["thread_id"].search(raw)
        if thread_match:
            entry.thread_id = thread_match.group(1)

        # Extract correlation ID
        corr_match = self.PATTERNS["correlation_id"].search(raw)
        if corr_match:
            entry.correlation_id = corr_match.group(1)

        # Extract trace ID
        trace_match = self.PATTERNS["trace_id"].search(raw)
        if trace_match:
            entry.trace_id = trace_match.group(1)

        # Extract span ID
        span_match = self.PATTERNS["span_id"].search(raw)
        if span_match:
            entry.span_id = span_match.group(1)

        return entry
