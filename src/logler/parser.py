"""
Line parsing for the commands that read files themselves.

There is one parser: the Rust one in ``logler_core``. ``LogParser`` here is a thin adapter
over it, so a line reads the same here as it does in search and the index.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional, Tuple

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


def read_lines(path: str) -> Iterator[Tuple[int, str]]:
    """A log file's lines, numbered from 1, cut the way the Rust index cuts them: a line ends
    at "\\n" or "\\r\\n", nothing else is trimmed and no line is skipped. So a reader that
    parses line by line gives the line numbers and the text that search gives.

    Bytes that are not UTF-8 are replaced.
    """
    with open(path, encoding="utf-8", errors="replace", newline="\n") as f:
        for number, line in enumerate(f, start=1):
            if line.endswith("\n"):
                line = line[:-2] if line.endswith("\r\n") else line[:-1]
            yield number, line


def without_leap_second(ts: str) -> str:
    """Rust's RFC 3339 timestamp with a leap second (":60") read as the last second of its
    minute: neither ``datetime`` nor a SQL ``TIMESTAMP`` can hold second 60."""
    return ts.replace(":60", ":59", 1) if ":60" in ts else ts


def _to_utc(ts: Optional[str]) -> Optional[datetime]:
    """Rust's RFC 3339 timestamp as an aware UTC datetime.

    ``None`` for a time ``datetime`` cannot hold: a year before 1 or after 9999.
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(without_leap_second(ts)).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def format_time(ts: datetime) -> str:
    """An entry's time as text, the way the search engine writes it: UTC, a ``Z`` for the
    zone, and the fraction as 3 digits for milliseconds or 6 for microseconds, none for a
    whole second (``2024-01-15T10:00:00Z``, ``...00.123Z``, ``...00.123456Z``).

    The one function that spells an entry's time; ``ts`` is an aware datetime.
    """
    micro = ts.microsecond
    spec = "seconds" if micro == 0 else "milliseconds" if micro % 1000 == 0 else "microseconds"
    return ts.astimezone(timezone.utc).isoformat(timespec=spec).removesuffix("+00:00") + "Z"


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

    def parse_entry(self, line_number: int, raw: str, file: str = "") -> Dict[str, Any]:
        """One line as the dict the Rust index gives for an entry (``timestamp`` as RFC 3339
        text, ``level`` as the engine gives it, ``fields``), with the caller's file, line
        number and raw text. The one reading of a line: ``parse_line`` builds from it."""
        # Rust counts lines as unsigned; the entry keeps the number the caller gave.
        data = json.loads(self._parser.parse_line(max(line_number, 0), raw))
        data.update(file=file, line_number=line_number, raw=raw)
        return data

    def parse_line(self, line_number: int, raw: str) -> LogEntry:
        """Parse a single log line."""
        data = self.parse_entry(line_number, raw)
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
