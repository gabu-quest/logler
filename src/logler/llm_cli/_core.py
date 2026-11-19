"""
What every llm command shares: the ``llm`` group, the exit codes, the JSON output and error
helpers, the ``command`` decorator (error handling and ``--pretty``), level-word options,
glob expansion, the time filter options and how they resolve to bounds, and the max-bytes
truncation.
"""

import click
import functools
import json
import os
import sys
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime, timezone

from .._search_core import _parse_levels, level_text, parse_duration
from ..config import FormatFileError
from ..parser import format_time, to_utc


@click.group()
def llm():
    """
    LLM-first CLI commands - optimized for AI agents.

    All commands output structured JSON by default.
    No truncation - full data is always returned.

    Exit codes:
      0 - Success with results
      1 - Success but no results found
      2 - User error (invalid args, file not found)
      3 - Internal error
    """
    pass


# Exit codes
EXIT_SUCCESS = 0  # Success with results
EXIT_NO_RESULTS = 1  # Success but no results found
EXIT_USER_ERROR = 2  # Invalid arguments, file not found
EXIT_INTERNAL_ERROR = 3  # Unexpected exception


def _output_json(data: Dict[str, Any], pretty: bool = False, err: bool = False) -> None:
    """Output JSON to stdout (or to stderr, for a command whose stdout is its data stream)."""
    if pretty:
        click.echo(json.dumps(data, indent=2, default=str), err=err)
    else:
        click.echo(json.dumps(data, default=str), err=err)


def _error_json(message: str, code: int = EXIT_USER_ERROR, err: bool = False) -> None:
    """Output error as JSON and exit."""
    _output_json({"error": message, "code": code}, err=err)
    sys.exit(code)


def command(
    name: Optional[str] = None,
    *,
    group: Optional[click.Group] = None,
    stream: bool = False,
):
    """Declare an llm command: the one owner of what every command shares.

    Registers the function on ``group`` (default ``llm``) under ``name``, gives it the
    ``--pretty`` option (passed to it as ``pretty``) and turns an exception it does not
    handle into the JSON internal error with exit code 3, except a formats.yaml that cannot
    be used (``FormatFileError``) and a file that cannot be opened, read or written (an
    ``OSError`` that names a file), which are the user's to put right (exit code 2, the message
    is the file and the reason).
    ``sys.exit`` passes through.
    ``stream=True`` is for a command whose stdout is a stream of one JSON object per line:
    it has no ``--pretty``, and that error goes to stderr.
    """

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except FormatFileError as e:
                _error_json(f"Unusable format file: {e}", err=stream)
            except OSError as e:
                if e.filename and e.strerror:
                    _error_json(f"{e.filename}: {e.strerror}", err=stream)
                _error_json(f"Internal error: {e}", EXIT_INTERNAL_ERROR, err=stream)
            except Exception as e:
                _error_json(f"Internal error: {e}", EXIT_INTERNAL_ERROR, err=stream)

        if not stream:
            wrapper = click.option("--pretty", is_flag=True, help="Pretty-print JSON output")(
                wrapper
            )
        return (group or llm).command(name)(wrapper)

    return decorate


def _check_level_words(ctx, param, value):
    """Click callback for an option that takes level words: a word that names no level is
    the user's error. ``_parse_levels`` is the one reader of a list of level words."""
    if value:
        try:
            _parse_levels(value)
        except ValueError as e:
            _error_json(str(e))
    return value


def _level_texts(value: Optional[str]) -> Optional[Set[str]]:
    """The texts of an entry's level (``WARN``) that a comma list of level words names."""
    return {level_text(name) for name in _parse_levels(value)} if value else None


def _expand_globs(patterns: List[str]) -> List[str]:
    """The files the patterns name. A folder a pattern matches is not a log file."""
    import glob

    files = []
    for pattern in patterns:
        matches = [m for m in glob.glob(pattern, recursive=True) if Path(m).is_file()]
        if matches:
            files.extend(matches)
        elif Path(pattern).is_file():
            files.append(pattern)
    return sorted(set(files))


def _apply_max_bytes(data: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    """Truncate results list to fit within max_bytes budget."""
    serialized = json.dumps(data, default=str)
    if len(serialized.encode("utf-8")) <= max_bytes:
        return data

    # Binary search for the right number of results to keep
    results_key = None
    for key in (
        "results",
        "entries",
        "timeline",
        "thread_ids",
        "bottlenecks",
        "errors",
        "warnings",
    ):
        if key in data and isinstance(data[key], list):
            results_key = key
            break

    if results_key is None:
        return data

    original_count = len(data[results_key])
    lo, hi = 0, original_count
    best = 0

    while lo <= hi:
        mid = (lo + hi) // 2
        trial = dict(data)
        trial[results_key] = data[results_key][:mid]
        # Include truncation metadata in size estimate (it will be in final output)
        trial["truncated"] = True
        trial["truncated_at"] = mid
        trial["original_count"] = original_count
        trial_size = len(json.dumps(trial, default=str).encode("utf-8"))
        if trial_size <= max_bytes:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    data[results_key] = data[results_key][:best]
    data["truncated"] = True
    data["truncated_at"] = best
    data["original_count"] = original_count
    # Update summary.returned if present so LLMs see consistent counts
    if "summary" in data and isinstance(data["summary"], dict):
        data["summary"]["returned"] = best
    return data


def time_filter_options(f):
    """Add --last, --after, --before to a command."""
    f = click.option(
        "--last", "last_duration", help="Only entries in last N duration (e.g., 30m, 2h)"
    )(f)
    f = click.option(
        "--after", help="Only entries after this time (ISO8601 or relative: -1h, -30m)"
    )(f)
    f = click.option(
        "--before", help="Only entries before this time (ISO8601 or relative: -1h, -30m)"
    )(f)
    return f


def _resolve_time_filters(
    last_duration: Optional[str], after: Optional[str], before: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve time filter options into (time_start, time_end) ISO strings.

    Supports relative time with '-' prefix: --after=-1h --before=-30m
    means "between 1 hour ago and 30 minutes ago".
    """
    if last_duration:
        now = datetime.now(timezone.utc)
        return (format_time(_before(now, last_duration, "--last")), format_time(now))

    time_start = None
    time_end = None
    if after:
        time_start = _parse_time_arg(after, "--after")
    if before:
        time_end = _parse_time_arg(before, "--before")
    return (time_start, time_end)


def _resolve_time_bounds(
    last_duration: Optional[str], after: Optional[str], before: Optional[str]
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """The same bounds as aware datetimes, for a command that compares entry times itself."""
    start, end = _resolve_time_filters(last_duration, after, before)
    return (to_utc(start), to_utc(end))


def _outside_bounds(ts: Optional[datetime], start: Optional[datetime], end: Optional[datetime]):
    """Whether an entry's time lies outside the (inclusive) bounds.

    An entry with no time is inside any bounds, as it is for the search engine: nothing
    says it is too early or too late.
    """
    return ts is not None and ((start is not None and ts < start) or (end is not None and ts > end))


def _time_text_outside_bounds(
    ts: Optional[str], start: Optional[datetime], end: Optional[datetime]
):
    """``_outside_bounds`` for an engine entry, whose time is text."""
    return _outside_bounds(to_utc(ts), start, end)


def _before(now: datetime, duration: str, flag_name: str) -> datetime:
    """``now`` minus a relative duration (``30m``, ``2h``, ``1d``). Text that is no duration,
    or one that reaches back past the calendar's first year, is the user's error."""
    try:
        return now - parse_duration(duration)
    except (ValueError, OverflowError):
        _error_json(
            f"Invalid duration for {flag_name}: {duration}. Use format like '30m', '2h', '1d'"
        )


def _parse_time_arg(value: str, flag_name: str) -> str:
    """Parse a time argument, supporting both ISO8601 and relative durations.

    Relative format: -30m, -2h, -1d (dash prefix + duration)
    """
    if value.startswith("-"):
        return format_time(_before(datetime.now(timezone.utc), value[1:], flag_name))
    else:
        # Absolute ISO8601 timestamp. Without a zone it is UTC, as a log timestamp without
        # one is; every entry's time is zone-aware, so the bound must be too.
        parsed = to_utc(value)
        if parsed is None:
            _error_json(f"Invalid timestamp format for {flag_name}: {value}")
        return format_time(parsed)


def _extract_patterns(values: List[str]) -> List[str]:
    """Extract regex-like patterns from a list of values."""
    if not values:
        return []

    patterns = set()

    # Common patterns
    for val in values[:50]:
        # worker-N pattern
        if re.match(r"^[a-z]+-\d+$", val, re.I):
            patterns.add(r"[a-z]+-\d+")
        # UUID-like
        elif re.match(r"^[a-f0-9-]{36}$", val, re.I):
            patterns.add(r"uuid")
        # req-xxx pattern
        elif re.match(r"^req-[a-z0-9]+$", val, re.I):
            patterns.add(r"req-[a-z0-9]+")
        # trace-xxx pattern
        elif re.match(r"^trace-[a-z0-9]+$", val, re.I):
            patterns.add(r"trace-[a-z0-9]+")
        else:
            # Just add a sample
            if len(patterns) < 5:
                patterns.add(val)

    return sorted(list(patterns))[:10]


def db_source_option(f):
    """Add --db option to a command."""
    return click.option(
        "--db",
        "db_path",
        type=click.Path(exists=True, file_okay=True, dir_okay=False),
        help="sqler database file to use as log source",
    )(f)


@contextmanager
def _db_file_source(files, db_path, default_glob=None):
    """Resolve files + optional --db into a file list with cleanup.

    Args:
        files: File paths or glob patterns from CLI.
        db_path: Optional sqler database path.
        default_glob: If set, use as fallback when neither files nor --db given.
    """
    db_jsonl_path = None
    try:
        if not files and not db_path:
            if default_glob:
                files = [default_glob]
            else:
                _error_json("Either FILES or --db is required", EXIT_USER_ERROR)
        file_list = _expand_globs(list(files)) if files else []
        if db_path:
            from ..db_source import db_to_jsonl

            db_jsonl_path = db_to_jsonl(db_path)
            file_list.insert(0, db_jsonl_path)
        if not file_list:
            _error_json(f"No files found matching: {files}")
        yield file_list
    finally:
        if db_jsonl_path:
            try:
                os.unlink(db_jsonl_path)
            except OSError:
                pass
