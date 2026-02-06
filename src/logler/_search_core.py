"""
Core search, follow, context, and pattern/metadata functions.

This private module contains the foundational log investigation functions
powered by the Rust backend.  All other investigation submodules import
from here — never the reverse.

Public API surface is re-exported by :mod:`logler.investigate`.
"""

import json
import warnings
from typing import List, Optional, Dict, Any
from datetime import datetime
from collections import defaultdict

from .safe_regex import try_compile

# ---------------------------------------------------------------------------
# Rust backend initialisation
# ---------------------------------------------------------------------------

try:
    import logler_rs

    RUST_AVAILABLE = True
except ImportError:
    try:
        from .bootstrap import ensure_rust_backend

        if ensure_rust_backend():
            import logler_rs  # type: ignore

            RUST_AVAILABLE = True
        else:
            RUST_AVAILABLE = False
            warnings.warn("Rust backend not available. Using Python fallback.", stacklevel=2)
    except (ImportError, AttributeError, OSError):
        RUST_AVAILABLE = False
        warnings.warn("Rust backend not available. Using Python fallback.", stacklevel=2)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalize_entry(entry: Dict[str, Any]) -> None:
    """Normalize a single log entry in-place (uppercase level, detect format)."""
    if "level" in entry:
        raw_level = str(entry["level"]).upper().strip()
        entry["level"] = _LEVEL_MAP.get(raw_level, raw_level)

    # Infer syslog level if missing
    if not entry.get("level") and entry.get("fields", {}).get("priority"):
        inferred = _infer_syslog_level(entry["fields"]["priority"])
        if inferred:
            entry["level"] = inferred

    # Convert numeric fields
    for key in ("duration_ms",):
        if key in entry and entry[key] is not None:
            try:
                entry[key] = float(entry[key])
            except (ValueError, TypeError):
                pass


def _normalize_entries(entries: List[Dict[str, Any]]) -> None:
    """Batch-normalize entries."""
    for entry in entries:
        _normalize_entry(entry)


def _normalize_search_result_levels(result: Dict[str, Any]) -> None:
    """Normalize search result level casing and map aliases."""
    for item in result.get("results", []):
        entry = item.get("entry", {})
        _normalize_entry(entry)
    for item in result.get("context_before", []):
        _normalize_entry(item)
    for item in result.get("context_after", []):
        _normalize_entry(item)


def _apply_custom_regex_to_results(result: Dict[str, Any], custom_regex: Optional[str]) -> None:
    """Apply custom regex to fill missing fields in search results."""
    if not custom_regex:
        return
    compiled = try_compile(custom_regex)
    if not compiled:
        return
    for item in result.get("results", []):
        _apply_custom_regex_to_entry(item.get("entry", {}), compiled)
    # Also apply to pattern examples if present
    for pattern in result.get("patterns", []):
        for example in pattern.get("examples", []):
            _apply_custom_regex_to_entry(example, compiled)


def _apply_custom_regex_to_entry(entry: Dict[str, Any], compiled_regex) -> None:
    """Apply a compiled regex to a single entry to fill missing fields."""
    message = entry.get("raw_line") or entry.get("message") or ""
    if not message:
        return
    match = compiled_regex.search(message)
    if not match:
        return
    groups = match.groupdict()
    for key, value in groups.items():
        if value is not None:
            # Only fill if the entry field is missing or empty
            if key == "level":
                if not entry.get("level"):
                    entry["level"] = value.upper()
            elif key == "timestamp":
                if not entry.get("timestamp"):
                    entry["timestamp"] = value
            elif key == "thread_id":
                if not entry.get("thread_id"):
                    entry["thread_id"] = value
            elif key == "correlation_id":
                if not entry.get("correlation_id"):
                    entry["correlation_id"] = value
            elif key == "trace_id":
                if not entry.get("trace_id"):
                    entry["trace_id"] = value
            elif key == "service_name":
                if not entry.get("service_name"):
                    entry["service_name"] = value
            elif key == "message":
                if not entry.get("message") or entry["message"] == message:
                    entry["message"] = value
            else:
                # Put in fields dict
                fields = entry.setdefault("fields", {})
                if key not in fields:
                    fields[key] = value
    # Re-normalize after regex application
    _normalize_entry(entry)


def _normalize_pattern_examples(result: Dict[str, Any]) -> None:
    """Normalize examples inside pattern results."""
    for pattern in result.get("patterns", []):
        for example in pattern.get("examples", []):
            _normalize_entry(example)


def _infer_syslog_level(priority) -> Optional[str]:
    """Infer syslog level from a priority field value."""
    try:
        pri = int(priority)
        severity = pri & 0x07
        severity_map = {
            0: "FATAL",
            1: "FATAL",
            2: "FATAL",
            3: "ERROR",
            4: "WARN",
            5: "INFO",
            6: "INFO",
            7: "DEBUG",
        }
        return severity_map.get(severity)
    except (ValueError, TypeError):
        return None


def _parse_timestamp_flex(value: str) -> Optional[str]:
    """Parse a timestamp string in common formats, return ISO-8601 or None."""
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _normalize_context_payload(result: Dict[str, Any]) -> None:
    """Normalize context payload from Rust (rename keys to match API)."""
    target = result.get("target")
    if target:
        _normalize_entry(target)
    for entry in result.get("context_before", []):
        _normalize_entry(entry)
    for entry in result.get("context_after", []):
        _normalize_entry(entry)


def _build_time_range(
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    duration: Optional[str] = None,
) -> Dict[str, str]:
    """Build a time_range dict from CLI-style arguments.

    Supports ISO timestamps for start/end, and duration strings like ``30m``,
    ``2h``, ``1d`` relative to now or to a given start/end.
    """
    result: Dict[str, str] = {}

    if time_start:
        parsed = _parse_timestamp_flex(time_start)
        if parsed:
            result["start"] = parsed
        else:
            result["start"] = time_start  # Pass through, let Rust parse

    if time_end:
        parsed = _parse_timestamp_flex(time_end)
        if parsed:
            result["end"] = parsed
        else:
            result["end"] = time_end

    if duration and not (time_start and time_end):
        import re as _re
        from datetime import timedelta

        m = _re.match(r"^(\d+)(s|m|h|d)$", duration.lower())
        if m:
            value = int(m.group(1))
            unit = m.group(2)
            delta = {
                "s": timedelta(seconds=value),
                "m": timedelta(minutes=value),
                "h": timedelta(hours=value),
                "d": timedelta(days=value),
            }[unit]

            now = datetime.utcnow()
            if time_start and not time_end:
                result["end"] = (now).isoformat() + "Z"
            elif not time_start:
                result["start"] = (now - delta).isoformat() + "Z"
                if not time_end:
                    result["end"] = now.isoformat() + "Z"

    return result


# Level normalisation map — values must be Rust enum variant names (title case).
_LEVEL_MAP = {
    "trace": "Trace",
    "debug": "Debug",
    "info": "Info",
    "warn": "Warn",
    "warning": "Warn",
    "error": "Error",
    "fatal": "Fatal",
    "critical": "Fatal",
}


def _parse_levels(level_str: str) -> List[str]:
    """Parse a comma-separated level string into Rust-enum names.

    Example::

        >>> _parse_levels("ERROR,warn,info")
        ["Error", "Warn", "Info"]
    """
    result = []
    for part in level_str.split(","):
        part = part.strip().lower()
        if not part:
            continue
        mapped = _LEVEL_MAP.get(part)
        if not mapped:
            raise ValueError(f"Unknown log level: {part}")
        result.append(mapped)
    return result


# ---------------------------------------------------------------------------
# Core search & navigation functions
# ---------------------------------------------------------------------------


def search(
    files: List[str],
    query: Optional[str] = None,
    level: Optional[str] = None,
    exclude_level: Optional[str] = None,
    exclude_query: Optional[str] = None,
    thread_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    service_name: Optional[str] = None,
    limit: Optional[int] = None,
    tail: Optional[int] = None,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    context_lines: int = 3,
    output_format: str = "full",
    fields: Optional[List[str]] = None,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> Dict[str, Any]:
    """Search log entries across one or more files.

    Performs full-text search with optional filtering by level, thread,
    correlation ID, trace ID, service name, and time range.  Uses the Rust
    search engine for performance when available.

    Args:
        files: Log file paths to search.  Supports glob patterns.
        query: Regex pattern to match against log messages.
        level: Comma-separated log levels to include (e.g. ``"ERROR,WARN"``).
        exclude_level: Comma-separated log levels to exclude.
        exclude_query: Regex pattern to exclude matching entries.
        thread_id: Filter by thread ID (comma-separated for multi).
        correlation_id: Filter by correlation ID (comma-separated for multi).
        trace_id: Filter by trace ID (comma-separated for multi).
        service_name: Filter by service name (comma-separated for multi).
        limit: Maximum number of results (first *N* by relevance).
        tail: Return last *N* matches by timestamp.
        time_start: Start of time range (ISO 8601).
        time_end: End of time range (ISO 8601).
        context_lines: Number of context lines before/after each result.
        output_format: ``"full"`` | ``"summary"`` | ``"count"`` | ``"compact"``.
        fields: List of fields to include in output (projection).
        parser_format: Optional log format hint.
        custom_regex: Optional custom parsing regex.

    Returns:
        SearchResult dict with shape::

            {
                "total_matches": int,
                "results": [{"entry": {...}, ...}, ...],
                "query": str | None,
                "files": [str, ...],
                "filters": {"level": str | None, ...},
                "metadata": {"level_counts": {...}, "files_searched": int, ...}
            }

    Example::

        >>> result = search(["app.log"], query="timeout", level="ERROR,WARN", limit=50)
        >>> print(f"Found {result['total_matches']} matches")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = logler_rs.PyInvestigator()
    _load_files_with_config(investigator, files, parser_format, custom_regex)

    # Build filters
    filters: Dict[str, Any] = {"levels": [], "exclude_levels": []}
    if level:
        filters["levels"] = _parse_levels(level)
    if exclude_level:
        filters["exclude_levels"] = _parse_levels(exclude_level)
    if exclude_query:
        filters["exclude_pattern"] = exclude_query

    # ID filters — comma-separated → multi-value
    if thread_id:
        parts = [p.strip() for p in thread_id.split(",") if p.strip()]
        if len(parts) == 1:
            filters["thread_id"] = parts[0]
        else:
            filters["thread_ids"] = parts
    if correlation_id:
        parts = [p.strip() for p in correlation_id.split(",") if p.strip()]
        if len(parts) == 1:
            filters["correlation_id"] = parts[0]
        else:
            filters["correlation_ids"] = parts
    if trace_id:
        parts = [p.strip() for p in trace_id.split(",") if p.strip()]
        if len(parts) == 1:
            filters["trace_id"] = parts[0]
        else:
            filters["trace_ids"] = parts
    if service_name:
        parts = [p.strip() for p in service_name.split(",") if p.strip()]
        if len(parts) == 1:
            filters["service_name"] = parts[0]
        else:
            filters["service_names"] = parts

    # Time range — push to Rust
    if time_start or time_end:
        tr: Dict[str, str] = {}
        if time_start:
            tr["start"] = time_start
        if time_end:
            tr["end"] = time_end
        filters["time_range"] = tr

    query_dict: Dict[str, Any] = {
        "files": files,
        "query": query,
        "filters": filters,
        "limit": limit,
        "context_lines": context_lines,
    }
    if tail is not None:
        query_dict["tail"] = tail

    # Call Rust engine
    result_json = investigator.search(json.dumps(query_dict))
    result = json.loads(result_json)
    _normalize_search_result_levels(result)
    _apply_custom_regex_to_results(result, custom_regex)

    # Field projection
    if fields and output_format == "full":
        field_set = set(fields)
        for item in result.get("results", []):
            entry = item.get("entry", {})
            keys_to_remove = [k for k in entry if k not in field_set]
            for k in keys_to_remove:
                del entry[k]

    # Transform based on output_format
    if output_format == "full":
        return result
    elif output_format == "summary":
        return _format_as_summary(result)
    elif output_format == "count":
        return _format_as_count(result)
    elif output_format == "compact":
        return _format_as_compact(result)
    else:
        return result


def extract_ids(
    files: List[str],
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract all unique IDs (thread, correlation, trace, service) from files.

    Args:
        files: Log file paths to scan.
        time_start: Optional start of time range (ISO 8601).
        time_end: Optional end of time range (ISO 8601).

    Returns:
        ExtractedIds dict with shape::

            {
                "thread_ids": [str, ...],
                "correlation_ids": [str, ...],
                "trace_ids": [str, ...],
                "services": [str, ...],
                "total_entries": int
            }

    Example::

        >>> ids = extract_ids(["app.log"])
        >>> print(f"{len(ids['thread_ids'])} threads found")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = logler_rs.PyInvestigator()
    investigator.load_files(files)

    filters_json = None
    if time_start or time_end:
        f: Dict[str, Any] = {}
        tr: Dict[str, str] = {}
        if time_start:
            tr["start"] = time_start
        if time_end:
            tr["end"] = time_end
        f["time_range"] = tr
        filters_json = json.dumps(f)

    return json.loads(investigator.extract_ids(filters_json))


def follow_thread(
    files: List[str],
    thread_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> Dict[str, Any]:
    """Follow a thread/correlation/trace through log files.

    Args:
        files: Log file paths to search.
        thread_id: Thread ID to follow.
        correlation_id: Correlation ID to follow.
        trace_id: Trace ID to follow.
        parser_format: Optional log format hint.
        custom_regex: Optional custom parsing regex.

    Returns:
        FollowThreadResult dict with shape::

            {
                "entries": [...],
                "total_entries": int,
                "duration_ms": int | None,
                "unique_spans": [str, ...]
            }

    Example::

        >>> result = follow_thread(["app.log"], thread_id="worker-1")
        >>> for entry in result["entries"]:
        ...     print(f"  {entry['timestamp']}: {entry['message']}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Lazy import to avoid circular dependency
    from .investigate import Investigator

    # Use Investigator when custom parsing is requested so parsing honors the config.
    if parser_format or custom_regex:
        inv = Investigator()
        inv.load_files(files, parser_format=parser_format, custom_regex=custom_regex)
        return inv.follow_thread(
            thread_id=thread_id, correlation_id=correlation_id, trace_id=trace_id
        )

    result_json = logler_rs.follow_thread(files, thread_id, correlation_id, trace_id)
    result = json.loads(result_json)
    _normalize_entries(result.get("entries", []))
    return result


def get_context(
    file: str,
    line_number: int,
    lines_before: int = 10,
    lines_after: int = 10,
) -> Dict[str, Any]:
    """Get context around a specific log line.

    Args:
        file: Log file path.
        line_number: Line number to get context for.
        lines_before: Number of lines before.
        lines_after: Number of lines after.

    Returns:
        ContextResult dict with shape::

            {
                "target": {...},
                "context_before": [...],
                "context_after": [...]
            }

    Example::

        >>> ctx = get_context("app.log", line_number=42, lines_before=5, lines_after=5)
        >>> print(f"Target: {ctx['target']['message']}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Use Investigator class for more complex operations
    investigator = logler_rs.PyInvestigator()
    investigator.load_files([file])
    result_json = investigator.get_context(file, line_number, lines_before, lines_after, False)
    result = json.loads(result_json)
    _normalize_context_payload(result)
    return result


def find_patterns(
    files: List[str],
    min_occurrences: int = 3,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> Dict[str, Any]:
    """Find repeated patterns and anomalies in logs.

    Args:
        files: Log file paths to analyse.
        min_occurrences: Minimum occurrences to consider a pattern.
        parser_format: Optional log format hint.
        custom_regex: Optional custom parsing regex.

    Returns:
        PatternResult dict with shape::

            {
                "patterns": [
                    {"pattern": str, "occurrences": int, "first_seen": str, ...}
                ]
            }

    Example::

        >>> patterns = find_patterns(["app.log"], min_occurrences=5)
        >>> for p in patterns["patterns"]:
        ...     print(f"{p['occurrences']}x: {p['pattern']}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Lazy import to avoid circular dependency
    from .investigate import Investigator

    if parser_format or custom_regex:
        inv = Investigator()
        inv.load_files(files, parser_format=parser_format, custom_regex=custom_regex)
        return inv.find_patterns(min_occurrences=min_occurrences)

    result_json = logler_rs.find_patterns(files, min_occurrences)
    result = json.loads(result_json)
    _normalize_pattern_examples(result)
    _apply_custom_regex_to_results(result, custom_regex)
    return result


def get_metadata(files: List[str]) -> Dict[str, Any]:
    """Get metadata about log files.

    Args:
        files: Log file paths to examine.

    Returns:
        List of file metadata dicts with shape::

            [{"path": str, "size_bytes": int, "lines": int, "format": str, ...}]

    Example::

        >>> meta = get_metadata(["app.log"])
        >>> print(f"Total lines: {sum(f['lines'] for f in meta)}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    result_json = logler_rs.get_metadata(files)
    return json.loads(result_json)


# ---------------------------------------------------------------------------
# Token-efficient output formatters
# ---------------------------------------------------------------------------


def _format_as_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert full search results to token-efficient summary format.

    Instead of returning all log entries, groups them by message and
    provides aggregated statistics with a few examples.
    """
    results = result.get("results", [])
    if not results:
        return {
            "total_matches": 0,
            "unique_messages": 0,
            "log_levels": {},
            "top_messages": [],
            "sample_entries": [],
        }

    # Group by message
    message_groups = defaultdict(
        lambda: {
            "count": 0,
            "first_seen": None,
            "last_seen": None,
            "levels": defaultdict(int),
            "examples": [],
        }
    )

    level_counts = defaultdict(int)
    file_counts = defaultdict(int)

    for item in results:
        entry = item.get("entry", {})
        message = entry.get("message", "").strip()
        level = entry.get("level", "INFO")
        timestamp = entry.get("timestamp")
        file_path = entry.get("file", "")

        # Update level counts
        level_counts[level] += 1
        file_counts[file_path] += 1

        # Update message group
        group = message_groups[message]
        group["count"] += 1
        group["levels"][level] += 1

        if group["first_seen"] is None or (timestamp and timestamp < group["first_seen"]):
            group["first_seen"] = timestamp

        if group["last_seen"] is None or (timestamp and timestamp > group["last_seen"]):
            group["last_seen"] = timestamp

        # Keep up to 2 examples per message
        if len(group["examples"]) < 2:
            group["examples"].append(
                {
                    "file": file_path,
                    "line": entry.get("line_number"),
                    "timestamp": timestamp,
                    "level": level,
                }
            )

    # Convert to sorted list (most frequent first)
    top_messages = []
    for message, data in sorted(message_groups.items(), key=lambda x: x[1]["count"], reverse=True)[
        :20
    ]:
        top_messages.append(
            {
                "message": message[:200],  # Truncate long messages
                "count": data["count"],
                "first_seen": data["first_seen"],
                "last_seen": data["last_seen"],
                "levels": dict(data["levels"]),
                "examples": data["examples"],
            }
        )

    # Sample entries (diverse selection)
    sample_entries = _select_diverse_samples(results, max_samples=5)

    return {
        "total_matches": len(results),
        "unique_messages": len(message_groups),
        "log_levels": dict(level_counts),
        "by_file": dict(file_counts),
        "top_messages": top_messages,
        "sample_entries": sample_entries,
        "full_results_available": True,
    }


def _format_as_count(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert full search results to count-only format (minimal tokens).

    Returns only statistics, no actual log content.
    """
    results = result.get("results", [])
    if not results:
        return {"total_matches": 0, "by_level": {}, "by_file": {}, "time_range": None}

    level_counts = defaultdict(int)
    file_counts = defaultdict(int)
    timestamps = []

    for item in results:
        entry = item.get("entry", {})
        level = entry.get("level", "INFO")
        file_path = entry.get("file", "")
        timestamp = entry.get("timestamp")

        level_counts[level] += 1
        file_counts[file_path] += 1

        if timestamp:
            timestamps.append(timestamp)

    # Time range
    time_range = None
    if timestamps:
        timestamps.sort()
        time_range = {"start": timestamps[0], "end": timestamps[-1]}

    return {
        "total_matches": len(results),
        "by_level": dict(level_counts),
        "by_file": dict(file_counts),
        "time_range": time_range,
    }


def _format_as_compact(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert full search results to compact format.

    Returns only essential fields, removing raw logs and extra context.
    """
    results = result.get("results", [])
    if not results:
        return {"matches": [], "total": 0}

    compact_matches = []
    for item in results:
        entry = item.get("entry", {})
        compact_matches.append(
            {
                "time": entry.get("timestamp"),
                "level": entry.get("level"),
                "msg": entry.get("message", "")[:150],  # Truncate messages
                "thread": entry.get("thread_id") or entry.get("correlation_id"),
                "file": entry.get("file", "").split("/")[-1],  # Just filename
                "line": entry.get("line_number"),
            }
        )

    return {"matches": compact_matches, "total": len(results)}


def _select_diverse_samples(results: List[Dict], max_samples: int = 5) -> List[Dict]:
    """Select a diverse set of sample entries.

    Tries to include:
    - First and last entry
    - Different log levels
    - Different files
    - Errors if present
    """
    if not results:
        return []

    if len(results) <= max_samples:
        return [r.get("entry", {}) for r in results]

    samples = []
    indices_used = set()

    # Always include first and last
    samples.append(results[0].get("entry", {}))
    indices_used.add(0)

    if len(results) > 1:
        samples.append(results[-1].get("entry", {}))
        indices_used.add(len(results) - 1)

    # Find first error
    for i, item in enumerate(results):
        if i in indices_used:
            continue
        entry = item.get("entry", {})
        if entry.get("level") in ["ERROR", "FATAL"]:
            samples.append(entry)
            indices_used.add(i)
            break

    # Fill remaining slots with evenly spaced entries
    remaining = max_samples - len(samples)
    if remaining > 0 and len(results) > len(indices_used):
        step = len(results) // (remaining + 1)
        for i in range(1, remaining + 1):
            idx = min(i * step, len(results) - 1)
            if idx not in indices_used:
                samples.append(results[idx].get("entry", {}))
                indices_used.add(idx)

    return samples[:max_samples]


# ---------------------------------------------------------------------------
# File loading with config
# ---------------------------------------------------------------------------


def _load_files_with_config(
    inv: Any,
    files: List[str],
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
):
    """Load files with optional parser config; falls back to plain load if config not supported.

    When no explicit parser_format or custom_regex is given, auto-discovers
    .logler/formats.yaml and matches file patterns to select the right format.
    """
    # Auto-discover config when no explicit format is given
    if not parser_format and not custom_regex and files:
        custom_regex = _auto_detect_format_from_config(files)

    try:
        if parser_format or custom_regex:
            return inv.load_files_with_config(files, parser_format, custom_regex)
    except Exception:
        # Fall back silently to default loader if enhanced path fails
        pass
    return inv.load_files(files)


def _auto_detect_format_from_config(files: List[str]) -> Optional[str]:
    """Try to find a matching format in .logler/formats.yaml for the given files.

    Searches from the directory of the first file. If a config is found and
    any file matches a format's file_patterns, returns that format's regex.
    Only returns a regex if ALL files match the SAME format (or have no match).
    """
    try:
        from pathlib import Path as _Path

        from .config import find_config, get_format_for_file, load_config

        if not files:
            return None

        # Search from the directory of the first file
        start_dir = _Path(files[0]).resolve().parent
        config_path = find_config(start_dir)
        if not config_path:
            return None

        config = load_config(config_path)
        if not config.formats:
            return None

        # Find format for the first file that has a match
        matched_regex = None
        for f in files:
            fmt = get_format_for_file(config, f)
            if fmt:
                if matched_regex is None:
                    matched_regex = fmt.regex
                elif matched_regex != fmt.regex:
                    # Multiple files match different formats — don't auto-select
                    return None

        return matched_regex
    except Exception:
        # Config loading should never break file loading
        return None
