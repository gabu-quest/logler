"""
Line parsing for the commands that read files themselves.

There is one parser: the Rust one in ``logler_core``. ``LogParser`` here is a thin adapter
over it, so a line reads the same here as it does in search and the index.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ._search_core import level_text

try:
    import logler_rs
except ImportError:  # the extension is not installed
    logler_rs = None  # type: ignore[assignment]  # the extension is optional at import; None says it is absent


@dataclass
class LogEntry:
    """Parsed log entry."""

    line_number: int
    raw: str
    timestamp: datetime | None = None
    timestamp_text: str | None = None
    level: str = "UNKNOWN"
    message: str = ""
    thread_id: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    service_name: str | None = None
    format: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


def cut_newline(line: str) -> str:
    """A line without its ending: one "\\n" or one "\\r\\n", nothing else (trailing spaces and
    a lone "\\r" stay). The one cut, for every reader that gets lines with their endings."""
    if line.endswith("\n"):
        return line[:-2] if line.endswith("\r\n") else line[:-1]
    return line


def read_lines(path: str) -> Iterator[tuple[int, str]]:
    """A log file's lines, numbered from 1, cut the way the Rust index cuts them: a line ends
    at "\\n" or "\\r\\n", nothing else is trimmed and no line is skipped. So a reader that
    parses line by line gives the line numbers and the text that search gives.

    Bytes that are not UTF-8 are replaced; a UTF-8 byte-order mark at the start of the file is
    not part of line 1.
    """
    with open(path, encoding="utf-8-sig", errors="replace", newline="\n") as f:
        for number, line in enumerate(f, start=1):
            yield number, cut_newline(line)


def is_blank_line(line: str) -> bool:
    """Whether a line is empty or holds only white space, and so is no entry.

    White space is what ``str.strip()`` removes; the Rust index cuts the same way
    (``is_blank_line`` in ``logler-core``). The one rule of every reader that does not go
    through the index.
    """
    return not line.strip()


def read_entry_lines(path: str) -> Iterator[tuple[int, str]]:
    """The lines of a file that are entries: ``read_lines`` without the blank ones. A number is
    still the line's place in the file, so a blank line is skipped and its number not reused."""
    for number, line in read_lines(path):
        if not is_blank_line(line):
            yield number, line


_LEAP_SECOND = re.compile(r"(\d\d:\d\d):60")


def without_leap_second(ts: str) -> str:
    """Rust's RFC 3339 timestamp with a leap second (second 60) read as the last second of
    its minute: neither ``datetime`` nor a SQL ``TIMESTAMP`` can hold second 60. Only the
    seconds are touched: a minute 60 stays, and is no time."""
    return _LEAP_SECOND.sub(r"\1:59", ts, count=1) if ":60" in ts else ts


def to_utc(ts: str | None) -> datetime | None:
    """An ISO 8601 / RFC 3339 time as an aware UTC datetime: the one reader of a time string.

    A time with no zone is UTC, as a log line's is. ``None`` for no text, for text that is
    not a time, and for a time ``datetime`` cannot hold (a year before 1 or after 9999).
    """
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(without_leap_second(ts))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError, TypeError):
        return None


def format_time(ts: datetime) -> str:
    """An entry's time as text, the way the search engine writes it: UTC, a ``Z`` for the
    zone, and the fraction as 3 digits for milliseconds or 6 for microseconds, none for a
    whole second (``2024-01-15T10:00:00Z``, ``...00.123Z``, ``...00.123456Z``).

    The one function that spells an entry's time; ``ts`` is an aware datetime.
    """
    micro = ts.microsecond
    spec = "seconds" if micro == 0 else "milliseconds" if micro % 1000 == 0 else "microseconds"
    return ts.astimezone(UTC).isoformat(timespec=spec).removesuffix("+00:00") + "Z"


class LogParser:
    """Parse single log lines with the Rust parser."""

    def __init__(
        self,
        force_format: str | None = None,
        custom_regex: str | None = None,
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

    def parse_entry(self, line_number: int, raw: str, file: str = "") -> dict[str, Any]:
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
            timestamp=to_utc(ts),
            timestamp_text=ts,
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
