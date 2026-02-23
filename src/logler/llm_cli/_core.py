"""
Shared utilities for the LLM-First CLI.

Exit codes, JSON output helpers, glob expansion, time filters,
and max-bytes truncation used across all command submodules.
"""

import click
import json
import os
import sys
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta


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


def _output_json(data: Dict[str, Any], pretty: bool = False) -> None:
    """Output JSON to stdout."""
    if pretty:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        click.echo(json.dumps(data, default=str))


def _error_json(message: str, code: int = EXIT_USER_ERROR) -> None:
    """Output error as JSON and exit."""
    _output_json({"error": message, "code": code})
    sys.exit(code)


def _parse_duration(duration: str) -> timedelta:
    """Parse duration string like '30m', '2h', '1d' to timedelta."""
    match = re.match(r"^(\d+)(s|m|h|d)$", duration.lower())
    if not match:
        raise ValueError(f"Invalid duration format: {duration}. Use format like '30m', '2h', '1d'")

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "s":
        return timedelta(seconds=value)
    elif unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    else:
        raise ValueError(f"Unknown time unit: {unit}")


def _expand_globs(patterns: List[str]) -> List[str]:
    """Expand glob patterns to file paths."""
    import glob

    files = []
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            files.extend(matches)
        elif Path(pattern).exists():
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
) -> tuple:
    """Resolve time filter options into (time_start, time_end) ISO strings.

    Supports relative time with '-' prefix: --after=-1h --before=-30m
    means "between 1 hour ago and 30 minutes ago".
    """
    from .. import investigate as inv_mod

    if last_duration:
        tr = inv_mod._build_time_range(last=last_duration)
        return (tr.get("start") if tr else None, tr.get("end") if tr else None)

    time_start = None
    time_end = None
    if after:
        time_start = _parse_time_arg(after, "--after")
    if before:
        time_end = _parse_time_arg(before, "--before")
    return (time_start, time_end)


def _parse_time_arg(value: str, flag_name: str) -> str:
    """Parse a time argument, supporting both ISO8601 and relative durations.

    Relative format: -30m, -2h, -1d (dash prefix + duration)
    """
    if value.startswith("-"):
        # Relative time: subtract duration from now
        try:
            delta = _parse_duration(value[1:])
            from datetime import timezone

            return (datetime.now(timezone.utc) - delta).isoformat()
        except ValueError:
            _error_json(
                f"Invalid relative duration for {flag_name}: {value}. "
                f"Use format like '-30m', '-2h', '-1d'"
            )
    else:
        # Absolute ISO8601 timestamp
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            _error_json(f"Invalid timestamp format for {flag_name}: {value}")


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
        type=click.Path(exists=True),
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
