"""
Thread comparison, time-period comparison, and cross-service timeline.

Public API surface is re-exported by :mod:`logler.investigate`.
"""

import warnings
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from collections import defaultdict

from ._search_core import search, follow_thread


# ---------------------------------------------------------------------------
# Cross-service timeline
# ---------------------------------------------------------------------------


def cross_service_timeline(
    files: Dict[str, List[str]],
    time_window: Optional[Tuple[str, str]] = None,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: Optional[int] = None,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a unified timeline across multiple services/log files.

    Perfect for investigating distributed systems where a single request
    flows through multiple services (API Gateway -> Auth -> Database -> Cache).

    Args:
        files: Dict mapping service names to log file lists, e.g.
            ``{"api": ["api.log"], "db": ["db.log"]}``.
        time_window: Optional ``(start_time, end_time)`` tuple in ISO format.
        correlation_id: Filter to specific correlation ID.
        trace_id: Filter to specific trace ID.
        limit: Maximum number of entries to return.
        parser_format: Optional log format hint.
        custom_regex: Optional custom parsing regex.

    Returns:
        CrossServiceTimelineResult dict with shape::

            {
                "timeline": [{"service": str, "timestamp": str, "entry": {...}, "relative_time_ms": int}],
                "services": [str, ...],
                "total_entries": int,
                "duration_ms": int | None,
                "service_breakdown": {"api": int, "db": int}
            }

    Example::

        >>> tl = cross_service_timeline(
        ...     files={"api": ["api.log"], "db": ["db.log"]},
        ...     correlation_id="req-12345",
        ... )
        >>> for e in tl["timeline"]:
        ...     print(f"[{e['service']:10s}] +{e['relative_time_ms']:4d}ms: {e['entry']['message']}")
    """
    from ._search_core import RUST_AVAILABLE

    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Collect entries from all services
    all_entries = []
    service_counts = defaultdict(int)

    for service_name_key, service_files in files.items():
        if correlation_id:
            result = follow_thread(service_files, correlation_id=correlation_id)
            entries = result.get("entries", [])
        elif trace_id:
            result = follow_thread(service_files, trace_id=trace_id)
            entries = result.get("entries", [])
        else:
            # Get all entries (limit=0 bypasses DEFAULT_MAX_RESULTS)
            result = search(
                service_files, limit=0, parser_format=parser_format, custom_regex=custom_regex
            )
            entries = [r["entry"] for r in result.get("results", [])]

        # Accumulate entries with raw timestamp strings (defer parsing)
        for entry in entries:
            all_entries.append(
                {
                    "service": service_name_key,
                    "timestamp_str": entry.get("timestamp"),
                    "entry": entry,
                }
            )
            service_counts[service_name_key] += 1

    # Filter by time window if specified (parse timestamps only for filtering)
    if time_window:
        start_time, end_time = time_window
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            filtered = []
            for e in all_entries:
                ts_str = e["timestamp_str"]
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
                if start_dt <= ts <= end_dt:
                    filtered.append(e)
            all_entries = filtered
        except Exception as e:
            warnings.warn(f"Could not parse time window: {e}", stacklevel=2)

    # Sort by timestamp string (ISO 8601 sorts correctly lexicographically)
    all_entries.sort(key=lambda e: e["timestamp_str"] or "")

    # Apply limit before expensive datetime parsing
    if limit:
        all_entries = all_entries[:limit]

    # Parse timestamps only for the final entries (after limit)
    for e in all_entries:
        ts_str = e["timestamp_str"]
        if ts_str:
            try:
                e["timestamp"] = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                e["timestamp"] = None
        else:
            e["timestamp"] = None

    # Calculate relative times
    if all_entries and all_entries[0]["timestamp"]:
        start_time_dt = all_entries[0]["timestamp"]
        for entry in all_entries:
            if entry["timestamp"]:
                delta = entry["timestamp"] - start_time_dt
                entry["relative_time_ms"] = int(delta.total_seconds() * 1000)
            else:
                entry["relative_time_ms"] = None
    else:
        for entry in all_entries:
            entry["relative_time_ms"] = None

    # Calculate duration
    duration_ms = None
    if len(all_entries) >= 2 and all_entries[0]["timestamp"] and all_entries[-1]["timestamp"]:
        duration = all_entries[-1]["timestamp"] - all_entries[0]["timestamp"]
        duration_ms = int(duration.total_seconds() * 1000)

    # Clean up entries for output (remove internal timestamp objects)
    timeline = []
    for e in all_entries:
        timeline.append(
            {
                "service": e["service"],
                "timestamp": e["timestamp_str"],
                "entry": e["entry"],
                "relative_time_ms": e["relative_time_ms"],
            }
        )

    return {
        "timeline": timeline,
        "services": list(files.keys()),
        "total_entries": len(timeline),
        "duration_ms": duration_ms,
        "service_breakdown": dict(service_counts),
    }


# ---------------------------------------------------------------------------
# Thread comparison
# ---------------------------------------------------------------------------


def compare_threads(
    files: List[str],
    thread_a: Optional[str] = None,
    thread_b: Optional[str] = None,
    correlation_a: Optional[str] = None,
    correlation_b: Optional[str] = None,
    trace_a: Optional[str] = None,
    trace_b: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare two threads/requests to find differences.

    Perfect for root cause analysis: *"What's different between the successful
    request and the failed one?"*

    Args:
        files: Log file paths.
        thread_a: First thread ID to compare.
        thread_b: Second thread ID to compare.
        correlation_a: First correlation ID to compare.
        correlation_b: Second correlation ID to compare.
        trace_a: First trace ID to compare.
        trace_b: Second trace ID to compare.

    Returns:
        ThreadComparison dict with shape::

            {
                "thread_a": {"id": str, "entries": [...], "duration_ms": int, ...},
                "thread_b": {...},
                "differences": {"duration_diff_ms": int, "error_diff": int, ...},
                "summary": str
            }

    Example::

        >>> diff = compare_threads(["app.log"], correlation_a="req-ok", correlation_b="req-fail")
        >>> print(diff["summary"])
    """
    from ._search_core import RUST_AVAILABLE

    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Get both threads
    timeline_a = follow_thread(
        files, thread_id=thread_a, correlation_id=correlation_a, trace_id=trace_a
    )
    timeline_b = follow_thread(
        files, thread_id=thread_b, correlation_id=correlation_b, trace_id=trace_b
    )

    # Analyse thread A
    entries_a = timeline_a.get("entries", [])
    analysis_a = _analyze_thread(entries_a, thread_a or correlation_a or trace_a or "Thread A")

    # Analyse thread B
    entries_b = timeline_b.get("entries", [])
    analysis_b = _analyze_thread(entries_b, thread_b or correlation_b or trace_b or "Thread B")

    # Compare
    differences = _compute_differences(analysis_a, analysis_b)

    # Generate summary
    summary = _generate_comparison_summary(analysis_a, analysis_b, differences)

    return {
        "thread_a": analysis_a,
        "thread_b": analysis_b,
        "differences": differences,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Time-period comparison
# ---------------------------------------------------------------------------


def compare_time_periods(
    files: List[str],
    period_a_start: str,
    period_a_end: str,
    period_b_start: str,
    period_b_end: str,
) -> Dict[str, Any]:
    """Compare two time periods to find what changed.

    Perfect for questions like *"What changed after the deployment?"* or
    *"Why did error rates spike at 3pm?"*

    Args:
        files: Log file paths.
        period_a_start: Start time for period A (ISO format).
        period_a_end: End time for period A (ISO format).
        period_b_start: Start time for period B (ISO format).
        period_b_end: End time for period B (ISO format).

    Returns:
        PeriodComparison dict with shape::

            {
                "period_a": {"start": str, "end": str, "total_logs": int, ...},
                "period_b": {...},
                "changes": {"log_volume_change_pct": float, ...},
                "summary": str
            }

    Example::

        >>> diff = compare_time_periods(["app.log"], "2024-01-01T14:00:00Z",
        ...     "2024-01-01T15:00:00Z", "2024-01-01T15:00:00Z", "2024-01-01T16:00:00Z")
        >>> print(diff["summary"])
    """
    from ._search_core import RUST_AVAILABLE
    from .investigate import Investigator

    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Search each period
    inv = Investigator()
    inv.load_files(files)

    results_a = search(files, limit=0)
    results_b = search(files, limit=0)

    # Filter by time
    entries_a = [
        r["entry"]
        for r in results_a.get("results", [])
        if _in_time_range(r["entry"], period_a_start, period_a_end)
    ]
    entries_b = [
        r["entry"]
        for r in results_b.get("results", [])
        if _in_time_range(r["entry"], period_b_start, period_b_end)
    ]

    # Analyse periods
    analysis_a = _analyze_period(entries_a, period_a_start, period_a_end)
    analysis_b = _analyze_period(entries_b, period_b_start, period_b_end)

    # Compute changes
    changes = _compute_period_changes(analysis_a, analysis_b)

    # Generate summary
    summary = _generate_period_summary(analysis_a, analysis_b, changes)

    return {"period_a": analysis_a, "period_b": analysis_b, "changes": changes, "summary": summary}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _analyze_thread(entries: List[Dict], thread_id: str) -> Dict[str, Any]:
    """Analyse a single thread's entries."""
    if not entries:
        return {
            "id": thread_id,
            "entries": [],
            "duration_ms": 0,
            "error_count": 0,
            "log_levels": {},
            "unique_messages": 0,
            "messages": [],
            "services": [],
        }

    # Count log levels
    level_counts = defaultdict(int)
    error_count = 0
    messages = []
    services = set()

    for entry in entries:
        level = entry.get("level", "INFO")
        level_counts[level] += 1
        if level in ["ERROR", "FATAL"]:
            error_count += 1

        message = entry.get("message", "")
        messages.append(message)

        service = entry.get("service") or entry.get("service_name")
        if service:
            services.add(service)

    # Calculate duration
    duration_ms = 0
    if len(entries) >= 2:
        try:
            start = datetime.fromisoformat(entries[0].get("timestamp", "").replace("Z", "+00:00"))
            end = datetime.fromisoformat(entries[-1].get("timestamp", "").replace("Z", "+00:00"))
            duration_ms = int((end - start).total_seconds() * 1000)
        except (ValueError, TypeError, AttributeError):
            pass  # Skip if timestamps are missing or invalid

    return {
        "id": thread_id,
        "entries": entries,
        "entry_count": len(entries),
        "duration_ms": duration_ms,
        "error_count": error_count,
        "log_levels": dict(level_counts),
        "unique_messages": len(set(messages)),
        "messages": messages,
        "services": list(services),
    }


def _compute_differences(analysis_a: Dict, analysis_b: Dict) -> Dict[str, Any]:
    """Compute differences between two thread analyses."""
    # Duration difference
    duration_diff_ms = analysis_b["duration_ms"] - analysis_a["duration_ms"]

    # Error difference
    error_diff = analysis_b["error_count"] - analysis_a["error_count"]

    # Message differences
    messages_a = set(analysis_a["messages"])
    messages_b = set(analysis_b["messages"])
    only_in_a = list(messages_a - messages_b)
    only_in_b = list(messages_b - messages_a)

    # Log level changes
    level_changes = {}
    all_levels = set(list(analysis_a["log_levels"].keys()) + list(analysis_b["log_levels"].keys()))
    for level in all_levels:
        count_a = analysis_a["log_levels"].get(level, 0)
        count_b = analysis_b["log_levels"].get(level, 0)
        if count_a != count_b:
            level_changes[level] = count_b - count_a

    return {
        "duration_diff_ms": duration_diff_ms,
        "error_diff": error_diff,
        "only_in_a": only_in_a[:10],  # Limit to 10
        "only_in_b": only_in_b[:10],
        "level_changes": level_changes,
        "entry_count_diff": analysis_b["entry_count"] - analysis_a["entry_count"],
    }


def _generate_comparison_summary(analysis_a: Dict, analysis_b: Dict, differences: Dict) -> str:
    """Generate human-readable summary of comparison."""
    parts = []

    # Duration
    duration_diff = differences["duration_diff_ms"]
    if abs(duration_diff) > 100:
        if duration_diff > 0:
            parts.append(f"Thread B took {duration_diff}ms longer")
        else:
            parts.append(f"Thread B was {-duration_diff}ms faster")

    # Errors
    error_diff = differences["error_diff"]
    if error_diff > 0:
        parts.append(f"Thread B had {error_diff} more error(s)")
        if differences["only_in_b"]:
            examples = differences["only_in_b"][:3]
            parts.append(f"including: {', '.join(examples)}")
    elif error_diff < 0:
        parts.append(f"Thread B had {-error_diff} fewer error(s)")

    # New messages in B
    if differences["only_in_b"] and error_diff == 0:
        parts.append(f"Thread B had unique messages: {', '.join(differences['only_in_b'][:3])}")

    if not parts:
        parts.append("Threads are similar")

    return ". ".join(parts)


def _analyze_period(entries: List[Dict], start: str, end: str) -> Dict[str, Any]:
    """Analyse a time period's entries."""
    level_counts = defaultdict(int)
    error_messages = []
    threads = set()

    for entry in entries:
        level = entry.get("level", "INFO")
        level_counts[level] += 1

        if level in ["ERROR", "FATAL"]:
            error_messages.append(entry.get("message", ""))

        thread = entry.get("thread_id") or entry.get("correlation_id")
        if thread:
            threads.add(thread)

    total = len(entries)
    error_count = level_counts.get("ERROR", 0) + level_counts.get("FATAL", 0)
    error_rate = error_count / total if total > 0 else 0

    return {
        "start": start,
        "end": end,
        "total_logs": total,
        "error_count": error_count,
        "error_rate": error_rate,
        "log_levels": dict(level_counts),
        "top_errors": list(set(error_messages))[:10],
        "unique_threads": len(threads),
    }


def _compute_period_changes(analysis_a: Dict, analysis_b: Dict) -> Dict[str, Any]:
    """Compute changes between two time periods."""
    # Volume change
    if analysis_a["total_logs"] > 0:
        volume_change_pct = (
            (analysis_b["total_logs"] - analysis_a["total_logs"]) / analysis_a["total_logs"]
        ) * 100
    else:
        volume_change_pct = 100 if analysis_b["total_logs"] > 0 else 0

    # Error rate change
    if analysis_a["error_rate"] > 0:
        error_rate_multiplier = analysis_b["error_rate"] / analysis_a["error_rate"]
    else:
        error_rate_multiplier = float("inf") if analysis_b["error_rate"] > 0 else 1.0

    # New vs resolved errors
    errors_a = set(analysis_a["top_errors"])
    errors_b = set(analysis_b["top_errors"])
    new_errors = list(errors_b - errors_a)
    resolved_errors = list(errors_a - errors_b)

    return {
        "log_volume_change_pct": volume_change_pct,
        "error_rate_multiplier": error_rate_multiplier,
        "error_count_change": analysis_b["error_count"] - analysis_a["error_count"],
        "new_errors": new_errors[:10],
        "resolved_errors": resolved_errors[:10],
        "thread_count_change": analysis_b["unique_threads"] - analysis_a["unique_threads"],
    }


def _generate_period_summary(analysis_a: Dict, analysis_b: Dict, changes: Dict) -> str:
    """Generate human-readable summary of period comparison."""
    parts = []

    # Volume
    vol_change = changes["log_volume_change_pct"]
    if abs(vol_change) > 20:
        parts.append(
            f"Log volume {'increased' if vol_change > 0 else 'decreased'} by {abs(vol_change):.1f}%"
        )

    # Error rate
    err_mult = changes["error_rate_multiplier"]
    if err_mult > 1.5:
        parts.append(f"Error rate increased {err_mult:.1f}x")
    elif err_mult < 0.7 and err_mult > 0:
        parts.append(f"Error rate decreased to {err_mult:.1f}x")

    # New errors
    if changes["new_errors"]:
        parts.append(f"New errors: {', '.join(changes['new_errors'][:3])}")

    if not parts:
        parts.append("Periods are similar")

    return ". ".join(parts)


def _in_time_range(entry: Dict, start: str, end: str) -> bool:
    """Check if entry timestamp is within range."""
    timestamp_str = entry.get("timestamp")
    if not timestamp_str:
        return False

    try:
        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return start_dt <= timestamp <= end_dt
    except (ValueError, TypeError, AttributeError):
        return False
