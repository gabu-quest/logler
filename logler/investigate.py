"""
LLM Investigation Module - High-performance log investigation powered by Rust

This module provides fast log parsing, searching, and investigation capabilities
specifically designed for LLM agents like Claude.

Example Usage:
    import logler.investigate as investigate

    # Search for errors
    results = investigate.search(
        files=["app.log"],
        query="database timeout",
        level="ERROR",
        limit=10
    )

    # Follow a thread
    timeline = investigate.follow_thread(
        files=["app.log"],
        thread_id="worker-1"
    )

    # Find patterns
    patterns = investigate.find_patterns(
        files=["app.log"],
        min_occurrences=3
    )
"""

import json
from typing import List, Optional, Dict, Any

try:
    import logler_rs
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    print("Warning: Rust backend not available. Using Python fallback.")


def search(
    files: List[str],
    query: Optional[str] = None,
    level: Optional[str] = None,
    thread_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    limit: Optional[int] = None,
    context_lines: int = 3,
) -> Dict[str, Any]:
    """
    Search logs with filters.

    Args:
        files: List of log file paths
        query: Search query string
        level: Filter by log level (ERROR, WARN, INFO, etc.)
        thread_id: Filter by thread ID
        correlation_id: Filter by correlation ID
        limit: Maximum number of results
        context_lines: Number of context lines before/after each result

    Returns:
        Dictionary with search results:
        {
            "results": [...],
            "total_matches": 123,
            "search_time_ms": 45
        }
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Build query
    filters = {}
    if level:
        filters["levels"] = [level.upper()]
    if thread_id:
        filters["thread_id"] = thread_id
    if correlation_id:
        filters["correlation_id"] = correlation_id

    query_dict = {
        "files": files,
        "query": query,
        "filters": filters,
        "limit": limit,
        "context_lines": context_lines,
    }

    # Call Rust function
    result_json = logler_rs.search(files, query or "", limit)
    return json.loads(result_json)


def follow_thread(
    files: List[str],
    thread_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Follow a thread/correlation/trace through log files.

    Args:
        files: List of log file paths
        thread_id: Thread ID to follow
        correlation_id: Correlation ID to follow
        trace_id: Trace ID to follow

    Returns:
        Dictionary with timeline:
        {
            "entries": [...],
            "total_entries": 42,
            "duration_ms": 1523,
            "unique_spans": [...]
        }
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    result_json = logler_rs.follow_thread(files, thread_id, correlation_id, trace_id)
    return json.loads(result_json)


def get_context(
    file: str,
    line_number: int,
    lines_before: int = 10,
    lines_after: int = 10,
) -> Dict[str, Any]:
    """
    Get context around a specific log line.

    Args:
        file: Log file path
        line_number: Line number to get context for
        lines_before: Number of lines before
        lines_after: Number of lines after

    Returns:
        Dictionary with context:
        {
            "target": {...},
            "context_before": [...],
            "context_after": [...],
        }
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Use Investigator class for more complex operations
    investigator = logler_rs.PyInvestigator()
    investigator.load_files([file])
    result_json = investigator.get_context(file, line_number, lines_before, lines_after, False)
    return json.loads(result_json)


def find_patterns(
    files: List[str],
    min_occurrences: int = 3,
) -> Dict[str, Any]:
    """
    Find repeated patterns and anomalies in logs.

    Args:
        files: List of log file paths
        min_occurrences: Minimum number of occurrences to consider a pattern

    Returns:
        Dictionary with patterns:
        {
            "patterns": [
                {
                    "pattern": "...",
                    "occurrences": 15,
                    "first_seen": "...",
                    "last_seen": "...",
                    "affected_threads": [...],
                    "examples": [...]
                }
            ]
        }
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    result_json = logler_rs.find_patterns(files, min_occurrences)
    return json.loads(result_json)


def get_metadata(files: List[str]) -> Dict[str, Any]:
    """
    Get metadata about log files.

    Args:
        files: List of log file paths

    Returns:
        List of file metadata:
        [
            {
                "path": "...",
                "size_bytes": 12345,
                "lines": 5000,
                "format": "json",
                "time_range": {...},
                "available_fields": [...],
                "unique_threads": 8,
                "unique_correlation_ids": 123,
                "log_levels": {...}
            }
        ]
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    result_json = logler_rs.get_metadata(files)
    return json.loads(result_json)


# Advanced API using Investigator class
class Investigator:
    """
    Advanced investigation API with persistent index.

    Use this when you need to perform multiple operations on the same files
    for better performance.

    Example:
        investigator = Investigator()
        investigator.load_files(["app.log", "api.log"])

        results = investigator.search(query="error", limit=10)
        patterns = investigator.find_patterns(min_occurrences=5)
        metadata = investigator.get_metadata()
    """

    def __init__(self):
        if not RUST_AVAILABLE:
            raise RuntimeError("Rust backend not available")
        self._investigator = logler_rs.PyInvestigator()
        self._files = []

    def load_files(self, files: List[str]):
        """Load log files and build index."""
        self._investigator.load_files(files)
        self._files = files

    def search(
        self,
        query: Optional[str] = None,
        level: Optional[str] = None,
        thread_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        limit: Optional[int] = None,
        context_lines: int = 3,
    ) -> Dict[str, Any]:
        """Search loaded files."""
        filters = {}
        if level:
            filters["levels"] = [level.upper()]
        if thread_id:
            filters["thread_id"] = thread_id
        if correlation_id:
            filters["correlation_id"] = correlation_id

        query_dict = {
            "files": self._files,
            "query": query,
            "filters": filters,
            "limit": limit,
            "context_lines": context_lines,
        }

        result_json = self._investigator.search(json.dumps(query_dict))
        return json.loads(result_json)

    def follow_thread(
        self,
        thread_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Follow thread in loaded files."""
        result_json = self._investigator.follow_thread(self._files, thread_id, correlation_id, trace_id)
        return json.loads(result_json)

    def find_patterns(self, min_occurrences: int = 3) -> Dict[str, Any]:
        """Find patterns in loaded files."""
        result_json = self._investigator.find_patterns(self._files, min_occurrences)
        return json.loads(result_json)

    def get_metadata(self) -> Dict[str, Any]:
        """Get metadata for loaded files."""
        result_json = self._investigator.get_metadata(self._files)
        return json.loads(result_json)

    def get_context(
        self,
        file: str,
        line_number: int,
        lines_before: int = 10,
        lines_after: int = 10,
    ) -> Dict[str, Any]:
        """Get context around a line."""
        result_json = self._investigator.get_context(file, line_number, lines_before, lines_after, False)
        return json.loads(result_json)
