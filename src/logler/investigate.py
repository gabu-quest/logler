"""
LLM Investigation Module - High-performance log investigation powered by Rust

This module provides fast log parsing, searching, and investigation capabilities
specifically designed for LLM agents like Claude.

Implementation is split across focused submodules for maintainability:

* :mod:`logler._search_core`  — search, follow, context, patterns, metadata
* :mod:`logler.hierarchy`     — thread hierarchy, error flow, bottleneck analysis
* :mod:`logler.export`        — Jaeger / Zipkin trace export
* :mod:`logler.comparison`    — thread & time-period comparison, cross-service timeline
* :mod:`logler.sampling`      — smart sampling strategies
* :mod:`logler.session`       — InvestigationSession (stateful investigations)

All public symbols are re-exported here so that existing code continues to work::

    from logler.investigate import search, follow_thread_hierarchy, Investigator

Example Usage::

    import logler.investigate as investigate

    results = investigate.search(
        files=["app.log"],
        query="database timeout",
        level="ERROR",
        limit=10
    )
"""

# Re-export everything so ``from logler.investigate import X`` keeps working.

import json
from typing import List, Optional, Dict, Any

# ---------------------------------------------------------------------------
# Core search / navigation (private module)
# ---------------------------------------------------------------------------
from ._search_core import (  # noqa: F401
    RUST_AVAILABLE,
    search,
    extract_ids,
    follow_thread,
    get_context,
    get_metadata,
    find_patterns,
    # Private helpers re-exported for Investigator class & tests
    _normalize_entry,
    _normalize_entries,
    _normalize_search_result_levels,
    _apply_custom_regex_to_results,
    _apply_custom_regex_to_entry,
    _normalize_pattern_examples,
    _infer_syslog_level,
    _parse_timestamp_flex,
    _normalize_context_payload,
    _build_time_range,
    _parse_levels,
    _format_as_summary,
    _format_as_count,
    _format_as_compact,
    _select_diverse_samples,
    _load_files_with_config,
    _auto_detect_format_from_config,
    _LEVEL_MAP,
)

# ---------------------------------------------------------------------------
# Hierarchy, error flow, bottleneck, correlation chains
# ---------------------------------------------------------------------------
from .hierarchy import (  # noqa: F401
    follow_thread_hierarchy,
    get_hierarchy_summary,
    analyze_error_flow,
    format_error_flow,
    detect_correlation_chains,
    build_hierarchy_with_correlation_chains,
    analyze_bottlenecks,
    diff_hierarchies,
    format_hierarchy_diff,
    _format_detection_method,
    _append_tree_preview,
)

# ---------------------------------------------------------------------------
# Export (Jaeger / Zipkin)
# ---------------------------------------------------------------------------
from .export import (  # noqa: F401
    export_to_jaeger,
    export_to_zipkin,
)

# ---------------------------------------------------------------------------
# Comparison (threads, periods, cross-service)
# ---------------------------------------------------------------------------
from .comparison import (  # noqa: F401
    cross_service_timeline,
    compare_threads,
    compare_time_periods,
    _analyze_thread,
    _compute_differences,
    _generate_comparison_summary,
    _analyze_period,
    _compute_period_changes,
    _generate_period_summary,
    _in_time_range,
)

# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
from .sampling import (  # noqa: F401
    smart_sample,
)

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
from .session import InvestigationSession  # noqa: F401


# ============================================================================
# Investigator class — kept here to avoid circular imports
# ============================================================================


class Investigator:
    """Advanced investigation API with persistent index.

    Use this when you need to perform multiple operations on the same files
    for better performance.

    Args:
        sql_db_path: Optional path for a disk-backed DuckDB database.
            Use this for large datasets (100K+ entries) to avoid OOM.
            Defaults to in-memory.

    Example::

        investigator = Investigator()
        investigator.load_files(["app.log", "api.log"])

        results = investigator.search(query="error", limit=10)
        patterns = investigator.find_patterns(min_occurrences=5)
        metadata = investigator.get_metadata()

    For large datasets::

        investigator = Investigator(sql_db_path="/tmp/inv.duckdb")
        investigator.load_files(["huge.log"])
        results = investigator.sql_query("SELECT level, COUNT(*) FROM logs GROUP BY level")
    """

    def __init__(self, sql_db_path: Optional[str] = None):
        if not RUST_AVAILABLE:
            raise RuntimeError("Rust backend not available")
        import logler_rs

        self._investigator = logler_rs.PyInvestigator()
        self._files: List[str] = []
        self._custom_regex: Optional[str] = None
        self._db_temp_files: List[str] = []
        self._sql_engine = None
        self._sql_db_path = sql_db_path

    def load_files(
        self,
        files: List[str],
        parser_format: Optional[str] = None,
        custom_regex: Optional[str] = None,
    ):
        """Load log files and build index."""
        _load_files_with_config(self._investigator, files, parser_format, custom_regex)
        self._files = files
        self._custom_regex = custom_regex
        # Invalidate cached SQL engine so next query rebuilds with new data
        if self._sql_engine is not None:
            self._sql_engine.close()
            self._sql_engine = None

    def get_metadata(self) -> List[Dict[str, Any]]:  # noqa: F811
        """Get metadata about loaded log files."""
        return json.loads(self._investigator.get_metadata(self._files))

    def get_context(  # noqa: F811
        self,
        file: str,
        line_number: int,
        lines_before: int = 10,
        lines_after: int = 10,
    ) -> Dict[str, Any]:
        """Get context around a specific log line."""
        result_json = self._investigator.get_context(
            file, line_number, lines_before, lines_after, False
        )
        result = json.loads(result_json)
        _normalize_context_payload(result)
        return result

    def follow_thread(  # noqa: F811
        self,
        thread_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Follow a thread/correlation/trace through loaded files."""
        result_json = self._investigator.follow_thread(
            self._files, thread_id, correlation_id, trace_id
        )
        result = json.loads(result_json)
        _normalize_entries(result.get("entries", []))
        return result

    def search(
        self,
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
        count_only: bool = False,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Search loaded files.

        Args:
            count_only: If True, return only ``total_matches`` (no results).
                Skips Rust Phase 2 materialization — zero memory overhead.
            offset: Skip first *N* sorted results before taking ``limit``.
                Server-side pagination: ``offset=100, limit=100`` → page 2.
        """
        filters: Dict[str, Any] = {"levels": [], "exclude_levels": []}
        if level:
            filters["levels"] = _parse_levels(level)
        if exclude_level:
            filters["exclude_levels"] = _parse_levels(exclude_level)
        if exclude_query:
            filters["exclude_pattern"] = exclude_query
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
        if time_start or time_end:
            tr: Dict[str, str] = {}
            if time_start:
                tr["start"] = time_start
            if time_end:
                tr["end"] = time_end
            filters["time_range"] = tr

        query_dict: Dict[str, Any] = {
            "files": self._files,
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

        result_json = self._investigator.search(json.dumps(query_dict))
        result = json.loads(result_json)
        _normalize_search_result_levels(result)
        _apply_custom_regex_to_results(result, self._custom_regex)
        return result

    def sql_query(self, query: str) -> List[Dict[str, Any]]:
        """Execute SQL query on loaded logs.

        Args:
            query: SQL query string.

        Returns:
            List of result rows as dictionaries.

        Example::

            results = investigator.sql_query('''
                SELECT level, COUNT(*) as count
                FROM logs
                GROUP BY level
                ORDER BY count DESC
            ''')
        """
        engine = self._get_sql_engine()
        result_json = engine.query(query)
        return json.loads(result_json)

    def sql_tables(self) -> List[str]:
        """Get list of available SQL tables."""
        engine = self._get_sql_engine()
        return engine.get_tables()

    def sql_schema(self, table: str) -> List[Dict[str, Any]]:
        """Get schema for a SQL table."""
        engine = self._get_sql_engine()
        result_json = engine.get_schema(table)
        return json.loads(result_json)

    _SQL_ENGINE_PAGE_SIZE = 10_000

    def _get_entries_page(self, offset: int, limit: int) -> str:
        """Fetch a page of raw entries from the Rust index (JSON string)."""
        return self._investigator.get_entries_page(offset, limit)

    def _get_sql_engine(self):
        """Get a SQL engine loaded with current log data.

        The engine is built once and cached for the lifetime of this
        Investigator (or until :meth:`load_files` is called again).

        Uses ``get_entries_page()`` to iterate the Rust index directly —
        O(page_size) per call, O(N) total. No search/filter/sort overhead.
        """
        if self._sql_engine is not None:
            return self._sql_engine

        from types import SimpleNamespace

        from logler.sql import SqlEngine

        engine = SqlEngine(db_path=self._sql_db_path)
        offset = 0

        while True:
            page_json = self._get_entries_page(offset, self._SQL_ENGINE_PAGE_SIZE)
            page = json.loads(page_json)
            items = page.get("entries", [])
            if not items:
                break

            indices: Dict[str, Any] = {}
            for entry in items:
                fp = entry.get("file", "unknown")
                if fp not in indices:
                    indices[fp] = SimpleNamespace(entries=[])
                ns = SimpleNamespace()
                for k, v in entry.items():
                    # Rust serializes LogLevel as title-case ("Info");
                    # normalize to uppercase for consistency with search().
                    if k == "level" and isinstance(v, str):
                        v = v.upper()
                    setattr(ns, k, v)
                indices[fp].entries.append(ns)

            engine.load_files(indices)
            offset += self._SQL_ENGINE_PAGE_SIZE

            if not page.get("has_more", False):
                break

        self._sql_engine = engine
        return engine

    def build_hierarchy(
        self,
        root_identifier: str,
        max_depth: Optional[int] = None,
        use_naming_patterns: bool = True,
        use_temporal_inference: bool = True,
        min_confidence: float = 0.0,
    ) -> Dict[str, Any]:
        """Build hierarchical tree of threads/spans from loaded files.

        Args:
            root_identifier: Root thread ID, correlation ID, or span ID.
            max_depth: Maximum depth of hierarchy tree.
            use_naming_patterns: Enable naming pattern detection.
            use_temporal_inference: Enable time-based inference.
            min_confidence: Minimum confidence score (0.0-1.0).

        Returns:
            Hierarchy dictionary (see :func:`follow_thread_hierarchy` for structure).

        Example::

            inv = Investigator()
            inv.load_files(["app.log"])
            hierarchy = inv.build_hierarchy(root_identifier="req-123")
            summary = get_hierarchy_summary(hierarchy)
            print(summary)
        """
        result_json = self._investigator.build_hierarchy(
            self._files,
            root_identifier,
            max_depth,
            use_naming_patterns,
            use_temporal_inference,
            min_confidence,
        )
        return json.loads(result_json)

    def load_from_db(
        self,
        db_path: str,
        mappings: Optional[List] = None,
    ) -> None:
        """Load a sqler database as a log source.

        Converts the database to JSONL and feeds it into the Rust parser,
        giving full access to all logler features (search, hierarchy,
        correlation, etc.).

        Args:
            db_path: Path to the SQLite database file.
            mappings: List of :class:`~logler.db_source.DbTableMapping`.
                Auto-detected if None.

        Example::

            inv = Investigator()
            inv.load_from_db("qler.db")
            results = inv.search(level="ERROR")
            inv.close()  # clean up temp files
        """
        from .db_source import db_to_jsonl

        jsonl_path = db_to_jsonl(db_path, mappings)
        self._db_temp_files.append(jsonl_path)
        _load_files_with_config(self._investigator, [jsonl_path], None, None)
        self._files.append(jsonl_path)

    def close(self) -> None:
        """Clean up temporary files created by :meth:`load_from_db`."""
        import os

        for path in self._db_temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass
        self._db_temp_files.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# ============================================================================
# Numeric Extraction Wrappers (M5)
# ============================================================================


def extract_metrics(
    files: List[str],
    fields: Optional[List[str]] = None,
    bucket_size: Optional[str] = None,
    anomaly_threshold: float = 2.0,
    query: Optional[str] = None,
    level: Optional[str] = None,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract numeric metrics from log files.

    Loads files via :func:`search`, extracts numeric values from entries,
    and returns time-series stats with optional bucketing and anomaly detection.

    Args:
        files: Log file paths to analyse.
        fields: If specified, only return these field names.
        bucket_size: If specified, include time-bucketed aggregation (e.g. ``"5s"``).
        anomaly_threshold: Z-score threshold for anomaly detection (default 2.0).
        query: Optional search query to filter entries.
        level: Optional log level filter.
        time_start: Optional time range start (ISO 8601).
        time_end: Optional time range end (ISO 8601).
        parser_format: Optional parser format hint.
        custom_regex: Optional custom regex for parsing.

    Returns:
        MetricsExtractionResult dict with shape::

            {
                "fields": {"field_name": {"count": int, "min": float, "max": float, ...}},
                "entries_scanned": int,
                "files_searched": int
            }

    Example::

        >>> metrics = extract_metrics(["app.log"], fields=["duration_ms"])
        >>> stats = metrics["fields"]["duration_ms"]
        >>> print(f"p95={stats['p95']}ms, mean={stats['mean']:.1f}ms")
    """
    from .metrics import extract_metrics as _extract

    # Load all entries for metrics (limit=0 bypasses DEFAULT_MAX_RESULTS)
    result = search(
        files=files,
        query=query,
        level=level,
        limit=0,
        time_start=time_start,
        time_end=time_end,
        parser_format=parser_format,
        custom_regex=custom_regex,
    )

    entries = [item.get("entry", {}) for item in result.get("results", [])]

    metrics = _extract(
        entries, fields=fields, bucket_size=bucket_size, anomaly_threshold=anomaly_threshold
    )
    metrics["files_searched"] = len(files)
    return metrics


# ============================================================================
# Format Detection Wrappers (M6)
# ============================================================================


def detect_formats(
    files: List[str],
    sample_size: int = 50,
) -> Dict[str, Any]:
    """Detect log format for each file.

    Args:
        files: Log file paths to analyse.
        sample_size: Number of lines to sample per file.

    Returns:
        FormatDetectionResult dict with shape::

            {"files": {"path": {"format": str, "confidence": float, ...}}}

    Example::

        >>> detection = detect_formats(["app.log"])
        >>> for path, info in detection["files"].items():
        ...     print(f"{path}: {info['format']} ({info['confidence']:.0%})")
    """
    from .format_detector import detect_format as _detect

    # Load custom formats from config if available
    custom_formats = None
    try:
        from pathlib import Path as _Path
        from .config import find_config, load_config

        if files:
            start_dir = _Path(files[0]).resolve().parent
            config_path = find_config(start_dir)
            if config_path:
                config = load_config(config_path)
                if config.formats:
                    custom_formats = {
                        name: {"regex": fmt.regex} for name, fmt in config.formats.items()
                    }
    except Exception:
        pass  # Config loading should never break detection

    results = {}
    for file_path in files:
        detection = _detect(file_path, sample_size=sample_size, custom_formats=custom_formats)
        results[file_path] = {
            "format": detection.format,
            "confidence": detection.confidence,
            "sample_size": detection.sample_size,
            "match_rate": detection.match_rate,
            "alternatives": detection.alternatives,
            "detected_fields": detection.detected_fields,
            "sample_lines": detection.sample_lines,
            "mixed": detection.mixed,
        }

    return {"files": results}


def mine_log_templates(
    files: List[str],
    max_clusters: int = 200,
    sim_threshold: float = 0.5,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> Dict[str, Any]:
    """Mine log templates from files using the Drain algorithm.

    Args:
        files: Log file paths to analyse.
        max_clusters: Maximum number of template clusters.
        sim_threshold: Minimum token similarity for cluster merge.
        parser_format: Optional parser format hint.
        custom_regex: Optional custom regex for parsing.

    Returns:
        TemplateMiningResult dict with shape::

            {
                "templates": [...],
                "total_lines": int,
                "unique_templates": int,
                "coverage": float,
                "files_searched": int
            }

    Example::

        >>> result = mine_log_templates(["app.log"])
        >>> for t in result["templates"][:5]:
        ...     print(f"{t['count']}x: {t['template']}")
    """
    from .format_detector import mine_templates as _mine

    # Load all entries for template mining (limit=0 bypasses DEFAULT_MAX_RESULTS)
    result = search(
        files=files,
        limit=0,
        parser_format=parser_format,
        custom_regex=custom_regex,
    )

    messages = [
        item.get("entry", {}).get("message", "")
        for item in result.get("results", [])
        if item.get("entry", {}).get("message")
    ]

    template_result = _mine(messages, max_clusters=max_clusters, sim_threshold=sim_threshold)

    return {
        "templates": template_result.templates,
        "total_lines": template_result.total_lines,
        "unique_templates": template_result.unique_templates,
        "coverage": template_result.coverage,
        "files_searched": len(files),
    }


# ============================================================================
# Database Source (M-1: logler-sqler bridge)
# ============================================================================


# Re-export for convenience: ``from logler.investigate import DbTableMapping``
from .db_source import (  # noqa: E402, F401
    DbTableMapping,
    qler_job_mapping,
    qler_attempt_mapping,
)


def search_db(
    db_path: str,
    mappings: Optional[List] = None,
    query: Optional[str] = None,
    level: Optional[str] = None,
    correlation_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """One-shot convenience: load a sqler DB and search it.

    Creates a temporary :class:`Investigator`, loads the database,
    searches, and cleans up.

    Args:
        db_path: Path to the SQLite database file.
        mappings: Table mappings. Auto-detected if None.
        query: Search query regex.
        level: Log level filter (e.g. ``"ERROR"``).
        correlation_id: Filter by correlation ID.
        limit: Maximum results to return.

    Returns:
        Search results dict (same shape as :meth:`Investigator.search`).

    Example::

        from logler.investigate import search_db
        results = search_db("qler.db", level="ERROR")
    """
    inv = Investigator()
    try:
        inv.load_from_db(db_path, mappings)
        return inv.search(
            query=query,
            level=level,
            correlation_id=correlation_id,
            limit=limit,
        )
    finally:
        inv.close()
