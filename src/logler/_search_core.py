"""
Core search, follow, context, and pattern/metadata functions.

This private module contains the foundational log investigation functions
powered by the Rust backend.  All other investigation submodules import
from here — never the reverse.

Public API surface is re-exported by :mod:`logler.investigate`.
"""

import contextlib
import json
import re
import warnings
from datetime import timedelta
from typing import Any

from ._loading import load_files
from .cache import get_cached_investigator

# ---------------------------------------------------------------------------
# Rust backend initialisation
# ---------------------------------------------------------------------------

# How to build the extension in a source checkout: the one spelling, quoted in every message.
BUILD_HINT = "maturin develop --release -m crates/logler-py/Cargo.toml"

try:
    import logler_rs
    from logler_rs import InvalidPatternError, LineNotFoundError

    RUST_AVAILABLE = True
except ImportError as _exc:
    RUST_AVAILABLE = False

    class LineNotFoundError(ValueError):  # type: ignore[no-redef]
        """Stands in for the extension's error of that name, which cannot be raised here."""

    class InvalidPatternError(ValueError):  # type: ignore[no-redef]
        """Stands in for the extension's error of that name, which cannot be raised here."""

    warnings.warn(
        f"logler's compiled extension (logler_rs) could not be imported: {_exc}. "
        "Search, hierarchy, comparison and sampling need it and will raise "
        f"RuntimeError. Reinstall logler; in a source checkout, build it with `{BUILD_HINT}`.",
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def level_text(level: Any) -> str:
    """The text of an entry's level: upper case, and ``UNKNOWN`` for a line with none.

    The one owner of that spelling: the engine gives ``null`` for a line with no level.
    """
    return str(level or "").strip().upper() or "UNKNOWN"


def _normalize_entry(entry: dict[str, Any]) -> None:
    """Normalize a single log entry in-place (level text, numeric fields)."""
    if "level" in entry:
        entry["level"] = level_text(entry["level"])

    # Convert numeric fields
    for key in ("duration_ms",):
        if key in entry and entry[key] is not None:
            with contextlib.suppress(ValueError, TypeError):
                entry[key] = float(entry[key])


def _normalize_entries(entries: list[dict[str, Any]]) -> None:
    """Batch-normalize entries."""
    for entry in entries:
        _normalize_entry(entry)


def _normalize_search_result_levels(result: dict[str, Any]) -> None:
    """Normalize search result level casing and map aliases."""
    for item in result.get("results", []):
        _normalize_entry(item.get("entry", {}))
        _normalize_entries(item.get("context_before", []))
        _normalize_entries(item.get("context_after", []))


def _normalize_pattern_examples(result: dict[str, Any]) -> None:
    """Normalize examples inside pattern results."""
    for pattern in result.get("patterns", []):
        for example in pattern.get("examples", []):
            _normalize_entry(example)


def _normalize_context_payload(result: dict[str, Any]) -> None:
    """Normalize context payload from Rust (rename keys to match API)."""
    target = result.get("target")
    if target:
        _normalize_entry(target)
    for entry in result.get("context_before", []):
        _normalize_entry(entry)
    for entry in result.get("context_after", []):
        _normalize_entry(entry)


_DURATION = re.compile(r"^(\d+)(s|m|h|d)$")
_DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_duration(text: str) -> timedelta:
    """A relative duration (``30s``, ``2h``, ``1d``; the unit in either case) as a timedelta.

    The one parser of a duration. Raises ``ValueError`` for anything else.
    """
    match = _DURATION.match(text.lower())
    if not match:
        raise ValueError(f"Invalid duration format: {text}. Use format like '30m', '2h', '1d'")
    return timedelta(**{_DURATION_UNITS[match.group(2)]: int(match.group(1))})


def level_name(word: str) -> str:
    """The Rust name (``Warn``) of the level a user-given word names (``warning``, ``ERR``).

    The words are the Rust parser's own table, read through the extension, so a level the
    parser reads can be asked for by the same word. Raises ``ValueError`` for a word that
    names no level.
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")
    name = logler_rs.level_name(word)
    if name is None:
        raise ValueError(f"Unknown log level: {word.strip().lower()}")
    return name


def _parse_levels(level_str: str) -> list[str]:
    """Parse a comma-separated level string into Rust-enum names.

    Example::

        >>> _parse_levels("ERROR,warn,crit")
        ["Error", "Warn", "Fatal"]
    """
    return [level_name(part) for part in level_str.split(",") if part.strip()]


def _build_filters(
    level: str | None = None,
    exclude_level: str | None = None,
    exclude_query: str | None = None,
    thread_id: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    service_name: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
) -> dict[str, Any]:
    """The engine's filter dict for search's keyword arguments (the one builder).

    An id argument is a comma list: one value goes under the singular key, several under
    the plural key.  Raises ``ValueError`` for a level word that names no level.
    """
    filters: dict[str, Any] = {
        "levels": _parse_levels(level) if level else [],
        "exclude_levels": _parse_levels(exclude_level) if exclude_level else [],
    }
    if exclude_query:
        filters["exclude_pattern"] = exclude_query
    for single, plural, value in (
        ("thread_id", "thread_ids", thread_id),
        ("correlation_id", "correlation_ids", correlation_id),
        ("trace_id", "trace_ids", trace_id),
        ("service_name", "service_names", service_name),
    ):
        parts = [p.strip() for p in (value or "").split(",") if p.strip()]
        if len(parts) == 1:
            filters[single] = parts[0]
        elif parts:
            filters[plural] = parts
    if time_start or time_end:
        time_range: dict[str, str] = {}
        if time_start:
            time_range["start"] = time_start
        if time_end:
            time_range["end"] = time_end
        filters["time_range"] = time_range
    return filters


def _investigator_for(
    files: list[str],
    parser_format: str | None = None,
    custom_regex: str | None = None,
) -> Any:
    """The investigator for a call: a freshly loaded one when the caller names a format
    (it never reaches the cache), otherwise the cached one for ``files``."""
    if parser_format or custom_regex:
        investigator = logler_rs.PyInvestigator()
        load_files(investigator, files, parser_format, custom_regex)
        return investigator
    return get_cached_investigator(files)


# ---------------------------------------------------------------------------
# Core search & navigation functions
# ---------------------------------------------------------------------------


def search(
    files: list[str],
    query: str | None = None,
    level: str | None = None,
    exclude_level: str | None = None,
    exclude_query: str | None = None,
    thread_id: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    service_name: str | None = None,
    limit: int | None = None,
    tail: int | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    context_lines: int = 3,
    output_format: str = "full",
    fields: list[str] | None = None,
    parser_format: str | None = None,
    custom_regex: str | None = None,
    count_only: bool = False,
    offset: int = 0,
) -> dict[str, Any]:
    """Search log entries across one or more files.

    Performs full-text search with optional filtering by level, thread,
    correlation ID, trace ID, service name, and time range.  Uses the Rust
    search engine for performance when available.

    Args:
        files: Log file paths to search.  Supports glob patterns.
        query: A regex, matched without regard to letter case against the whole line as
            written in the file (a JSON line: its keys and other fields too) and against
            the message read from it. A pattern that is not a regex raises
            ``InvalidPatternError`` (a ``ValueError``). An empty query is no filter.
        level: Comma-separated log levels to include (e.g. ``"ERROR,WARN"``).
        exclude_level: Comma-separated log levels to exclude.
        exclude_query: A regex of lines to leave out, read as ``query`` is.
        thread_id: Filter by thread ID (comma-separated for multi).
        correlation_id: Filter by correlation ID (comma-separated for multi).
        trace_id: Filter by trace ID (comma-separated for multi).
        service_name: Filter by service name (comma-separated for multi).
        limit: Maximum number of results (the first *N* in time order).
            ``0`` means no cap (bypasses ``DEFAULT_MAX_RESULTS``).
            ``None`` applies the safety cap (10K).
        tail: Return last *N* matches by timestamp.
        time_start: Start of time range (ISO 8601).
        time_end: End of time range (ISO 8601).
        context_lines: Number of context lines before/after each result.
        output_format: ``"full"`` | ``"summary"`` | ``"count"`` | ``"compact"``.
        fields: List of fields to include in output (projection).
        parser_format: Optional log format hint.
        custom_regex: Optional custom parsing regex.
        count_only: If True, skip materialization and return only
            ``total_matches`` with an empty ``results`` list.
            Handled Rust-side — zero JSON serialization overhead.
        offset: Number of sorted results to skip before taking ``limit``.
            Enables server-side pagination (e.g. ``offset=100, limit=100``
            for page 2).  Applied Rust-side before materialization.

    Returns:
        With ``output_format="full"``, a SearchResult dict with shape::

            {
                "results": [
                    {
                        "entry": {...},
                        "context_before": [{...}, ...],
                        "context_after": [{...}, ...],
                        "relevance_score": float
                    },
                    ...
                ],
                "total_matches": int,
                "search_time_ms": int
            }

        With ``fields=[...]`` the shape is ``ProjectedSearchResult``: the same, but each
        ``entry`` holds only the asked keys (the context entries stay whole).

        Every entry, the context entries included, has its level in upper case (``INFO``);
        a line with no level reads ``UNKNOWN``.
        ``"summary"``, ``"count"`` and ``"compact"`` return the shapes of
        ``SearchSummaryResult``, ``SearchCountResult`` and ``SearchCompactResult``
        (``logler.types``).

    Example::

        >>> result = search(["app.log"], query="timeout", level="ERROR,WARN", limit=50)
        >>> print(f"Found {result['total_matches']} matches")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = _investigator_for(files, parser_format, custom_regex)

    filters = _build_filters(
        level=level,
        exclude_level=exclude_level,
        exclude_query=exclude_query,
        thread_id=thread_id,
        correlation_id=correlation_id,
        trace_id=trace_id,
        service_name=service_name,
        time_start=time_start,
        time_end=time_end,
    )

    query_dict: dict[str, Any] = {
        "files": files,
        "query": query,
        "filters": filters,
        "limit": limit,
        "context_lines": context_lines,
    }
    if tail is not None:
        query_dict["tail"] = tail
    if count_only:
        query_dict["count_only"] = True
    if offset > 0:
        query_dict["offset"] = offset
    if output_format in ("summary", "count"):
        # The engine counts every match; the page (``limit``, ``tail``, ``offset``) is only
        # where the summary's samples come from, so it needs no context, and a count none.
        query_dict["context_lines"] = 0
        if output_format == "summary":
            query_dict["aggregate"] = "messages"
        else:
            query_dict["aggregate"] = "counts"
            query_dict["count_only"] = True

    # Call Rust engine
    result_json = investigator.search(json.dumps(query_dict))
    result = json.loads(result_json)
    _normalize_search_result_levels(result)

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
    files: list[str],
    time_start: str | None = None,
    time_end: str | None = None,
) -> dict[str, Any]:
    """Extract all unique IDs (thread, correlation, trace, service) from files.

    Args:
        files: Log file paths to scan.
        time_start: Optional start of time range (ISO 8601).
        time_end: Optional end of time range (ISO 8601).

    Returns:
        ExtractedIds dict with shape::

            {
                "thread_ids": [{"id": str, "count": int, "first_seen": str | None,
                                "last_seen": str | None}, ...],
                "correlation_ids": [{...}, ...],
                "trace_ids": [{...}, ...],
                "services": [{...}, ...],
                "total_entries": int,
                "time_range": {"start": str, "end": str} | None
            }

        Each list holds the most frequent id first; ``time_range`` is ``None`` when no
        entry has a timestamp.

    Example::

        >>> ids = extract_ids(["app.log"])
        >>> print(f"{len(ids['thread_ids'])} threads found")
        >>> print(ids["thread_ids"][0]["id"], ids["thread_ids"][0]["count"])
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = get_cached_investigator(files)

    filters_json = None
    if time_start or time_end:
        filters_json = json.dumps(_build_filters(time_start=time_start, time_end=time_end))

    return json.loads(investigator.extract_ids(filters_json))


def follow_thread(
    files: list[str],
    thread_id: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    parser_format: str | None = None,
    custom_regex: str | None = None,
) -> dict[str, Any]:
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

    investigator = _investigator_for(files, parser_format, custom_regex)
    result_json = investigator.follow_thread(files, thread_id, correlation_id, trace_id)
    result = json.loads(result_json)
    _normalize_entries(result.get("entries", []))
    return result


def get_context(
    file: str,
    line_number: int,
    lines_before: int = 10,
    lines_after: int = 10,
) -> dict[str, Any]:
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
                "context_after": [...],
                "related_threads": [{"thread_id": str, "entries": [...]}, ...]
            }

    Example::

        >>> ctx = get_context("app.log", line_number=42, lines_before=5, lines_after=5)
        >>> print(f"Target: {ctx['target']['message']}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = get_cached_investigator([file])
    result_json = investigator.get_context(file, line_number, lines_before, lines_after, False)
    result = json.loads(result_json)
    _normalize_context_payload(result)
    return result


def find_patterns(
    files: list[str],
    min_occurrences: int = 3,
    parser_format: str | None = None,
    custom_regex: str | None = None,
) -> dict[str, Any]:
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
                    {
                        "pattern_type": "RepeatedError",
                        "pattern": str,
                        "occurrences": int,
                        "first_seen": str,
                        "last_seen": str,
                        "affected_threads": [str, ...],
                        "examples": [{...}, ...]
                    }
                ]
            }

        Nothing else is returned: there is no total or file list.

    Example::

        >>> patterns = find_patterns(["app.log"], min_occurrences=5)
        >>> for p in patterns["patterns"]:
        ...     print(f"{p['occurrences']}x: {p['pattern']}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = _investigator_for(files, parser_format, custom_regex)
    result_json = investigator.find_patterns(files, min_occurrences)
    result = json.loads(result_json)
    _normalize_pattern_examples(result)
    return result


def get_metadata(files: list[str]) -> list[dict[str, Any]]:
    """Get metadata about log files.

    Args:
        files: Log file paths to examine.

    Returns:
        List of file metadata dicts with shape::

            [{
                "path": str, "size_bytes": int, "lines": int, "format": str,
                "time_range": {"start": str, "end": str} | None,
                "available_fields": [str, ...],
                "unique_threads": int, "unique_correlation_ids": int,
                "log_levels": {"INFO": int, ...}
            }]

    Example::

        >>> meta = get_metadata(["app.log"])
        >>> print(f"Total lines: {sum(f['lines'] for f in meta)}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = get_cached_investigator(files)
    result_json = investigator.get_metadata(files)
    return json.loads(result_json)


def get_thread_level_counts(files: list[str]) -> dict[str, dict[str, int]]:
    """Count each thread's entries by level.

    Args:
        files: Log file paths to count.

    Returns:
        A dict mapping every thread id in the files to a dict of its entry count per upper-case
        level name (``UNKNOWN`` for an entry with no level; only levels that occur) and
        ``total``, the thread's number of entries. Several files add up. An entry with no
        thread id is in no thread's counts.

    Example::

        >>> counts = get_thread_level_counts(["app.log"])
        >>> counts["worker-1"]
        {'ERROR': 2, 'INFO': 3, 'total': 5}
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = get_cached_investigator(files)
    return json.loads(investigator.thread_level_counts(files))


# ---------------------------------------------------------------------------
# Token-efficient output formatters
# ---------------------------------------------------------------------------


def _format_as_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Convert search results to the token-efficient summary format.

    Every count is the engine's, over every match of the query (``result["aggregates"]``);
    the samples come from the returned page (``result["results"]``). In ``top_messages``
    two messages of equal count come in the order of their first match.
    """
    total = result["total_matches"]
    if not total:
        return {
            "total_matches": total,
            "unique_messages": 0,
            "log_levels": {},
            "top_messages": [],
            "sample_entries": [],
        }
    counts = result["aggregates"]
    return {
        "total_matches": total,
        "unique_messages": counts["unique_messages"],
        "log_levels": counts["by_level"],
        "by_file": counts["by_file"],
        "top_messages": counts["top_messages"],
        "sample_entries": _select_diverse_samples(result["results"], max_samples=5),
        "full_results_available": True,
    }


def _format_as_count(result: dict[str, Any]) -> dict[str, Any]:
    """Convert search results to the count format (minimal tokens): the engine's counts
    over every match of the query, and no log content."""
    total = result["total_matches"]
    if not total:
        return {"total_matches": total, "by_level": {}, "by_file": {}, "time_range": None}
    counts = result["aggregates"]
    return {
        "total_matches": total,
        "by_level": counts["by_level"],
        "by_file": counts["by_file"],
        "time_range": counts["time_range"],
    }


def _format_as_compact(result: dict[str, Any]) -> dict[str, Any]:
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


def _select_diverse_samples(results: list[dict], max_samples: int = 5) -> list[dict]:
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
