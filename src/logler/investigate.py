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
import re
import warnings
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from collections import defaultdict

from .safe_regex import try_compile

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


def _normalize_entry(entry: Dict[str, Any]) -> None:
    """Normalize a single log entry in-place (e.g., ensure uppercase levels)."""
    if not isinstance(entry, dict):
        return
    level = entry.get("level")
    if isinstance(level, str):
        entry["level"] = level.upper()
    raw = entry.get("raw") or ""
    # Always detect and set format based on raw content
    if isinstance(raw, str):
        stripped = raw.lstrip()
        if stripped.startswith("{"):
            entry["format"] = "Json"
        elif stripped.startswith("<") and stripped[1:2].isdigit():
            entry["format"] = "Syslog"
        elif "level=" in raw or " msg=" in raw or raw.startswith("level="):
            entry["format"] = "Logfmt"
        elif entry.get("format") is None:
            entry["format"] = "PlainText"
    if entry.get("level") is None and isinstance(raw, str):
        inferred = _infer_syslog_level(raw)
        entry["level"] = inferred or "UNKNOWN"


def _normalize_entries(entries: List[Dict[str, Any]]) -> None:
    for entry in entries or []:
        _normalize_entry(entry)


def _normalize_search_result_levels(result: Dict[str, Any]) -> None:
    """Ensure search results and their contexts use consistent level casing."""
    for item in result.get("results", []) or []:
        _normalize_entry(item.get("entry", {}))
        for ctx in item.get("context_before", []) or []:
            _normalize_entry(ctx)
        for ctx in item.get("context_after", []) or []:
            _normalize_entry(ctx)


def _apply_custom_regex_to_results(result: Dict[str, Any], pattern: Optional[str]) -> None:
    """Apply a user-provided regex to fill missing fields like timestamp/level."""
    if not pattern:
        return
    regex = try_compile(pattern)
    if regex is None:
        return

    for item in result.get("results", []) or []:
        _apply_custom_regex_to_entry(item.get("entry", {}), regex)
        for ctx in item.get("context_before", []) or []:
            _apply_custom_regex_to_entry(ctx, regex)
        for ctx in item.get("context_after", []) or []:
            _apply_custom_regex_to_entry(ctx, regex)


def _apply_custom_regex_to_entry(entry: Dict[str, Any], regex: re.Pattern[str]) -> None:
    if not isinstance(entry, dict):
        return
    raw = entry.get("raw") or entry.get("message") or ""
    match = regex.match(raw)
    if not match:
        return

    groups = match.groupdict()
    ts_val = groups.get("timestamp")
    if ts_val and not entry.get("timestamp"):
        parsed = _parse_timestamp_flex(ts_val)
        if parsed:
            entry["timestamp"] = parsed
    if groups.get("level") and not entry.get("level"):
        entry["level"] = groups["level"].upper()
    if groups.get("message") and entry.get("message") == raw:
        entry["message"] = groups["message"]
    if groups.get("thread") and not entry.get("thread_id"):
        entry["thread_id"] = groups["thread"]
    if groups.get("correlation_id") and not entry.get("correlation_id"):
        entry["correlation_id"] = groups["correlation_id"]
    entry["format"] = "Custom"


def _normalize_pattern_examples(result: Dict[str, Any]) -> None:
    """Normalize example entries inside pattern detection results."""
    for pattern in result.get("patterns", []) or []:
        for example in pattern.get("examples", []) or []:
            _normalize_entry(example)


def _infer_syslog_level(raw: str) -> Optional[str]:
    match = re.match(r"<(?P<priority>\d+)>", raw.strip())
    if not match:
        return None
    try:
        priority = int(match.group("priority"))
    except ValueError:
        return None
    severity = priority & 0x07
    if severity == 0:
        return "FATAL"
    if severity <= 3:
        return "ERROR"
    if severity == 4:
        return "WARN"
    if severity <= 6:
        return "INFO"
    return "DEBUG"


def _parse_timestamp_flex(value: str) -> Optional[str]:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(value.replace("Z", "+0000"), fmt)
            return dt.isoformat()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except Exception:
        return None


def _normalize_context_payload(payload: Dict[str, Any]) -> None:
    """Normalize context payload returned from Rust backend."""
    _normalize_entry(payload.get("target", {}))
    _normalize_entries(payload.get("context_before", []))
    _normalize_entries(payload.get("context_after", []))


def search(
    files: List[str],
    query: Optional[str] = None,
    level: Optional[str] = None,
    thread_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    limit: Optional[int] = None,
    context_lines: int = 3,
    output_format: str = "full",
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
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
        output_format: Output format - "full", "summary", "count", or "compact"
                      - "full": Complete log entries (default)
                      - "summary": Aggregated summary with examples
                      - "count": Just counts, no log content
                      - "compact": Essential fields only (no raw logs)

    Returns:
        Dictionary with search results (format depends on output_format):

        For "full":
        {
            "results": [...],  # Full entries
            "total_matches": 123,
            "search_time_ms": 45
        }

        For "summary":
        {
            "total_matches": 123,
            "unique_messages": 15,
            "log_levels": {"ERROR": 100, "WARN": 23},
            "top_messages": [
                {"message": "...", "count": 50, "first_seen": "...", "last_seen": "..."},
                ...
            ],
            "sample_entries": [...]  # 3-5 examples
        }

        For "count":
        {
            "total_matches": 123,
            "by_level": {"ERROR": 100, "WARN": 23},
            "by_file": {"app.log": 80, "api.log": 43},
            "time_range": {"start": "...", "end": "..."}
        }

        For "compact":
        {
            "matches": [
                {"time": "...", "level": "ERROR", "msg": "...", "thread": "..."},
                ...
            ],
            "total": 123
        }
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    investigator = logler_rs.PyInvestigator()
    _load_files_with_config(investigator, files, parser_format, custom_regex)

    # Build query
    filters = {"levels": []}
    if level:
        level_map = {
            "trace": "Trace",
            "debug": "Debug",
            "info": "Info",
            "warn": "Warn",
            "warning": "Warn",
            "error": "Error",
            "fatal": "Fatal",
            "critical": "Fatal",
        }
        normalized_level = level_map.get(level.lower())
        if not normalized_level:
            raise ValueError(f"Unknown log level: {level}")
        filters["levels"] = [normalized_level]
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

    # Call Rust engine with the full query payload
    result_json = investigator.search(json.dumps(query_dict))
    result = json.loads(result_json)
    _normalize_search_result_levels(result)
    _apply_custom_regex_to_results(result, custom_regex)

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


def follow_thread(
    files: List[str],
    thread_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
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
    result = json.loads(result_json)
    _normalize_context_payload(result)
    return result


def follow_thread_hierarchy(
    files: List[str],
    root_identifier: str,
    max_depth: Optional[int] = None,
    use_naming_patterns: bool = True,
    use_temporal_inference: bool = True,
    min_confidence: float = 0.0,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build hierarchical tree of threads/spans showing parent-child relationships.

    This detects sub-threads and nested operations using:
    - Explicit parent_span_id fields (OpenTelemetry)
    - Naming patterns (worker-1.task-a, main:subtask-1)
    - Temporal inference (time-based proximity)

    Args:
        files: List of log file paths
        root_identifier: Root thread ID, correlation ID, or span ID
        max_depth: Maximum depth of hierarchy tree (default: unlimited)
        use_naming_patterns: Enable naming pattern detection (default: True)
        use_temporal_inference: Enable time-based inference (default: True)
        min_confidence: Minimum confidence score (0.0-1.0, default: 0.0)
        parser_format: Optional log format hint
        custom_regex: Optional custom parsing regex

    Returns:
        Dictionary with hierarchical structure:
        {
            "roots": [
                {
                    "id": "main-thread",
                    "node_type": "Thread" | "Span" | "CorrelationGroup",
                    "name": "Main Request Handler",
                    "parent_id": null,
                    "children": [
                        {
                            "id": "worker-1.db-query",
                            "node_type": "Span",
                            "name": "Database Query",
                            "parent_id": "main-thread",
                            "children": [],
                            "entry_ids": [...],
                            "start_time": "2024-01-15T10:00:00Z",
                            "end_time": "2024-01-15T10:00:02Z",
                            "duration_ms": 2000,
                            "entry_count": 15,
                            "error_count": 0,
                            "level_counts": {"INFO": 12, "DEBUG": 3},
                            "depth": 1,
                            "confidence": 0.8,
                            "relationship_evidence": ["Naming pattern: worker-1.db-query"]
                        }
                    ],
                    "entry_ids": [...],
                    "start_time": "2024-01-15T10:00:00Z",
                    "end_time": "2024-01-15T10:00:05Z",
                    "duration_ms": 5000,
                    "entry_count": 42,
                    "error_count": 2,
                    "level_counts": {"INFO": 35, "ERROR": 2, "DEBUG": 5},
                    "depth": 0,
                    "confidence": 1.0,
                    "relationship_evidence": []
                }
            ],
            "total_nodes": 8,
            "max_depth": 3,
            "total_duration_ms": 5000,
            "concurrent_count": 2,
            "bottleneck": {
                "node_id": "worker-1.db-query",
                "duration_ms": 2000,
                "percentage": 40.0,
                "depth": 1
            },
            "error_nodes": ["worker-2.api-call"],
            "detection_method": "ExplicitParentId" | "NamingPattern" | "TemporalInference" | "Mixed"
        }

    Example:
        # Detect OpenTelemetry trace hierarchy
        hierarchy = follow_thread_hierarchy(
            files=["app.log"],
            root_identifier="trace-abc123",
            min_confidence=0.8
        )

        # Print tree structure
        for root in hierarchy['roots']:
            print_tree(root, indent=0)

        # Find bottleneck
        if hierarchy['bottleneck']:
            print(f"Bottleneck: {hierarchy['bottleneck']['node_id']} ({hierarchy['bottleneck']['duration_ms']}ms)")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Use Investigator when custom parsing is requested
    if parser_format or custom_regex:
        inv = Investigator()
        inv.load_files(files, parser_format=parser_format, custom_regex=custom_regex)
        return inv.build_hierarchy(
            root_identifier=root_identifier,
            max_depth=max_depth,
            use_naming_patterns=use_naming_patterns,
            use_temporal_inference=use_temporal_inference,
            min_confidence=min_confidence,
        )

    # Call Rust directly for better performance
    result_json = logler_rs.build_hierarchy(
        files,
        root_identifier,
        max_depth,
        use_naming_patterns,
        use_temporal_inference,
        min_confidence,
    )
    return json.loads(result_json)


def get_hierarchy_summary(hierarchy: Dict[str, Any]) -> str:
    """
    Generate a human-readable summary of a thread hierarchy.

    Args:
        hierarchy: Hierarchy dictionary from follow_thread_hierarchy()

    Returns:
        Formatted text summary

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        summary = get_hierarchy_summary(hierarchy)
        print(summary)
    """
    lines = []

    # Overview
    lines.append("=== Thread Hierarchy Summary ===")
    lines.append(f"Total nodes: {hierarchy.get('total_nodes', 0)}")
    lines.append(f"Max depth: {hierarchy.get('max_depth', 0)}")
    lines.append(f"Detection method: {hierarchy.get('detection_method', 'Unknown')}")

    # Duration
    total_duration = hierarchy.get("total_duration_ms")
    if total_duration:
        lines.append(f"Total duration: {total_duration}ms ({total_duration/1000:.2f}s)")

    # Concurrent operations
    concurrent = hierarchy.get("concurrent_count", 0)
    if concurrent > 1:
        lines.append(f"Concurrent operations: {concurrent}")

    # Bottleneck
    bottleneck = hierarchy.get("bottleneck")
    if bottleneck:
        lines.append("")
        lines.append("⚠️  BOTTLENECK DETECTED:")
        lines.append(f"  Node: {bottleneck.get('node_id')}")
        lines.append(
            f"  Duration: {bottleneck.get('duration_ms')}ms ({bottleneck.get('percentage', 0):.1f}% of total)"
        )
        lines.append(f"  Depth: {bottleneck.get('depth')}")

    # Errors
    error_nodes = hierarchy.get("error_nodes", [])
    if error_nodes:
        lines.append("")
        lines.append(f"❌ Errors in {len(error_nodes)} node(s):")
        for node_id in error_nodes[:5]:  # Show first 5
            lines.append(f"  - {node_id}")
        if len(error_nodes) > 5:
            lines.append(f"  ... and {len(error_nodes) - 5} more")

    # Tree structure preview
    roots = hierarchy.get("roots", [])
    if roots:
        lines.append("")
        lines.append("Tree Structure:")
        for root in roots[:3]:  # Show first 3 roots
            lines.append(
                f"  📁 {root.get('id')} ({root.get('entry_count', 0)} entries, {len(root.get('children', []))} children)"
            )
            _append_tree_preview(root, lines, depth=1, max_depth=2)
        if len(roots) > 3:
            lines.append(f"  ... and {len(roots) - 3} more root(s)")

    return "\n".join(lines)


def _append_tree_preview(node: Dict[str, Any], lines: List[str], depth: int, max_depth: int):
    """Helper to append tree preview to lines"""
    if depth >= max_depth:
        return

    children = node.get("children", [])
    for i, child in enumerate(children[:3]):  # Show first 3 children
        is_last = i == len(children) - 1
        prefix = "  " * depth + ("└─ " if is_last else "├─ ")

        error_marker = "❌ " if child.get("error_count", 0) > 0 else ""
        duration = child.get("duration_ms", 0)
        duration_str = f" ({duration}ms)" if duration > 0 else ""

        lines.append(
            f"{prefix}{error_marker}{child.get('id')} ({child.get('entry_count', 0)} entries){duration_str}"
        )
        _append_tree_preview(child, lines, depth + 1, max_depth)

    if len(children) > 3:
        prefix = "  " * depth + "└─ "
        lines.append(f"{prefix}... and {len(children) - 3} more")


def analyze_error_flow(
    hierarchy: Dict[str, Any],
    include_context: bool = True,
) -> Dict[str, Any]:
    """
    Analyze error propagation through a hierarchy to identify root causes and cascading failures.

    This function traces errors through parent-child relationships to find:
    - Root cause: The first/originating error in the chain
    - Propagation chain: How errors cascaded through the system
    - Affected nodes: All nodes impacted by the error
    - Impact assessment: Severity and scope of the failure

    Args:
        hierarchy: Hierarchy dictionary from follow_thread_hierarchy()
        include_context: Include sample error messages (default: True)

    Returns:
        Dictionary with error flow analysis:
        {
            "has_errors": bool,
            "total_error_nodes": int,
            "root_causes": [
                {
                    "node_id": "redis-write",
                    "node_type": "Span",
                    "error_count": 1,
                    "depth": 3,
                    "timestamp": "2024-01-15T10:00:01.020Z",
                    "path": ["api-gateway", "product-service", "cache-update", "redis-write"],
                    "is_leaf": True,
                    "confidence": 0.95
                }
            ],
            "propagation_chains": [
                {
                    "root_cause": "redis-write",
                    "chain": [
                        {"node_id": "redis-write", "error_count": 1, "depth": 3},
                        {"node_id": "cache-update", "error_count": 1, "depth": 2},
                        {"node_id": "product-service", "error_count": 1, "depth": 1}
                    ],
                    "total_affected": 3,
                    "propagation_type": "upward"  # errors bubbled up to parent
                }
            ],
            "impact_summary": {
                "total_affected_nodes": 5,
                "affected_percentage": 35.7,
                "max_propagation_depth": 3,
                "concurrent_failures": 2
            },
            "recommendations": [
                "Investigate redis-write first - it appears to be the root cause",
                "Consider adding retry logic for cache operations",
                "3 nodes show cascading failures from a single source"
            ]
        }

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        error_analysis = analyze_error_flow(hierarchy)

        if error_analysis['has_errors']:
            print(f"Root cause: {error_analysis['root_causes'][0]['node_id']}")
            for rec in error_analysis['recommendations']:
                print(f"  - {rec}")
    """
    result = {
        "has_errors": False,
        "total_error_nodes": 0,
        "root_causes": [],
        "propagation_chains": [],
        "impact_summary": {
            "total_affected_nodes": 0,
            "affected_percentage": 0.0,
            "max_propagation_depth": 0,
            "concurrent_failures": 0,
        },
        "recommendations": [],
    }

    error_nodes = hierarchy.get("error_nodes", [])
    if not error_nodes:
        return result

    result["has_errors"] = True
    result["total_error_nodes"] = len(error_nodes)

    # Build node lookup and parent mapping
    all_nodes = {}
    parent_map = {}  # child_id -> parent_id

    def collect_nodes(node: Dict[str, Any], parent_id: Optional[str] = None):
        node_id = node.get("id")
        if node_id:
            all_nodes[node_id] = node
            if parent_id:
                parent_map[node_id] = parent_id
        for child in node.get("children", []):
            collect_nodes(child, node_id)

    for root in hierarchy.get("roots", []):
        collect_nodes(root)

    # Find root causes (errors at leaf nodes or deepest error in each chain)
    error_node_data = []
    for node_id in error_nodes:
        node = all_nodes.get(node_id)
        if node:
            error_node_data.append(
                {
                    "node_id": node_id,
                    "node_type": node.get("node_type", "Unknown"),
                    "error_count": node.get("error_count", 0),
                    "depth": node.get("depth", 0),
                    "timestamp": node.get("start_time"),
                    "is_leaf": len(node.get("children", [])) == 0,
                    "children_with_errors": sum(
                        1 for c in node.get("children", []) if c.get("error_count", 0) > 0
                    ),
                }
            )

    # Sort by depth (deepest first) and timestamp (earliest first)
    error_node_data.sort(key=lambda x: (-x["depth"], x["timestamp"] or ""))

    # Identify root causes - errors that didn't come from children
    root_causes = []

    for error_node in error_node_data:
        node_id = error_node["node_id"]

        # Build path from root to this node
        path = []
        current = node_id
        while current:
            path.insert(0, current)
            current = parent_map.get(current)

        # Check if this is a root cause (no child errors, or leaf node)
        if error_node["children_with_errors"] == 0:
            # Calculate confidence based on evidence
            confidence = 1.0 if error_node["is_leaf"] else 0.85

            root_causes.append(
                {
                    "node_id": node_id,
                    "node_type": error_node["node_type"],
                    "error_count": error_node["error_count"],
                    "depth": error_node["depth"],
                    "timestamp": error_node["timestamp"],
                    "path": path,
                    "is_leaf": error_node["is_leaf"],
                    "confidence": confidence,
                }
            )

    result["root_causes"] = root_causes

    # Build propagation chains (trace errors upward from root causes)
    propagation_chains = []

    for root_cause in root_causes:
        chain = []
        current_id = root_cause["node_id"]

        # Walk up the tree
        while current_id:
            node = all_nodes.get(current_id)
            if node:
                chain.append(
                    {
                        "node_id": current_id,
                        "error_count": node.get("error_count", 0),
                        "depth": node.get("depth", 0),
                    }
                )
            current_id = parent_map.get(current_id)

        # Only include chains where errors actually propagated
        if len(chain) > 1:
            # Check if parent nodes also have errors
            propagated_chain = [c for c in chain if c["error_count"] > 0]
            if len(propagated_chain) > 1:
                propagation_chains.append(
                    {
                        "root_cause": root_cause["node_id"],
                        "chain": propagated_chain,
                        "total_affected": len(propagated_chain),
                        "propagation_type": "upward",
                    }
                )

    result["propagation_chains"] = propagation_chains

    # Calculate impact summary
    total_nodes = hierarchy.get("total_nodes", 1)
    affected_nodes = len(set(error_nodes))
    max_depth = max((rc["depth"] for rc in root_causes), default=0)

    # Count concurrent failures (root causes at same depth)
    depth_counts = defaultdict(int)
    for rc in root_causes:
        depth_counts[rc["depth"]] += 1
    concurrent = max(depth_counts.values(), default=0)

    result["impact_summary"] = {
        "total_affected_nodes": affected_nodes,
        "affected_percentage": (affected_nodes / total_nodes * 100) if total_nodes > 0 else 0,
        "max_propagation_depth": max_depth,
        "concurrent_failures": concurrent if concurrent > 1 else 0,
    }

    # Generate recommendations
    recommendations = []

    if root_causes:
        primary_cause = root_causes[0]
        recommendations.append(
            f"Investigate {primary_cause['node_id']} first - it appears to be the root cause"
        )

        if primary_cause["is_leaf"]:
            recommendations.append(
                f"Error originated at leaf node (depth {primary_cause['depth']}) - check external dependencies"
            )

    if len(propagation_chains) > 0:
        total_propagated = sum(c["total_affected"] for c in propagation_chains)
        recommendations.append(
            f"{total_propagated} nodes show cascading failures - consider adding circuit breakers"
        )

    if concurrent > 1:
        recommendations.append(
            f"{concurrent} concurrent failures detected - possible systemic issue"
        )

    if result["impact_summary"]["affected_percentage"] > 50:
        recommendations.append(
            "High impact failure (>50% of nodes affected) - prioritize investigation"
        )

    result["recommendations"] = recommendations

    return result


def format_error_flow(
    error_analysis: Dict[str, Any],
    show_chains: bool = True,
    show_recommendations: bool = True,
) -> str:
    """
    Format error flow analysis as human-readable text.

    Args:
        error_analysis: Error analysis from analyze_error_flow()
        show_chains: Show propagation chains (default: True)
        show_recommendations: Show recommendations (default: True)

    Returns:
        Formatted error flow string

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        error_analysis = analyze_error_flow(hierarchy)
        print(format_error_flow(error_analysis))
    """
    lines = []

    if not error_analysis.get("has_errors"):
        return "✅ No errors detected in hierarchy"

    # Header
    lines.append("=" * 70)
    lines.append("🔍 ERROR FLOW ANALYSIS")
    lines.append("=" * 70)
    lines.append("")

    # Summary
    total = error_analysis.get("total_error_nodes", 0)
    impact = error_analysis.get("impact_summary", {})
    lines.append(f"Total error nodes: {total}")
    lines.append(f"Affected: {impact.get('affected_percentage', 0):.1f}% of hierarchy")

    if impact.get("concurrent_failures", 0) > 1:
        lines.append(f"Concurrent failures: {impact['concurrent_failures']}")

    lines.append("")

    # Root Causes
    root_causes = error_analysis.get("root_causes", [])
    if root_causes:
        lines.append("-" * 70)
        lines.append("🔴 ROOT CAUSE(S)")
        lines.append("-" * 70)

        for i, cause in enumerate(root_causes, 1):
            confidence_pct = int(cause.get("confidence", 0) * 100)
            leaf_marker = " (leaf node)" if cause.get("is_leaf") else ""

            lines.append(f"\n  {i}. {cause['node_id']}{leaf_marker}")
            lines.append(f"     Type: {cause.get('node_type', 'Unknown')}")
            lines.append(f"     Errors: {cause.get('error_count', 0)}")
            lines.append(f"     Depth: {cause.get('depth', 0)}")
            lines.append(f"     Confidence: {confidence_pct}%")

            if cause.get("timestamp"):
                lines.append(f"     Time: {cause['timestamp']}")

            if cause.get("path"):
                path_str = " → ".join(cause["path"])
                lines.append(f"     Path: {path_str}")

    # Propagation Chains
    if show_chains:
        chains = error_analysis.get("propagation_chains", [])
        if chains:
            lines.append("")
            lines.append("-" * 70)
            lines.append("📈 ERROR PROPAGATION")
            lines.append("-" * 70)

            for chain_data in chains:
                lines.append(f"\n  From: {chain_data['root_cause']}")
                lines.append(f"  Affected nodes: {chain_data['total_affected']}")
                lines.append("  Chain:")

                chain = chain_data.get("chain", [])
                for j, node in enumerate(chain):
                    is_last = j == len(chain) - 1
                    prefix = "     └─" if is_last else "     ├─"
                    arrow = " ← ROOT CAUSE" if j == 0 else ""
                    lines.append(
                        f"{prefix} {node['node_id']} ({node['error_count']} errors){arrow}"
                    )

    # Recommendations
    if show_recommendations:
        recommendations = error_analysis.get("recommendations", [])
        if recommendations:
            lines.append("")
            lines.append("-" * 70)
            lines.append("💡 RECOMMENDATIONS")
            lines.append("-" * 70)

            for rec in recommendations:
                lines.append(f"  • {rec}")

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def detect_correlation_chains(
    files: List[str],
    root_correlation_id: Optional[str] = None,
    chain_patterns: Optional[List[str]] = None,
    parser_format: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Detect correlation ID chaining where one request spawns sub-requests.

    This function identifies parent-child relationships between correlation IDs
    by analyzing log messages for patterns like:
    - "spawning request {child_id}"
    - "child_correlation_id": "xxx"
    - "parent_request_id": "xxx"

    Args:
        files: List of log file paths to analyze
        root_correlation_id: Optional root correlation ID to start from
        chain_patterns: Optional custom regex patterns for detecting chains
        parser_format: Optional log format hint

    Returns:
        Dictionary with correlation chain information:
        {
            "chains": [
                {
                    "parent_correlation_id": "req-123",
                    "child_correlation_id": "subreq-456",
                    "evidence": "Spawning sub-request subreq-456",
                    "timestamp": "2024-01-15T10:00:00Z",
                    "confidence": 0.9
                }
            ],
            "root_ids": ["req-123"],
            "hierarchy": {
                "req-123": ["subreq-456", "subreq-789"],
                "subreq-456": ["subreq-456-a"]
            },
            "total_chains": 3
        }

    Example:
        chains = detect_correlation_chains(
            files=["app.log", "service.log"],
            root_correlation_id="req-main-001"
        )
        for chain in chains['chains']:
            print(f"{chain['parent_correlation_id']} -> {chain['child_correlation_id']}")
    """
    # Default patterns to detect correlation chaining
    default_patterns = [
        # Explicit field patterns
        r'child_correlation_id["\s:=]+([a-zA-Z0-9_-]+)',
        r'parent_correlation_id["\s:=]+([a-zA-Z0-9_-]+)',
        r'parent_request_id["\s:=]+([a-zA-Z0-9_-]+)',
        r'spawned_request["\s:=]+([a-zA-Z0-9_-]+)',
        # Message patterns
        r"[Ss]pawning (?:sub-?)?request[:\s]+([a-zA-Z0-9_-]+)",
        r"[Cc]reating child request[:\s]+([a-zA-Z0-9_-]+)",
        r"[Ff]orked to[:\s]+([a-zA-Z0-9_-]+)",
        r"[Dd]elegating to[:\s]+([a-zA-Z0-9_-]+)",
        r"[Ss]ub-?request[:\s]+([a-zA-Z0-9_-]+)",
    ]

    patterns = chain_patterns or default_patterns
    compiled_patterns = [re.compile(p) for p in patterns]

    # Read and parse logs
    entries = []
    if RUST_AVAILABLE:
        for file_path in files:
            result_json = logler_rs.search(
                [file_path],
                "",  # No query filter
                None,  # level
                None,  # thread_id
                None,  # correlation_id
                None,  # trace_id
                None,  # start_time
                None,  # end_time
                10000,  # limit - get many entries
                0,  # offset
            )
            result = json.loads(result_json)
            entries.extend(result.get("entries", []))
    else:
        # Fallback to Python parsing
        from .parser import LogParser

        parser = LogParser()
        for file_path in files:
            with open(file_path, "r") as f:
                for line in f:
                    entry = parser.parse_line(line)
                    if entry:
                        entries.append(entry.__dict__ if hasattr(entry, "__dict__") else entry)

    # Detect chains
    chains = []
    hierarchy = defaultdict(list)
    all_correlation_ids = set()

    for entry in entries:
        correlation_id = entry.get("correlation_id")
        message = entry.get("message", "")
        timestamp = entry.get("timestamp")
        fields = entry.get("fields", {})

        if correlation_id:
            all_correlation_ids.add(correlation_id)

        # Check explicit fields first
        child_id = fields.get("child_correlation_id") or fields.get("spawned_request")
        parent_id = fields.get("parent_correlation_id") or fields.get("parent_request_id")

        if child_id and correlation_id:
            chains.append(
                {
                    "parent_correlation_id": correlation_id,
                    "child_correlation_id": child_id,
                    "evidence": f"Explicit field: child_correlation_id={child_id}",
                    "timestamp": timestamp,
                    "confidence": 1.0,
                }
            )
            hierarchy[correlation_id].append(child_id)
            all_correlation_ids.add(child_id)

        if parent_id and correlation_id:
            chains.append(
                {
                    "parent_correlation_id": parent_id,
                    "child_correlation_id": correlation_id,
                    "evidence": f"Explicit field: parent_correlation_id={parent_id}",
                    "timestamp": timestamp,
                    "confidence": 1.0,
                }
            )
            hierarchy[parent_id].append(correlation_id)
            all_correlation_ids.add(parent_id)

        # Check message patterns
        for pattern in compiled_patterns:
            match = pattern.search(message)
            if match and correlation_id:
                detected_id = match.group(1)
                if detected_id != correlation_id:
                    # Determine if it's a parent or child reference
                    if "parent" in pattern.pattern.lower():
                        chains.append(
                            {
                                "parent_correlation_id": detected_id,
                                "child_correlation_id": correlation_id,
                                "evidence": f"Pattern match in message: {match.group(0)}",
                                "timestamp": timestamp,
                                "confidence": 0.85,
                            }
                        )
                        hierarchy[detected_id].append(correlation_id)
                    else:
                        chains.append(
                            {
                                "parent_correlation_id": correlation_id,
                                "child_correlation_id": detected_id,
                                "evidence": f"Pattern match in message: {match.group(0)}",
                                "timestamp": timestamp,
                                "confidence": 0.85,
                            }
                        )
                        hierarchy[correlation_id].append(detected_id)
                    all_correlation_ids.add(detected_id)

    # Deduplicate chains
    seen = set()
    unique_chains = []
    for chain in chains:
        key = (chain["parent_correlation_id"], chain["child_correlation_id"])
        if key not in seen:
            seen.add(key)
            unique_chains.append(chain)

    # Find root IDs (correlation IDs that are never a child)
    all_children = set()
    for children in hierarchy.values():
        all_children.update(children)

    root_ids = [cid for cid in all_correlation_ids if cid not in all_children]

    # Filter by root_correlation_id if specified
    if root_correlation_id:
        # Build the tree from root
        def get_descendants(cid: str, seen: set) -> set:
            if cid in seen:
                return set()
            seen.add(cid)
            result = {cid}
            for child in hierarchy.get(cid, []):
                result.update(get_descendants(child, seen))
            return result

        relevant_ids = get_descendants(root_correlation_id, set())
        unique_chains = [
            c
            for c in unique_chains
            if c["parent_correlation_id"] in relevant_ids
            or c["child_correlation_id"] in relevant_ids
        ]
        root_ids = [root_correlation_id] if root_correlation_id in root_ids else []

    # Convert hierarchy to regular dict
    hierarchy_dict = {k: list(set(v)) for k, v in hierarchy.items()}

    return {
        "chains": unique_chains,
        "root_ids": sorted(root_ids),
        "hierarchy": hierarchy_dict,
        "total_chains": len(unique_chains),
        "total_correlation_ids": len(all_correlation_ids),
    }


def build_hierarchy_with_correlation_chains(
    files: List[str],
    root_identifier: str,
    include_correlation_chains: bool = True,
    max_depth: Optional[int] = None,
    use_naming_patterns: bool = True,
    use_temporal_inference: bool = True,
    min_confidence: float = 0.0,
) -> Dict[str, Any]:
    """
    Build hierarchy that includes correlation ID chaining relationships.

    This extends follow_thread_hierarchy by also detecting when one correlation ID
    spawns sub-requests with different correlation IDs.

    Args:
        files: List of log file paths
        root_identifier: Root correlation ID, thread ID, or span ID
        include_correlation_chains: Whether to detect correlation chaining (default: True)
        max_depth: Maximum hierarchy depth
        use_naming_patterns: Enable naming pattern detection
        use_temporal_inference: Enable temporal inference
        min_confidence: Minimum confidence score

    Returns:
        Hierarchy dictionary with additional correlation chain information

    Example:
        hierarchy = build_hierarchy_with_correlation_chains(
            files=["api.log", "worker.log"],
            root_identifier="req-main-001",
            include_correlation_chains=True
        )
        # hierarchy now includes sub-requests spawned by req-main-001
    """
    # First build the regular hierarchy
    hierarchy = follow_thread_hierarchy(
        files=files,
        root_identifier=root_identifier,
        max_depth=max_depth,
        use_naming_patterns=use_naming_patterns,
        use_temporal_inference=use_temporal_inference,
        min_confidence=min_confidence,
    )

    if not include_correlation_chains:
        return hierarchy

    # Detect correlation chains
    chains = detect_correlation_chains(files=files, root_correlation_id=root_identifier)

    # Add chain information to hierarchy
    hierarchy["correlation_chains"] = chains["chains"]
    hierarchy["chained_correlation_ids"] = list(chains["hierarchy"].keys())

    # If there are chained correlation IDs, we could optionally merge their hierarchies
    # For now, just add metadata about them
    if chains["total_chains"] > 0:
        hierarchy["has_correlation_chains"] = True
        hierarchy["correlation_chain_count"] = chains["total_chains"]

        # Add note about additional correlation IDs that could be explored
        child_ids = set()
        for chain in chains["chains"]:
            child_ids.add(chain["child_correlation_id"])

        hierarchy["related_correlation_ids"] = sorted(child_ids)

    return hierarchy


def analyze_bottlenecks(
    hierarchy: Dict[str, Any],
    threshold_percentage: float = 20.0,
) -> Dict[str, Any]:
    """
    AI-powered bottleneck detection with optimization suggestions.

    Analyzes hierarchy to identify:
    - Primary bottleneck (longest duration)
    - Secondary bottlenecks
    - Potential parallelization opportunities
    - Caching opportunities
    - Circuit breaker recommendations

    Args:
        hierarchy: Hierarchy from follow_thread_hierarchy()
        threshold_percentage: Minimum % of total time to be considered significant

    Returns:
        Dictionary with bottleneck analysis:
        {
            "primary_bottleneck": {...},
            "secondary_bottlenecks": [...],
            "optimization_suggestions": [...],
            "parallelization_opportunities": [...],
            "estimated_improvement_ms": float
        }

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        analysis = analyze_bottlenecks(hierarchy)
        for suggestion in analysis['optimization_suggestions']:
            print(f"  - {suggestion}")
    """
    result = {
        "primary_bottleneck": None,
        "secondary_bottlenecks": [],
        "optimization_suggestions": [],
        "parallelization_opportunities": [],
        "caching_opportunities": [],
        "estimated_improvement_ms": 0,
    }

    total_duration = hierarchy.get("total_duration_ms", 0)
    if total_duration <= 0:
        return result

    bottleneck = hierarchy.get("bottleneck")
    if bottleneck:
        result["primary_bottleneck"] = bottleneck

    # Collect all nodes with timing
    all_nodes = []

    def collect_nodes(node: Dict[str, Any]):
        duration = node.get("duration_ms", 0)
        if duration and duration > 0:
            percentage = (duration / total_duration) * 100
            all_nodes.append(
                {
                    "id": node.get("id"),
                    "duration_ms": duration,
                    "percentage": percentage,
                    "depth": node.get("depth", 0),
                    "children_count": len(node.get("children", [])),
                    "is_leaf": len(node.get("children", [])) == 0,
                    "error_count": node.get("error_count", 0),
                }
            )
        for child in node.get("children", []):
            collect_nodes(child)

    for root in hierarchy.get("roots", []):
        collect_nodes(root)

    # Sort by duration
    all_nodes.sort(key=lambda x: -x["duration_ms"])

    # Find secondary bottlenecks
    for node in all_nodes[1:5]:  # Top 5 excluding primary
        if node["percentage"] >= threshold_percentage:
            result["secondary_bottlenecks"].append(node)

    # Generate optimization suggestions
    suggestions = []

    # Check for parallelization opportunities
    # Look for siblings at same depth with no dependencies
    depth_groups = defaultdict(list)
    for node in all_nodes:
        depth_groups[node["depth"]].append(node)

    for depth, nodes in depth_groups.items():
        if len(nodes) >= 2:
            total_sibling_time = sum(n["duration_ms"] for n in nodes)
            max_sibling_time = max(n["duration_ms"] for n in nodes)
            savings = total_sibling_time - max_sibling_time

            if savings > total_duration * 0.1:  # >10% potential savings
                sibling_names = [n["id"] for n in nodes[:3]]
                result["parallelization_opportunities"].append(
                    {
                        "depth": depth,
                        "nodes": sibling_names,
                        "potential_savings_ms": savings,
                    }
                )
                suggestions.append(
                    f"Parallelize operations at depth {depth} ({', '.join(sibling_names[:2])}) - "
                    f"potential savings: {savings:.0f}ms"
                )

    # Check for caching opportunities (repeated patterns)
    leaf_nodes = [n for n in all_nodes if n["is_leaf"]]
    if len(leaf_nodes) > 3:
        avg_leaf_time = sum(n["duration_ms"] for n in leaf_nodes) / len(leaf_nodes)
        slow_leaves = [n for n in leaf_nodes if n["duration_ms"] > avg_leaf_time * 2]
        if slow_leaves:
            suggestions.append(
                f"Consider caching for slow leaf operations: {', '.join(n['id'] for n in slow_leaves[:3])}"
            )
            result["caching_opportunities"] = [n["id"] for n in slow_leaves[:3]]

    # Primary bottleneck specific suggestions
    if bottleneck:
        percentage = bottleneck.get("percentage", 0)
        if percentage > 50:
            suggestions.append(
                f"CRITICAL: {bottleneck['node_id']} takes {percentage:.0f}% of total time - prioritize optimization"
            )
        elif percentage > 30:
            suggestions.append(
                f"IMPORTANT: Consider optimizing {bottleneck['node_id']} ({percentage:.0f}% of time)"
            )

        if bottleneck.get("depth", 0) > 2:
            suggestions.append(
                f"Bottleneck is deep in call stack (depth {bottleneck['depth']}) - consider moving to async"
            )

    # Check for error-prone bottlenecks
    error_nodes = [n for n in all_nodes if n["error_count"] > 0 and n["percentage"] > 10]
    for node in error_nodes:
        suggestions.append(
            f"Add circuit breaker for {node['id']} - errors detected and {node['percentage']:.0f}% of time"
        )

    result["optimization_suggestions"] = suggestions

    # Estimate potential improvement
    if result["parallelization_opportunities"]:
        result["estimated_improvement_ms"] = sum(
            p["potential_savings_ms"] for p in result["parallelization_opportunities"]
        )

    return result


def diff_hierarchies(
    hierarchy_a: Dict[str, Any],
    hierarchy_b: Dict[str, Any],
    label_a: str = "Before",
    label_b: str = "After",
) -> Dict[str, Any]:
    """
    Compare two hierarchies to identify performance changes.

    Useful for before/after deployment comparisons, A/B testing,
    or debugging performance regressions.

    Args:
        hierarchy_a: First hierarchy (baseline)
        hierarchy_b: Second hierarchy (comparison)
        label_a: Label for first hierarchy
        label_b: Label for second hierarchy

    Returns:
        Dictionary with comparison results:
        {
            "summary": {
                "total_duration_change_ms": float,
                "total_duration_change_pct": float,
                "node_count_change": int,
                "new_errors": int,
                "resolved_errors": int
            },
            "improved_nodes": [...],
            "degraded_nodes": [...],
            "new_nodes": [...],
            "removed_nodes": [...],
            "error_changes": {...}
        }

    Example:
        before = follow_thread_hierarchy(files=["before.log"], root_identifier="req-123")
        after = follow_thread_hierarchy(files=["after.log"], root_identifier="req-123")
        diff = diff_hierarchies(before, after)
        print(f"Performance change: {diff['summary']['total_duration_change_pct']:.1f}%")
    """
    result = {
        "label_a": label_a,
        "label_b": label_b,
        "summary": {
            "total_duration_change_ms": 0,
            "total_duration_change_pct": 0,
            "node_count_change": 0,
            "new_errors": 0,
            "resolved_errors": 0,
        },
        "improved_nodes": [],
        "degraded_nodes": [],
        "new_nodes": [],
        "removed_nodes": [],
        "error_changes": {
            "new_errors": [],
            "resolved_errors": [],
        },
    }

    # Collect nodes from both hierarchies
    def collect_nodes(hierarchy: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        nodes = {}

        def walk(node: Dict[str, Any]):
            node_id = node.get("id")
            if node_id:
                nodes[node_id] = {
                    "duration_ms": node.get("duration_ms", 0),
                    "error_count": node.get("error_count", 0),
                    "entry_count": node.get("entry_count", 0),
                }
            for child in node.get("children", []):
                walk(child)

        for root in hierarchy.get("roots", []):
            walk(root)

        return nodes

    nodes_a = collect_nodes(hierarchy_a)
    nodes_b = collect_nodes(hierarchy_b)

    # Duration changes
    duration_a = hierarchy_a.get("total_duration_ms", 0)
    duration_b = hierarchy_b.get("total_duration_ms", 0)

    result["summary"]["total_duration_change_ms"] = duration_b - duration_a
    if duration_a > 0:
        result["summary"]["total_duration_change_pct"] = (
            (duration_b - duration_a) / duration_a * 100
        )

    # Node count changes
    result["summary"]["node_count_change"] = len(nodes_b) - len(nodes_a)

    # Compare individual nodes
    all_node_ids = set(nodes_a.keys()) | set(nodes_b.keys())

    for node_id in all_node_ids:
        in_a = node_id in nodes_a
        in_b = node_id in nodes_b

        if in_a and not in_b:
            result["removed_nodes"].append(
                {
                    "id": node_id,
                    "duration_ms": nodes_a[node_id]["duration_ms"],
                }
            )
        elif in_b and not in_a:
            result["new_nodes"].append(
                {
                    "id": node_id,
                    "duration_ms": nodes_b[node_id]["duration_ms"],
                }
            )
        else:
            # Both exist - compare
            dur_a = nodes_a[node_id]["duration_ms"]
            dur_b = nodes_b[node_id]["duration_ms"]
            change_ms = dur_b - dur_a
            change_pct = ((dur_b - dur_a) / dur_a * 100) if dur_a > 0 else 0

            if change_ms < -10:  # >10ms improvement
                result["improved_nodes"].append(
                    {
                        "id": node_id,
                        "before_ms": dur_a,
                        "after_ms": dur_b,
                        "change_ms": change_ms,
                        "change_pct": change_pct,
                    }
                )
            elif change_ms > 10:  # >10ms degradation
                result["degraded_nodes"].append(
                    {
                        "id": node_id,
                        "before_ms": dur_a,
                        "after_ms": dur_b,
                        "change_ms": change_ms,
                        "change_pct": change_pct,
                    }
                )

            # Error changes
            err_a = nodes_a[node_id]["error_count"]
            err_b = nodes_b[node_id]["error_count"]

            if err_a == 0 and err_b > 0:
                result["error_changes"]["new_errors"].append(node_id)
                result["summary"]["new_errors"] += 1
            elif err_a > 0 and err_b == 0:
                result["error_changes"]["resolved_errors"].append(node_id)
                result["summary"]["resolved_errors"] += 1

    # Sort by impact
    result["improved_nodes"].sort(key=lambda x: x["change_ms"])
    result["degraded_nodes"].sort(key=lambda x: -x["change_ms"])

    return result


def format_hierarchy_diff(diff: Dict[str, Any]) -> str:
    """
    Format hierarchy diff as human-readable text.

    Args:
        diff: Diff from diff_hierarchies()

    Returns:
        Formatted diff string
    """
    lines = []

    lines.append("=" * 70)
    lines.append("📊 HIERARCHY COMPARISON")
    lines.append(f"   {diff['label_a']} vs {diff['label_b']}")
    lines.append("=" * 70)

    summary = diff["summary"]
    change_ms = summary["total_duration_change_ms"]
    change_pct = summary["total_duration_change_pct"]

    direction = "⬇️ IMPROVED" if change_ms < 0 else "⬆️ DEGRADED" if change_ms > 0 else "➡️ UNCHANGED"
    lines.append(f"\n{direction}: {abs(change_ms):.0f}ms ({abs(change_pct):.1f}%)")

    if summary["new_errors"] > 0:
        lines.append(f"❌ New errors: {summary['new_errors']}")
    if summary["resolved_errors"] > 0:
        lines.append(f"✅ Resolved errors: {summary['resolved_errors']}")

    if diff["improved_nodes"]:
        lines.append("\n" + "-" * 70)
        lines.append("✅ IMPROVED NODES")
        for node in diff["improved_nodes"][:5]:
            lines.append(
                f"  • {node['id']}: {node['before_ms']:.0f}ms → {node['after_ms']:.0f}ms "
                f"({node['change_pct']:.1f}%)"
            )

    if diff["degraded_nodes"]:
        lines.append("\n" + "-" * 70)
        lines.append("⚠️ DEGRADED NODES")
        for node in diff["degraded_nodes"][:5]:
            lines.append(
                f"  • {node['id']}: {node['before_ms']:.0f}ms → {node['after_ms']:.0f}ms "
                f"(+{node['change_pct']:.1f}%)"
            )

    if diff["new_nodes"]:
        lines.append("\n" + "-" * 70)
        lines.append("🆕 NEW NODES")
        for node in diff["new_nodes"][:5]:
            lines.append(f"  • {node['id']}: {node['duration_ms']:.0f}ms")

    if diff["removed_nodes"]:
        lines.append("\n" + "-" * 70)
        lines.append("🗑️ REMOVED NODES")
        for node in diff["removed_nodes"][:5]:
            lines.append(f"  • {node['id']}: was {node['duration_ms']:.0f}ms")

    lines.append("\n" + "=" * 70)

    return "\n".join(lines)


def export_to_jaeger(
    hierarchy: Dict[str, Any],
    service_name: str = "logler-export",
) -> Dict[str, Any]:
    """
    Export hierarchy to Jaeger-compatible format.

    The output follows the Jaeger JSON format and can be imported
    into Jaeger UI for visualization.

    Args:
        hierarchy: Hierarchy from follow_thread_hierarchy()
        service_name: Name of the service for Jaeger

    Returns:
        Dictionary in Jaeger trace format

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        jaeger_trace = export_to_jaeger(hierarchy, service_name="my-service")

        with open("trace.json", "w") as f:
            json.dump(jaeger_trace, f)

        # Import with: jaeger-query --grpc.host-port=localhost:16685
    """
    import uuid
    from datetime import datetime

    trace_id = uuid.uuid4().hex[:32]
    spans = []

    def convert_node(node: Dict[str, Any], parent_span_id: Optional[str] = None):
        span_id = uuid.uuid4().hex[:16]

        # Parse timestamps
        start_time = node.get("start_time")
        if start_time:
            if isinstance(start_time, str):
                try:
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    start_us = int(dt.timestamp() * 1_000_000)
                except Exception:
                    start_us = 0
            else:
                start_us = 0
        else:
            start_us = 0

        duration_us = int((node.get("duration_ms", 0) or 0) * 1000)

        span = {
            "traceID": trace_id,
            "spanID": span_id,
            "operationName": node.get("id", "unknown"),
            "references": [],
            "startTime": start_us,
            "duration": duration_us,
            "tags": [
                {"key": "node_type", "type": "string", "value": node.get("node_type", "unknown")},
                {"key": "entry_count", "type": "int64", "value": node.get("entry_count", 0)},
                {"key": "error_count", "type": "int64", "value": node.get("error_count", 0)},
            ],
            "logs": [],
            "processID": "p1",
            "warnings": [],
        }

        if parent_span_id:
            span["references"].append(
                {
                    "refType": "CHILD_OF",
                    "traceID": trace_id,
                    "spanID": parent_span_id,
                }
            )

        if node.get("error_count", 0) > 0:
            span["tags"].append({"key": "error", "type": "bool", "value": True})

        spans.append(span)

        # Process children
        for child in node.get("children", []):
            convert_node(child, span_id)

    # Convert all roots
    for root in hierarchy.get("roots", []):
        convert_node(root)

    return {
        "data": [
            {
                "traceID": trace_id,
                "spans": spans,
                "processes": {
                    "p1": {
                        "serviceName": service_name,
                        "tags": [
                            {"key": "exported_by", "type": "string", "value": "logler"},
                        ],
                    }
                },
                "warnings": [],
            }
        ]
    }


def export_to_zipkin(
    hierarchy: Dict[str, Any],
    service_name: str = "logler-export",
) -> List[Dict[str, Any]]:
    """
    Export hierarchy to Zipkin-compatible format.

    Args:
        hierarchy: Hierarchy from follow_thread_hierarchy()
        service_name: Name of the service

    Returns:
        List of spans in Zipkin V2 format

    Example:
        hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
        zipkin_spans = export_to_zipkin(hierarchy)

        # POST to Zipkin: curl -X POST http://localhost:9411/api/v2/spans -H 'Content-Type: application/json' -d '@spans.json'
    """
    import uuid
    from datetime import datetime

    trace_id = uuid.uuid4().hex[:32]
    spans = []

    def convert_node(node: Dict[str, Any], parent_id: Optional[str] = None):
        span_id = uuid.uuid4().hex[:16]

        # Parse timestamp
        start_time = node.get("start_time")
        timestamp_us = 0
        if start_time:
            if isinstance(start_time, str):
                try:
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    timestamp_us = int(dt.timestamp() * 1_000_000)
                except Exception:
                    pass

        duration_us = int((node.get("duration_ms", 0) or 0) * 1000)

        span = {
            "traceId": trace_id,
            "id": span_id,
            "name": node.get("id", "unknown"),
            "timestamp": timestamp_us,
            "duration": duration_us,
            "localEndpoint": {
                "serviceName": service_name,
            },
            "tags": {
                "node_type": node.get("node_type", "unknown"),
                "entry_count": str(node.get("entry_count", 0)),
            },
        }

        if parent_id:
            span["parentId"] = parent_id

        if node.get("error_count", 0) > 0:
            span["tags"]["error"] = "true"

        spans.append(span)

        for child in node.get("children", []):
            convert_node(child, span_id)

    for root in hierarchy.get("roots", []):
        convert_node(root)

    return spans


def find_patterns(
    files: List[str],
    min_occurrences: int = 3,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
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
        self._custom_regex = None

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
        filters = {"levels": []}
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
        result = json.loads(result_json)
        _normalize_search_result_levels(result)
        _apply_custom_regex_to_results(result, self._custom_regex)
        return result

    def follow_thread(
        self,
        thread_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Follow thread in loaded files."""
        result_json = self._investigator.follow_thread(
            self._files, thread_id, correlation_id, trace_id
        )
        result = json.loads(result_json)
        _normalize_entries(result.get("entries", []))
        return result

    def find_patterns(self, min_occurrences: int = 3) -> Dict[str, Any]:
        """Find patterns in loaded files."""
        result_json = self._investigator.find_patterns(self._files, min_occurrences)
        result = json.loads(result_json)
        _normalize_pattern_examples(result)
        return result

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
        result_json = self._investigator.get_context(
            file, line_number, lines_before, lines_after, False
        )
        result = json.loads(result_json)
        _normalize_context_payload(result)
        return result

    def sql_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute SQL query on loaded logs (requires 'sql' feature).

        Args:
            query: SQL query string

        Returns:
            List of result rows as dictionaries

        Example:
            results = investigator.sql_query(\"\"\"
                SELECT level, COUNT(*) as count
                FROM logs
                GROUP BY level
                ORDER BY count DESC
            \"\"\")
        """
        if not hasattr(self._investigator, "sql_query"):
            raise RuntimeError("SQL feature not available. Build with --features sql")
        result_json = self._investigator.sql_query(query)
        return json.loads(result_json)

    def sql_tables(self) -> List[str]:
        """Get list of available SQL tables (requires 'sql' feature)."""
        if not hasattr(self._investigator, "sql_tables"):
            raise RuntimeError("SQL feature not available. Build with --features sql")
        return self._investigator.sql_tables()

    def sql_schema(self, table: str) -> List[Dict[str, Any]]:
        """Get schema for a SQL table (requires 'sql' feature)."""
        if not hasattr(self._investigator, "sql_schema"):
            raise RuntimeError("SQL feature not available. Build with --features sql")
        result_json = self._investigator.sql_schema(table)
        return json.loads(result_json)

    def build_hierarchy(
        self,
        root_identifier: str,
        max_depth: Optional[int] = None,
        use_naming_patterns: bool = True,
        use_temporal_inference: bool = True,
        min_confidence: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Build hierarchical tree of threads/spans from loaded files.

        Args:
            root_identifier: Root thread ID, correlation ID, or span ID
            max_depth: Maximum depth of hierarchy tree
            use_naming_patterns: Enable naming pattern detection
            use_temporal_inference: Enable time-based inference
            min_confidence: Minimum confidence score (0.0-1.0)

        Returns:
            Hierarchy dictionary (see follow_thread_hierarchy for structure)

        Example:
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


# Advanced LLM-optimized features


def cross_service_timeline(
    files: Dict[str, List[str]],
    time_window: Optional[Tuple[str, str]] = None,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: Optional[int] = None,
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a unified timeline across multiple services/log files.

    This is perfect for investigating distributed systems where a single
    request flows through multiple services (API Gateway → Auth → Database → Cache).

    Args:
        files: Dictionary mapping service names to log file lists
               e.g., {"api": ["api.log"], "database": ["db.log"], "cache": ["cache.log"]}
        time_window: Optional tuple of (start_time, end_time) in ISO format
        correlation_id: Filter to specific correlation ID
        trace_id: Filter to specific trace ID
        limit: Maximum number of entries to return

    Returns:
        Dictionary with unified timeline:
        {
            "timeline": [
                {
                    "service": "api",
                    "timestamp": "2024-01-01T10:30:15.123Z",
                    "entry": {...},
                    "relative_time_ms": 0
                },
                {
                    "service": "database",
                    "timestamp": "2024-01-01T10:30:15.456Z",
                    "entry": {...},
                    "relative_time_ms": 333
                },
                ...
            ],
            "services": ["api", "database", "cache"],
            "total_entries": 42,
            "duration_ms": 1523,
            "service_breakdown": {
                "api": 15,
                "database": 20,
                "cache": 7
            }
        }

    Example:
        # Investigate a failed request across services
        timeline = cross_service_timeline(
            files={
                "api": ["logs/api.log"],
                "auth": ["logs/auth.log"],
                "db": ["logs/db.log"]
            },
            correlation_id="req-12345"
        )

        # See the flow
        for entry in timeline['timeline']:
            print(f"[{entry['service']:10s}] +{entry['relative_time_ms']:4d}ms: {entry['entry']['message']}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Collect entries from all services
    all_entries = []
    service_counts = defaultdict(int)

    for service_name, service_files in files.items():
        if correlation_id:
            result = follow_thread(service_files, correlation_id=correlation_id, trace_id=trace_id)
            entries = result.get("entries", [])
        elif trace_id:
            result = follow_thread(service_files, trace_id=trace_id)
            entries = result.get("entries", [])
        else:
            # Get all entries
            result = search(
                service_files, limit=None, parser_format=parser_format, custom_regex=custom_regex
            )
            entries = [r["entry"] for r in result.get("results", [])]

        # Add service label to each entry
        for entry in entries:
            # Parse timestamp if present
            timestamp_str = entry.get("timestamp")
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    timestamp = None
            else:
                timestamp = None

            all_entries.append(
                {
                    "service": service_name,
                    "timestamp": timestamp,
                    "timestamp_str": timestamp_str,
                    "entry": entry,
                }
            )
            service_counts[service_name] += 1

    # Filter by time window if specified
    if time_window:
        start_time, end_time = time_window
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            all_entries = [
                e for e in all_entries if e["timestamp"] and start_dt <= e["timestamp"] <= end_dt
            ]
        except Exception as e:
            warnings.warn(f"Could not parse time window: {e}", stacklevel=2)

    # Sort by timestamp
    all_entries.sort(key=lambda e: e["timestamp"] if e["timestamp"] else datetime.min)

    # Calculate relative times
    if all_entries and all_entries[0]["timestamp"]:
        start_time = all_entries[0]["timestamp"]
        for entry in all_entries:
            if entry["timestamp"]:
                delta = entry["timestamp"] - start_time
                entry["relative_time_ms"] = int(delta.total_seconds() * 1000)
            else:
                entry["relative_time_ms"] = None
    else:
        for entry in all_entries:
            entry["relative_time_ms"] = None

    # Apply limit if specified
    if limit:
        all_entries = all_entries[:limit]

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


def compare_threads(
    files: List[str],
    thread_a: Optional[str] = None,
    thread_b: Optional[str] = None,
    correlation_a: Optional[str] = None,
    correlation_b: Optional[str] = None,
    trace_a: Optional[str] = None,
    trace_b: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare two threads/requests to find differences.

    Perfect for root cause analysis: "What's different between the successful
    request and the failed one?"

    Args:
        files: List of log file paths
        thread_a: First thread ID to compare
        thread_b: Second thread ID to compare
        correlation_a: First correlation ID to compare
        correlation_b: Second correlation ID to compare
        trace_a: First trace ID to compare
        trace_b: Second trace ID to compare

    Returns:
        Dictionary with comparison:
        {
            "thread_a": {
                "id": "...",
                "entries": [...],
                "duration_ms": 1523,
                "error_count": 0,
                "log_levels": {"INFO": 15, "ERROR": 0},
                "unique_messages": 15,
                "services": [...]
            },
            "thread_b": {...},
            "differences": {
                "duration_diff_ms": 2341,  # B took 2341ms longer
                "error_diff": 5,  # B had 5 more errors
                "only_in_a": ["cache hit", ...],  # Messages only in A
                "only_in_b": ["cache miss", "timeout", ...],  # Messages only in B
                "level_changes": {"ERROR": +5, "WARN": +2}
            },
            "summary": "Thread B took 2.3s longer and had 5 errors (cache miss, timeout)"
        }

    Example:
        # Compare successful vs failed request
        diff = compare_threads(
            files=["app.log"],
            correlation_a="req-success-123",
            correlation_b="req-failed-456"
        )
        print(diff['summary'])
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Get both threads
    timeline_a = follow_thread(
        files, thread_id=thread_a, correlation_id=correlation_a, trace_id=trace_a
    )
    timeline_b = follow_thread(
        files, thread_id=thread_b, correlation_id=correlation_b, trace_id=trace_b
    )

    # Analyze thread A
    entries_a = timeline_a.get("entries", [])
    analysis_a = _analyze_thread(entries_a, thread_a or correlation_a or trace_a or "Thread A")

    # Analyze thread B
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


def compare_time_periods(
    files: List[str],
    period_a_start: str,
    period_a_end: str,
    period_b_start: str,
    period_b_end: str,
) -> Dict[str, Any]:
    """
    Compare two time periods to find what changed.

    Perfect for questions like: "What changed after the deployment?"
    or "Why did error rates spike at 3pm?"

    Args:
        files: List of log file paths
        period_a_start: Start time for period A (ISO format)
        period_a_end: End time for period A (ISO format)
        period_b_start: Start time for period B (ISO format)
        period_b_end: End time for period B (ISO format)

    Returns:
        Dictionary with comparison:
        {
            "period_a": {
                "start": "...",
                "end": "...",
                "total_logs": 1523,
                "error_rate": 0.02,
                "log_levels": {...},
                "top_errors": [...],
                "unique_threads": 45
            },
            "period_b": {...},
            "changes": {
                "log_volume_change_pct": 150,  # 150% increase
                "error_rate_change": 10.5,  # 10.5x more errors
                "new_errors": ["OutOfMemoryError", ...],
                "resolved_errors": [],
                "new_threads": 23
            },
            "summary": "Period B had 150% more logs and 10.5x error rate. New errors: OutOfMemoryError"
        }

    Example:
        # Compare before/after deployment
        diff = compare_time_periods(
            files=["app.log"],
            period_a_start="2024-01-01T14:00:00Z",
            period_a_end="2024-01-01T15:00:00Z",
            period_b_start="2024-01-01T15:00:00Z",
            period_b_end="2024-01-01T16:00:00Z"
        )
        print(diff['summary'])
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Search each period
    # Period A
    inv = Investigator()
    inv.load_files(files)

    results_a = search(files, limit=None)
    results_b = search(files, limit=None)

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

    # Analyze periods
    analysis_a = _analyze_period(entries_a, period_a_start, period_a_end)
    analysis_b = _analyze_period(entries_b, period_b_start, period_b_end)

    # Compute changes
    changes = _compute_period_changes(analysis_a, analysis_b)

    # Generate summary
    summary = _generate_period_summary(analysis_a, analysis_b, changes)

    return {"period_a": analysis_a, "period_b": analysis_b, "changes": changes, "summary": summary}


# Helper functions for comparison


def _analyze_thread(entries: List[Dict], thread_id: str) -> Dict[str, Any]:
    """Analyze a single thread's entries"""
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
    """Compute differences between two thread analyses"""
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
    """Generate human-readable summary of comparison"""
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
    """Analyze a time period's entries"""
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
    """Compute changes between two time periods"""
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
    """Generate human-readable summary of period comparison"""
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
    """Check if entry timestamp is within range"""
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


# Token-efficient output formatters


def _format_as_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert full search results to token-efficient summary format.

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
    """
    Convert full search results to count-only format (minimal tokens).

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
    """
    Convert full search results to compact format.

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
    """
    Select a diverse set of sample entries.

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


# Investigation Session Management


class InvestigationSession:
    """
    Track investigation state and history for multi-step analysis.

    This allows LLMs to:
    - Track what they've already investigated
    - Undo/redo operations
    - Save and resume investigations
    - Generate reports of their investigation process

    Example:
        session = InvestigationSession(files=["app.log"])

        # Perform investigation
        session.search(level="ERROR")
        session.follow_thread(correlation_id="req-123")
        session.find_patterns()

        # Review history
        history = session.get_history()

        # Undo last operation
        session.undo()

        # Save for later
        session.save("incident_2024_01_15.json")

        # Resume later
        session2 = InvestigationSession.load("incident_2024_01_15.json")
    """

    def __init__(self, files: Optional[List[str]] = None, name: Optional[str] = None):
        self.files = files or []
        self.name = name or f"investigation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.history = []
        self.current_index = -1
        self.metadata = {}

        if files:
            self._add_to_history("init", "Initialize investigation", {"files": files}, None)

    def search(
        self,
        query: Optional[str] = None,
        level: Optional[str] = None,
        output_format: str = "summary",
        **kwargs,
    ) -> Dict[str, Any]:
        """Perform search and track in history"""
        params = {"query": query, "level": level, "output_format": output_format, **kwargs}
        result = search(self.files, query=query, level=level, output_format=output_format, **kwargs)

        self._add_to_history(
            "search",
            f"Search for {level or 'all'} logs" + (f" matching '{query}'" if query else ""),
            params,
            result,
        )

        return result

    def follow_thread(
        self,
        thread_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Follow thread and track in history"""
        params = {"thread_id": thread_id, "correlation_id": correlation_id, "trace_id": trace_id}
        result = follow_thread(
            self.files, thread_id=thread_id, correlation_id=correlation_id, trace_id=trace_id
        )

        thread_desc = thread_id or correlation_id or trace_id
        self._add_to_history("follow_thread", f"Follow thread: {thread_desc}", params, result)

        return result

    def find_patterns(self, min_occurrences: int = 3) -> Dict[str, Any]:
        """Find patterns and track in history"""
        params = {"min_occurrences": min_occurrences}
        result = find_patterns(self.files, min_occurrences=min_occurrences)

        self._add_to_history(
            "find_patterns", f"Find patterns (min {min_occurrences} occurrences)", params, result
        )

        return result

    def compare_threads(self, **kwargs) -> Dict[str, Any]:
        """Compare threads and track in history"""
        result = compare_threads(self.files, **kwargs)

        desc = f"Compare {kwargs.get('correlation_a', 'A')} vs {kwargs.get('correlation_b', 'B')}"
        self._add_to_history("compare_threads", desc, kwargs, result)

        return result

    def cross_service_timeline(
        self, service_files: Dict[str, List[str]], **kwargs
    ) -> Dict[str, Any]:
        """Create cross-service timeline and track in history"""
        result = cross_service_timeline(service_files, **kwargs)

        desc = f"Cross-service timeline for {list(service_files.keys())}"
        self._add_to_history(
            "cross_service_timeline", desc, {"service_files": service_files, **kwargs}, result
        )

        return result

    def add_note(self, note: str):
        """Add a text note to the investigation"""
        self._add_to_history("note", f"Note: {note[:50]}...", {"note": note}, None)

    def _add_to_history(
        self,
        operation_type: str,
        description: str,
        params: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ):
        """Add operation to history"""
        # Remove any operations after current index (for undo/redo)
        self.history = self.history[: self.current_index + 1]

        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation_type,
            "description": description,
            "params": params,
            "result_summary": self._summarize_result(result) if result else None,
        }

        self.history.append(entry)
        self.current_index = len(self.history) - 1

    def _summarize_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Create a compact summary of operation result"""
        if not result:
            return {}

        summary = {}

        # Common fields
        if "total_matches" in result:
            summary["total_matches"] = result["total_matches"]
        if "total_entries" in result:
            summary["total_entries"] = result["total_entries"]
        if "duration_ms" in result:
            summary["duration_ms"] = result["duration_ms"]
        if "summary" in result:
            summary["summary"] = result["summary"]

        # Pattern results
        if "patterns" in result:
            summary["pattern_count"] = len(result["patterns"])

        # Timeline results
        if "timeline" in result:
            summary["timeline_length"] = len(result["timeline"])

        return summary

    def get_history(self, include_results: bool = False) -> List[Dict[str, Any]]:
        """Get investigation history"""
        if include_results:
            return self.history
        else:
            # Return without full results (more token-efficient)
            return [
                {
                    "timestamp": h["timestamp"],
                    "operation": h["operation"],
                    "description": h["description"],
                    "result_summary": h.get("result_summary"),
                }
                for h in self.history
            ]

    def undo(self) -> bool:
        """Undo last operation"""
        if self.current_index > 0:
            self.current_index -= 1
            return True
        return False

    def redo(self) -> bool:
        """Redo previously undone operation"""
        if self.current_index < len(self.history) - 1:
            self.current_index += 1
            return True
        return False

    def get_current_focus(self) -> Optional[Dict[str, Any]]:
        """Get the current operation being focused on"""
        if 0 <= self.current_index < len(self.history):
            return self.history[self.current_index]
        return None

    def save(self, filepath: str):
        """Save session to file"""
        import json

        data = {
            "name": self.name,
            "files": self.files,
            "history": self.history,
            "current_index": self.current_index,
            "metadata": self.metadata,
            "saved_at": datetime.now().isoformat(),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, filepath: str) -> "InvestigationSession":
        """Load session from file"""
        import json

        with open(filepath, "r") as f:
            data = json.load(f)

        session = cls(files=data["files"], name=data["name"])
        session.history = data["history"]
        session.current_index = data["current_index"]
        session.metadata = data.get("metadata", {})

        return session

    def get_summary(self) -> str:
        """Get a human-readable summary of the investigation"""
        if not self.history:
            return "No investigation steps yet"

        lines = [
            f"Investigation: {self.name}",
            f"Steps completed: {len(self.history)}",
            "",
            "Timeline:",
        ]

        for i, entry in enumerate(self.history):
            marker = "→" if i == self.current_index else " "
            lines.append(f"  {marker} {i+1}. {entry['description']}")
            if entry.get("result_summary"):
                for key, value in entry["result_summary"].items():
                    lines.append(f"      {key}: {value}")

        return "\n".join(lines)

    def generate_report(self, format: str = "markdown", include_evidence: bool = True) -> str:
        """
        Generate a comprehensive investigation report.

        Args:
            format: Output format - "markdown", "text", or "json"
            include_evidence: Include example log entries as evidence

        Returns:
            Formatted investigation report string
        """
        if format == "markdown":
            return self._generate_markdown_report(include_evidence)
        elif format == "text":
            return self._generate_text_report(include_evidence)
        elif format == "json":
            import json

            return json.dumps(self._generate_json_report(include_evidence), indent=2)
        else:
            return self._generate_markdown_report(include_evidence)

    def _generate_markdown_report(self, include_evidence: bool) -> str:
        """Generate Markdown format report"""
        lines = [
            f"# Investigation Report: {self.name}",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Files Analyzed:** {', '.join(self.files)}",
            f"**Steps Completed:** {len(self.history)}",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
        ]

        # Try to extract key findings
        error_counts = []
        patterns_found = []
        key_insights = []

        for entry in self.history:
            summary = entry.get("result_summary") or {}
            if "total_matches" in summary and entry["operation"] == "search":
                error_counts.append(
                    f"- Found {summary['total_matches']} matches in {entry['description']}"
                )
            if "pattern_count" in summary:
                patterns_found.append(f"- Identified {summary['pattern_count']} repeated patterns")
            if "summary" in summary:
                key_insights.append(f"- {summary['summary']}")

        if error_counts:
            lines.extend(error_counts)
        if patterns_found:
            lines.extend(patterns_found)
        if key_insights:
            lines.append("")
            lines.append("### Key Findings")
            lines.extend(key_insights)

        lines.extend(["", "---", "", "## Investigation Timeline", ""])

        # Add detailed timeline
        for i, entry in enumerate(self.history):
            timestamp = entry.get("timestamp", "Unknown time")
            desc = entry["description"]
            operation = entry["operation"]

            lines.append(f"### Step {i+1}: {desc}")
            lines.append("")
            lines.append(f"- **Time:** {timestamp}")
            lines.append(f"- **Operation:** `{operation}`")

            # Add results
            if entry.get("result_summary"):
                lines.append("- **Results:**")
                for key, value in entry["result_summary"].items():
                    lines.append(f"  - {key}: {value}")

            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "## Conclusions",
                "",
                "Based on the investigation steps above, review the key findings and error patterns.",
                "",
                "## Next Steps",
                "",
                "- [ ] Review identified error patterns",
                "- [ ] Investigate root causes",
                "- [ ] Implement fixes",
                "- [ ] Monitor for recurrence",
                "",
            ]
        )

        return "\n".join(lines)

    def _generate_text_report(self, include_evidence: bool) -> str:
        """Generate plain text format report"""
        lines = [
            "=" * 70,
            f"INVESTIGATION REPORT: {self.name}",
            "=" * 70,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Files: {', '.join(self.files)}",
            f"Steps: {len(self.history)}",
            "=" * 70,
            "",
            "TIMELINE:",
            "",
        ]

        for i, entry in enumerate(self.history):
            timestamp = entry.get("timestamp", "Unknown")
            lines.append(f"{i+1}. [{timestamp}] {entry['description']}")

            if entry.get("result_summary"):
                for key, value in entry["result_summary"].items():
                    lines.append(f"   - {key}: {value}")
            lines.append("")

        lines.extend(["=" * 70, "END OF REPORT", "=" * 70])

        return "\n".join(lines)

    def _generate_json_report(self, include_evidence: bool) -> Dict[str, Any]:
        """Generate JSON format report"""
        return {
            "name": self.name,
            "generated_at": datetime.now().isoformat(),
            "files": self.files,
            "steps_completed": len(self.history),
            "timeline": (
                self.history if include_evidence else self.get_history(include_results=False)
            ),
            "metadata": self.metadata,
        }


# Smart Sampling


def smart_sample(
    files: List[str],
    level: Optional[str] = None,
    strategy: str = "representative",
    sample_size: int = 50,
) -> Dict[str, Any]:
    """
    Get a smart sample of log entries that represents the full dataset.

    Instead of random sampling, this uses intelligent strategies to ensure
    the sample is informative and diverse.

    Args:
        files: List of log file paths
        level: Optional log level filter
        strategy: Sampling strategy:
            - "representative": Balanced mix of levels, times, and patterns
            - "diverse": Maximum diversity (different messages, threads, etc.)
            - "chronological": Evenly spaced across time
            - "errors_focused": Prioritize errors with context
        sample_size: Target number of entries (default 50)

    Returns:
        Dictionary with sampled entries:
        {
            "samples": [...],  # Selected log entries
            "total_population": 15230,
            "sample_size": 50,
            "strategy": "representative",
            "coverage": {
                "time_coverage": 0.95,  # % of time range covered
                "level_coverage": {"ERROR": 10, "INFO": 35, "WARN": 5},
                "thread_coverage": 23  # Number of unique threads
            }
        }

    Example:
        # Get representative sample of 100 entries
        sample = smart_sample(
            files=["app.log"],
            strategy="representative",
            sample_size=100
        )

        # Analyze the sample (much faster than full dataset)
        for entry in sample['samples']:
            print(entry['message'])
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Get all entries
    results = search(files, level=level, limit=None)
    all_entries = [r["entry"] for r in results.get("results", [])]

    if not all_entries:
        return {
            "samples": [],
            "total_population": 0,
            "sample_size": 0,
            "strategy": strategy,
            "coverage": {},
        }

    # Apply sampling strategy
    if strategy == "representative":
        samples = _sample_representative(all_entries, sample_size)
    elif strategy == "diverse":
        samples = _sample_diverse(all_entries, sample_size)
    elif strategy == "chronological":
        samples = _sample_chronological(all_entries, sample_size)
    elif strategy == "errors_focused":
        samples = _sample_errors_focused(all_entries, sample_size)
    else:
        # Default to representative
        samples = _sample_representative(all_entries, sample_size)

    # Calculate coverage
    coverage = _calculate_coverage(all_entries, samples)

    return {
        "samples": samples,
        "total_population": len(all_entries),
        "sample_size": len(samples),
        "strategy": strategy,
        "coverage": coverage,
    }


def _sample_representative(entries: List[Dict], size: int) -> List[Dict]:
    """Sample to represent overall distribution"""
    if len(entries) <= size:
        return entries

    samples = []

    # Group by level
    by_level = defaultdict(list)
    for entry in entries:
        level = entry.get("level", "INFO")
        by_level[level].append(entry)

    # Calculate proportional samples per level
    for level, level_entries in by_level.items():
        proportion = len(level_entries) / len(entries)
        level_sample_size = max(1, int(size * proportion))

        # Sample evenly across time
        if level_sample_size >= len(level_entries):
            samples.extend(level_entries)
        else:
            step = len(level_entries) / level_sample_size
            indices = [int(i * step) for i in range(level_sample_size)]
            samples.extend([level_entries[i] for i in indices])

    # If we have too many, trim to size
    if len(samples) > size:
        step = len(samples) / size
        indices = [int(i * step) for i in range(size)]
        samples = [samples[i] for i in indices]

    return samples[:size]


def _sample_diverse(entries: List[Dict], size: int) -> List[Dict]:
    """Sample for maximum diversity"""
    if len(entries) <= size:
        return entries

    samples = []
    used_messages = set()
    used_threads = set()

    # First pass: unique messages
    for entry in entries:
        if len(samples) >= size:
            break

        message = entry.get("message", "")
        if message and message not in used_messages:
            samples.append(entry)
            used_messages.add(message)
            thread = entry.get("thread_id") or entry.get("correlation_id")
            if thread:
                used_threads.add(thread)

    # Second pass: unique threads
    if len(samples) < size:
        for entry in entries:
            if len(samples) >= size:
                break

            thread = entry.get("thread_id") or entry.get("correlation_id")
            if thread and thread not in used_threads:
                samples.append(entry)
                used_threads.add(thread)

    # Third pass: fill remaining with evenly spaced entries
    if len(samples) < size:
        remaining = size - len(samples)
        step = len(entries) / remaining
        for i in range(remaining):
            idx = int(i * step)
            if idx < len(entries):
                samples.append(entries[idx])

    return samples[:size]


def _sample_chronological(entries: List[Dict], size: int) -> List[Dict]:
    """Sample evenly across time"""
    if len(entries) <= size:
        return entries

    # Sort by timestamp
    sorted_entries = sorted(entries, key=lambda e: e.get("timestamp", ""))

    # Sample evenly
    step = len(sorted_entries) / size
    indices = [int(i * step) for i in range(size)]
    return [sorted_entries[i] for i in indices]


def _sample_errors_focused(entries: List[Dict], size: int) -> List[Dict]:
    """Sample focusing on errors with context"""
    if len(entries) <= size:
        return entries

    samples = []
    error_indices = []
    non_error_indices = []

    # Separate errors from non-errors
    for i, entry in enumerate(entries):
        level = entry.get("level", "INFO")
        if level in ["ERROR", "FATAL"]:
            error_indices.append(i)
        else:
            non_error_indices.append(i)

    # Allocate 70% to errors, 30% to context
    error_budget = int(size * 0.7)

    # Sample errors
    if error_indices:
        if len(error_indices) <= error_budget:
            # All errors + some context
            for idx in error_indices:
                samples.append(entries[idx])
                # Add 1-2 entries before error for context
                if idx > 0:
                    samples.append(entries[idx - 1])
        else:
            # Sample errors evenly
            step = len(error_indices) / error_budget
            for i in range(error_budget):
                idx = error_indices[int(i * step)]
                samples.append(entries[idx])

    # Sample non-errors for context
    if non_error_indices and len(samples) < size:
        remaining = size - len(samples)
        step = len(non_error_indices) / remaining
        for i in range(remaining):
            idx = non_error_indices[min(int(i * step), len(non_error_indices) - 1)]
            samples.append(entries[idx])

    # Sort by original order
    entry_to_index = {id(e): i for i, e in enumerate(entries)}
    samples.sort(key=lambda e: entry_to_index.get(id(e), 0))

    return samples[:size]


def _calculate_coverage(population: List[Dict], sample: List[Dict]) -> Dict[str, Any]:
    """Calculate how well the sample covers the population"""
    # Time coverage
    pop_times = [e.get("timestamp") for e in population if e.get("timestamp")]
    sample_times = [e.get("timestamp") for e in sample if e.get("timestamp")]

    time_coverage = 0.0
    if pop_times and sample_times:
        pop_times.sort()
        sample_times.sort()
        # Simple coverage: sample span / population span
        try:
            pop_start = datetime.fromisoformat(pop_times[0].replace("Z", "+00:00"))
            pop_end = datetime.fromisoformat(pop_times[-1].replace("Z", "+00:00"))
            sample_start = datetime.fromisoformat(sample_times[0].replace("Z", "+00:00"))
            sample_end = datetime.fromisoformat(sample_times[-1].replace("Z", "+00:00"))

            pop_duration = (pop_end - pop_start).total_seconds()
            sample_duration = (sample_end - sample_start).total_seconds()

            if pop_duration > 0:
                time_coverage = min(1.0, sample_duration / pop_duration)
        except (ValueError, TypeError, AttributeError):
            pass  # Skip if timestamps are invalid

    # Level coverage
    level_coverage = defaultdict(int)
    for entry in sample:
        level = entry.get("level", "INFO")
        level_coverage[level] += 1

    # Thread coverage
    pop_threads = set()
    sample_threads = set()
    for entry in population:
        thread = entry.get("thread_id") or entry.get("correlation_id")
        if thread:
            pop_threads.add(thread)
    for entry in sample:
        thread = entry.get("thread_id") or entry.get("correlation_id")
        if thread:
            sample_threads.add(thread)

    thread_coverage_pct = len(sample_threads) / len(pop_threads) if pop_threads else 0

    return {
        "time_coverage": time_coverage,
        "level_distribution": dict(level_coverage),
        "unique_threads_in_sample": len(sample_threads),
        "unique_threads_in_population": len(pop_threads),
        "thread_coverage_pct": thread_coverage_pct,
    }


# Automatic Insights and Suggestions


def analyze_with_insights(
    files: List[str], level: Optional[str] = None, auto_investigate: bool = True
) -> Dict[str, Any]:
    """
    Analyze logs and automatically generate insights and suggestions.

    This is the "smart mode" that does the thinking for you - perfect for
    LLMs that want quick actionable information.

    Args:
        files: List of log file paths
        level: Optional log level filter (default: analyzes all levels)
        auto_investigate: Automatically perform follow-up investigations

    Returns:
        Dictionary with insights:
        {
            "overview": {...},  # Quick stats
            "insights": [
                {
                    "type": "error_spike",
                    "severity": "high",
                    "description": "Error rate 10x higher than normal",
                    "evidence": [...],
                    "suggestion": "Check database connections"
                },
                ...
            ],
            "suggestions": [
                "Follow thread req-12345 - appears to be failing consistently",
                "Check database connection pool size",
                ...
            ],
            "next_steps": [...]  # Recommended next investigation steps
        }

    Example:
        # One-shot analysis with insights
        result = analyze_with_insights(files=["app.log"])

        for insight in result['insights']:
            print(f"[{insight['severity']}] {insight['description']}")
            print(f"  → {insight['suggestion']}")
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    insights = []
    suggestions = []
    next_steps = []

    # Get overview
    metadata = get_metadata(files)
    search_results = search(files, level=level, output_format="summary")

    # Insight 1: Error rate analysis
    total = search_results.get("total_matches", 0)
    levels = search_results.get("log_levels", {})
    error_count = levels.get("ERROR", 0) + levels.get("FATAL", 0)

    if total > 0:
        error_rate = error_count / total
        if error_rate > 0.1:  # More than 10% errors
            insights.append(
                {
                    "type": "high_error_rate",
                    "severity": "high",
                    "description": f"High error rate: {error_rate:.1%} ({error_count}/{total})",
                    "evidence": {"error_count": error_count, "total": total, "rate": error_rate},
                    "suggestion": "Investigate most common errors first",
                }
            )
            next_steps.append("Run: find_patterns(files, min_occurrences=3)")

    # Insight 2: Pattern detection
    if auto_investigate and error_count > 0:
        patterns = find_patterns(files, min_occurrences=2)
        if patterns.get("patterns"):
            pattern_count = len(patterns["patterns"])
            insights.append(
                {
                    "type": "repeated_patterns",
                    "severity": "medium",
                    "description": f"Found {pattern_count} repeated error patterns",
                    "evidence": patterns["patterns"][:3],  # Top 3
                    "suggestion": "These errors are systematic, not random",
                }
            )

            # Suggest investigating the most frequent pattern
            if patterns["patterns"]:
                top_pattern = patterns["patterns"][0]
                suggestions.append(
                    f"Investigate pattern: '{top_pattern.get('pattern', '')[:50]}...'"
                )

    # Insight 3: Check for cascading failures
    if error_count > 5:
        # Look for timing patterns
        top_messages = search_results.get("top_messages", [])
        if top_messages:
            # Check if errors happened in quick succession
            time_clustered = any(msg.get("count", 0) > 3 for msg in top_messages)
            if time_clustered:
                insights.append(
                    {
                        "type": "possible_cascade",
                        "severity": "high",
                        "description": "Errors may be cascading (multiple errors in short time)",
                        "evidence": top_messages[:2],
                        "suggestion": "Look for root cause - later errors may be symptoms",
                    }
                )
                suggestions.append("Check timestamps - investigate earliest error first")

    # Insight 4: Thread analysis
    for meta in metadata:
        unique_correlations = meta.get("unique_correlation_ids", 0)

        if error_count > 0 and unique_correlations > 0:
            # Some threads are failing
            insights.append(
                {
                    "type": "thread_failures",
                    "severity": "medium",
                    "description": f"Errors across {unique_correlations} different requests",
                    "evidence": {"unique_correlations": unique_correlations},
                    "suggestion": "Compare successful vs failed requests",
                }
            )
            next_steps.append("Use: compare_threads() to find differences")

    # Generate suggestions based on insights
    if not suggestions:
        if error_count > 0:
            suggestions.append("Start by examining the first error - it may be the root cause")
            suggestions.append("Use follow_thread() to see full request flow")
        else:
            suggestions.append("No errors found - logs look healthy")

    # Overview
    overview = {
        "total_logs": total,
        "error_count": error_count,
        "error_rate": error_count / total if total > 0 else 0,
        "files_analyzed": len(files),
        "log_levels": levels,
    }

    return {
        "overview": overview,
        "insights": insights,
        "suggestions": suggestions,
        "next_steps": next_steps,
        "investigated_automatically": auto_investigate,
    }


def explain(
    entry: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    context: str = "general",
) -> str:
    """
    Explain a log entry or error message in simple terms.

    Perfect for when you encounter cryptic errors or need to understand
    what's happening. Provides human-friendly explanations and next steps.

    Args:
        entry: Log entry dictionary to explain
        error_message: Or just provide an error message string
        context: Context for explanation ("production", "development", "general")

    Returns:
        Human-friendly explanation string

    Example:
        # Explain a log entry
        explanation = explain(
            entry=error_entry,
            context="production"
        )
        print(explanation)

        # Explain just a message
        explanation = explain(
            error_message="Connection pool exhausted",
            context="production"
        )
    """
    if entry:
        message = entry.get("message", "")
        level = entry.get("level", "INFO")
    elif error_message:
        message = error_message
        level = "ERROR"
    else:
        return "No entry or message provided to explain"

    # Build explanation
    lines = []

    # What happened
    lines.append("## What This Means\n")

    # Pattern matching for common errors
    message_lower = message.lower()

    if "timeout" in message_lower or "timed out" in message_lower:
        lines.append("A timeout means an operation took too long and was cancelled.")
        lines.append("\n**Common causes:**")
        lines.append("- Database query is too slow")
        lines.append("- Network latency issues")
        lines.append("- Service is overloaded")
        lines.append("- Deadlock or infinite loop")
        lines.append("\n**Next steps:**")
        lines.append("1. Check what operation was timing out")
        lines.append("2. Look at the service being called - is it slow or down?")
        lines.append("3. Review timeout configuration - is it too short?")

    elif "connection" in message_lower and (
        "refused" in message_lower or "failed" in message_lower
    ):
        lines.append("A connection failure means the application couldn't reach another service.")
        lines.append("\n**Common causes:**")
        lines.append("- Service is down or not responding")
        lines.append("- Network connectivity issues")
        lines.append("- Firewall blocking the connection")
        lines.append("- Wrong hostname/port configuration")
        lines.append("\n**Next steps:**")
        lines.append("1. Check if the target service is running")
        lines.append("2. Verify network connectivity")
        lines.append("3. Check configuration (hostname, port, etc.)")

    elif "pool exhausted" in message_lower or "too many connections" in message_lower:
        lines.append("The connection pool is exhausted - all available connections are in use.")
        lines.append("\n**Common causes:**")
        lines.append("- Traffic spike overwhelming the system")
        lines.append("- Connection leaks (not closing connections)")
        lines.append("- Pool size too small for the load")
        lines.append("- Slow queries holding connections too long")
        lines.append("\n**Next steps:**")
        lines.append("1. Check connection pool size configuration")
        lines.append("2. Look for connection leaks in code")
        lines.append("3. Identify slow operations holding connections")
        lines.append("4. Consider increasing pool size if load is legitimate")

    elif "out of memory" in message_lower or "outofmemoryerror" in message_lower:
        lines.append("The application ran out of available memory.")
        lines.append("\n**Common causes:**")
        lines.append("- Memory leak (memory not being freed)")
        lines.append("- Processing too much data at once")
        lines.append("- Insufficient memory allocated")
        lines.append("- Caching too aggressively")
        lines.append("\n**Next steps:**")
        lines.append("1. Check memory allocation settings")
        lines.append("2. Look for memory leaks")
        lines.append("3. Review data processing - can it be batched/streamed?")
        lines.append("4. Check garbage collection logs")

    elif "null" in message_lower and ("pointer" in message_lower or "reference" in message_lower):
        lines.append("Tried to use something that doesn't exist (null/None).")
        lines.append("\n**Common causes:**")
        lines.append("- Missing input validation")
        lines.append("- Unexpected missing data")
        lines.append("- Race condition")
        lines.append("- API returned unexpected null")
        lines.append("\n**Next steps:**")
        lines.append("1. Check the stack trace to find where it happened")
        lines.append("2. Add null checks and validation")
        lines.append("3. Review why the value was null")

    elif (
        "permission" in message_lower
        or "access denied" in message_lower
        or "forbidden" in message_lower
    ):
        lines.append("The application doesn't have permission to perform this action.")
        lines.append("\n**Common causes:**")
        lines.append("- Incorrect file/resource permissions")
        lines.append("- Wrong user/service account")
        lines.append("- Missing IAM roles or policies")
        lines.append("- Authentication token expired")
        lines.append("\n**Next steps:**")
        lines.append("1. Check file/resource permissions")
        lines.append("2. Verify the application is running as the correct user")
        lines.append("3. Review access control policies")

    else:
        # Generic explanation
        if level == "ERROR" or level == "FATAL":
            lines.append("This is an error that prevented normal operation.")
            lines.append(f"\nError message: `{message}`")
            lines.append("\n**Next steps:**")
            lines.append("1. Look at the full stack trace if available")
            lines.append("2. Check what operation was being performed")
            lines.append("3. Look for similar errors - is this a pattern?")
            lines.append("4. Check if there were recent changes (deployment, config)")
        elif level == "WARN":
            lines.append("This is a warning - not critical but worth investigating.")
            lines.append(f"\nMessage: `{message}`")
            lines.append("\n**Next steps:**")
            lines.append("1. Determine if this warning is expected")
            lines.append("2. Check if it's happening frequently")
            lines.append("3. Consider if it could become a problem")
        else:
            lines.append("This is an informational message.")
            lines.append(f"\nMessage: `{message}`")

    # Context-specific advice
    if context == "production":
        lines.append("\n**Production Context:**")
        lines.append("- Check monitoring dashboards for patterns")
        lines.append("- Review recent deployments")
        lines.append("- Consider impact on users")
        lines.append("- Prepare rollback plan if needed")

    return "\n".join(lines)


def suggest_next_action(
    current_results: Dict[str, Any], investigation_context: Optional[Dict] = None
) -> List[str]:
    """
    Suggest what to investigate next based on current results.

    Args:
        current_results: Results from previous operation (search, pattern finding, etc.)
        investigation_context: Optional context about what's been investigated so far

    Returns:
        List of suggested next actions with example code
    """
    suggestions = []

    # Based on search results
    if "total_matches" in current_results:
        total = current_results["total_matches"]
        if total == 0:
            suggestions.append("No matches found. Try:")
            suggestions.append("  - Broaden search (remove filters)")
            suggestions.append("  - Check different log files")
            suggestions.append("  - Verify time range")
        elif total > 1000:
            suggestions.append(f"Large result set ({total} matches). Consider:")
            suggestions.append("  - Use output_format='summary' for token efficiency")
            suggestions.append("  - Add more filters (level, time range, thread_id)")
            suggestions.append("  - Use smart_sample() to get representative sample")
        elif total > 0:
            # Good result size, suggest next steps
            if "top_messages" in current_results:
                top_msg = (
                    current_results["top_messages"][0] if current_results["top_messages"] else None
                )
                if top_msg and top_msg.get("count", 0) > 3:
                    suggestions.append("Repeated errors detected. Next:")
                    suggestions.append("  - find_patterns(files, min_occurrences=3)")
                    suggestions.append("  - Follow one of these threads to see full context")

    # Based on patterns
    if "patterns" in current_results:
        pattern_count = len(current_results.get("patterns", []))
        if pattern_count > 0:
            suggestions.append(f"Found {pattern_count} patterns. Next:")
            suggestions.append("  - Compare successful vs failed requests")
            suggestions.append("  - Check timestamps - are they clustered?")

    # Default suggestions
    if not suggestions:
        suggestions.append("Continue investigation:")
        suggestions.append("  - analyze_with_insights(files) - Get automatic insights")
        suggestions.append("  - find_patterns(files) - Find repeated issues")
        suggestions.append("  - compare_time_periods() - Before/after analysis")

    return suggestions


def _load_files_with_config(
    inv: Any,
    files: List[str],
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
):
    """Load files with optional parser config; falls back to plain load if config not supported."""
    try:
        if parser_format or custom_regex:
            return inv.load_files_with_config(files, parser_format, custom_regex)
    except Exception:
        # Fall back silently to default loader if enhanced path fails
        pass
    return inv.load_files(files)
