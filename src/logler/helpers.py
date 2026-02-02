"""
Helper Utilities for Common Investigation Patterns

This module provides convenience functions that wrap common investigation
patterns, making it easier for LLM agents to perform typical tasks.
"""

from typing import List, Dict, Any, Optional
import logler.investigate as investigate
from logler.investigate import Investigator


def quick_summary(files: List[str]) -> Dict[str, Any]:
    """
    Get a quick summary of log files.

    Returns a dictionary with:
    - total_lines: Total number of log entries
    - time_range: Start and end timestamps
    - log_levels: Count of each log level
    - error_rate: Percentage of ERROR/FATAL logs
    - top_threads: Most active threads

    Example:
        summary = quick_summary(["app.log"])
        print(f"Error rate: {summary['error_rate']:.1f}%")
    """
    metadata = investigate.get_metadata(files)
    if not metadata:
        return {}

    meta = metadata[0]
    total = meta["lines"]
    levels = meta.get("log_levels", {})

    errors = levels.get("ERROR", 0) + levels.get("FATAL", 0) + levels.get("CRITICAL", 0)
    error_rate = (errors / total * 100) if total > 0 else 0

    return {
        "total_lines": total,
        "time_range": meta.get("time_range"),
        "log_levels": levels,
        "error_rate": error_rate,
        "unique_threads": meta.get("unique_threads", 0),
        "unique_correlations": meta.get("unique_correlation_ids", 0),
    }


def search_errors(
    files: List[str], query: Optional[str] = None, limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Search for ERROR and FATAL level logs.

    Example:
        errors = search_errors(["app.log"], query="database")
        for err in errors:
            print(f"Line {err['line_number']}: {err['message']}")
    """
    results = investigate.search(files=files, query=query, level="ERROR", limit=limit)
    return [r["entry"] for r in results["results"]]


def trace_request(files: List[str], correlation_id: str) -> Dict[str, Any]:
    """
    Trace a complete request by correlation ID.

    Returns a dictionary with:
    - entries: List of all log entries for this request
    - duration_ms: Total request duration
    - error_count: Number of errors in this request
    - services: List of services involved (if available)

    Example:
        trace = trace_request(["app.log"], "req-abc123")
        print(f"Request took {trace['duration_ms']}ms with {trace['error_count']} errors")
    """
    timeline = investigate.follow_thread(files=files, correlation_id=correlation_id)

    error_count = sum(
        1 for e in timeline["entries"] if e.get("level") in ["ERROR", "FATAL", "CRITICAL"]
    )

    # Extract unique services if available
    services = set()
    for entry in timeline["entries"]:
        if "service" in entry.get("fields", {}):
            services.add(entry["fields"]["service"])

    return {
        "entries": timeline["entries"],
        "duration_ms": timeline.get("duration_ms"),
        "error_count": error_count,
        "services": list(services),
        "total_entries": timeline["total_entries"],
    }


def get_error_context(file: str, line_number: int, lines: int = 10) -> Dict[str, Any]:
    """
    Get context around an error line.

    Example:
        context = get_error_context("app.log", 42, lines=5)
        print("Before:")
        for entry in context['before']:
            print(f"  {entry['message']}")
        print(f"ERROR: {context['error']['message']}")
    """
    inv = Investigator()
    inv.load_files([file])
    context = inv.get_context(file, line_number, lines, lines)

    return {
        "error": context["target"],
        "before": context["context_before"],
        "after": context["context_after"],
    }


def analyze_thread_health(files: List[str]) -> Dict[str, Dict[str, int]]:
    """
    Analyze health of each thread.

    Returns a dictionary mapping thread IDs to their log level counts.

    Example:
        health = analyze_thread_health(["app.log"])
        for thread, counts in health.items():
            error_rate = counts.get('ERROR', 0) / counts.get('total', 1) * 100
            print(f"{thread}: {error_rate:.1f}% errors")
    """
    # Get all entries
    metadata = investigate.get_metadata(files)
    inv = Investigator()
    inv.load_files(files)

    # This is a simplified version - full implementation would track by thread
    # For now, return basic info
    return {
        "note": "Thread health analysis requires SQL queries for full implementation",
        "total_threads": metadata[0].get("unique_threads", 0),
    }


def get_timeline_summary(files: List[str], correlation_id: str) -> str:
    """
    Get a human-readable timeline summary for a request.

    Example:
        summary = get_timeline_summary(["app.log"], "req-001")
        print(summary)
    """
    timeline = investigate.follow_thread(files=files, correlation_id=correlation_id)

    if not timeline["entries"]:
        return f"No entries found for correlation_id={correlation_id}"

    lines = []
    lines.append(f"Request {correlation_id} Timeline:")
    lines.append(f"Duration: {timeline.get('duration_ms', 'unknown')}ms")
    lines.append(f"Total entries: {timeline['total_entries']}")
    lines.append("")

    for i, entry in enumerate(timeline["entries"][:10], 1):  # Limit to first 10
        level_emoji = {
            "INFO": "ℹ️",
            "WARN": "⚠️",
            "ERROR": "❌",
            "FATAL": "💀",
            "CRITICAL": "🔴",
        }.get(entry.get("level"), "📝")

        thread = entry.get("thread_id", "unknown")
        message = entry.get("message", "")[:60]
        lines.append(f"{i:2d}. {level_emoji} [{thread}] {message}")

    if timeline["total_entries"] > 10:
        lines.append(f"... and {timeline['total_entries'] - 10} more entries")

    return "\n".join(lines)


# Convenience aliases for common operations
def errors(files: List[str], **kwargs) -> List[Dict[str, Any]]:
    """Shorthand for search_errors()"""
    return search_errors(files, **kwargs)


def trace(files: List[str], correlation_id: str) -> Dict[str, Any]:
    """Shorthand for trace_request()"""
    return trace_request(files, correlation_id)


def summary(files: List[str]) -> Dict[str, Any]:
    """Shorthand for quick_summary()"""
    return quick_summary(files)
