"""
Line parsing for the commands that read files themselves.

There is one parser: the Rust one in ``logler_core``. ``LogParser`` here is a thin adapter
over it, so a line reads the same here as it does in search and the index.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ._search_core import level_text

try:
    import logler_rs
except ImportError:  # the extension is not installed
    logler_rs = None  # type: ignore[assignment]


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
    parent_span_id: Optional[str] = None
    service_name: Optional[str] = None
    format: Optional[str] = None
    fields: Dict[str, Any] = field(default_factory=dict)


def _to_utc(ts: Optional[str]) -> Optional[datetime]:
    """Rust's RFC 3339 timestamp as an aware UTC datetime.

    ``None`` for a time ``datetime`` cannot hold: a year before 1 or after 9999.
    """
    if not ts:
        return None
    # A leap second (":60") has no datetime; read it as the last second of the minute.
    for text in (ts, ts.replace(":60", ":59", 1)):
        try:
            return datetime.fromisoformat(text).astimezone(timezone.utc)
        except (ValueError, OverflowError):
            continue
    return None


class LogParser:
    """Parse single log lines with the Rust parser."""

    def __init__(
        self,
        force_format: Optional[str] = None,
        custom_regex: Optional[str] = None,
    ):
        if logler_rs is None:
            raise RuntimeError("Rust backend not available")
        self._parser = logler_rs.PyLineParser(force_format=force_format, custom_regex=custom_regex)

    @classmethod
    def for_file(cls, path: str) -> "LogParser":
        """The parser for one file: its format from ``.logler/formats.yaml`` when one
        names the file (``config.format_for_file``), else the built-in detection."""
        from .config import format_for_file

        fmt = format_for_file(path)
        return cls(custom_regex=fmt.regex) if fmt is not None else cls()

    def parse_line(self, line_number: int, raw: str) -> LogEntry:
        """Parse a single log line."""
        # Rust counts lines as unsigned; the entry keeps the number the caller gave.
        data = json.loads(self._parser.parse_line(max(line_number, 0), raw))
        ts = data.get("timestamp")
        return LogEntry(
            line_number=line_number,
            raw=raw,
            timestamp=_to_utc(ts),
            level=level_text(data.get("level")),
            message=data["message"],
            thread_id=data.get("thread_id"),
            correlation_id=data.get("correlation_id"),
            trace_id=data.get("trace_id"),
            span_id=data.get("span_id"),
            parent_span_id=data.get("parent_span_id"),
            service_name=data.get("service_name"),
            format=data["format"],
            fields=data.get("fields") or {},
        )
