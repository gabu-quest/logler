"""
Thread hierarchy, error-flow analysis, bottleneck detection, and correlation chains.

Public API surface is re-exported by :mod:`logler.investigate`.
"""

import json
import re
from typing import List, Optional, Dict, Any
from collections import defaultdict

from ._search_core import (
    RUST_AVAILABLE,
)


# ---------------------------------------------------------------------------
# Hierarchy construction
# ---------------------------------------------------------------------------


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
    """Build hierarchical tree of threads/spans showing parent-child relationships.

    This detects sub-threads and nested operations using:

    * Explicit ``parent_span_id`` fields (OpenTelemetry)
    * Naming patterns (``worker-1.task-a``, ``main:subtask-1``)
    * Temporal inference (time-based proximity)

    Args:
        files: Log file paths to analyse.
        root_identifier: Root thread ID, correlation ID, or span ID.
        max_depth: Maximum depth of hierarchy tree (default: unlimited).
        use_naming_patterns: Enable naming pattern detection (default: True).
        use_temporal_inference: Enable time-based inference (default: True).
        min_confidence: Minimum confidence score 0.0-1.0 (default: 0.0).
        parser_format: Optional log format hint.
        custom_regex: Optional custom parsing regex.

    Returns:
        HierarchyResult dict with shape::

            {
                "roots": [HierarchyNode, ...],
                "total_nodes": int,
                "max_depth": int,
                "total_duration_ms": int | None,
                "concurrent_count": int,
                "bottleneck": {"node_id": str, "duration_ms": int, ...} | None,
                "error_nodes": [str, ...],
                "detection_method": str,
                "detection_methods": [str, ...]
            }

    Example::

        >>> h = follow_thread_hierarchy(["app.log"], root_identifier="trace-abc")
        >>> print(get_hierarchy_summary(h))
    """
    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    import logler_rs

    # Lazy import to avoid circular dependency
    from .investigate import Investigator

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


# ---------------------------------------------------------------------------
# Hierarchy summary & tree preview
# ---------------------------------------------------------------------------


def _format_detection_method(hierarchy: Dict[str, Any]) -> str:
    method = hierarchy.get("detection_method", "Unknown")
    methods = hierarchy.get("detection_methods") or []
    method_str = str(method)
    method_list = [str(m) for m in methods if m]
    if method_list and (method_str == "Mixed" or len(method_list) > 1):
        return f"{method_str} ({', '.join(method_list)})"
    return method_str


def get_hierarchy_summary(hierarchy: Dict[str, Any]) -> str:
    """Generate a human-readable summary of a thread hierarchy.

    Args:
        hierarchy: Hierarchy dict from :func:`follow_thread_hierarchy`.

    Returns:
        Formatted text summary.

    Example::

        >>> hierarchy = follow_thread_hierarchy(["app.log"], root_identifier="req-123")
        >>> print(get_hierarchy_summary(hierarchy))
    """
    lines = []

    # Overview
    lines.append("=== Thread Hierarchy Summary ===")
    lines.append(f"Total nodes: {hierarchy.get('total_nodes', 0)}")
    lines.append(f"Max depth: {hierarchy.get('max_depth', 0)}")
    lines.append(f"Detection method: {_format_detection_method(hierarchy)}")

    # Duration
    total_duration = hierarchy.get("total_duration_ms")
    if total_duration:
        lines.append(f"Total duration: {total_duration}ms ({total_duration / 1000:.2f}s)")

    # Concurrent operations
    concurrent = hierarchy.get("concurrent_count", 0)
    if concurrent > 1:
        lines.append(f"Concurrent operations: {concurrent}")

    # Bottleneck
    bottleneck = hierarchy.get("bottleneck")
    if bottleneck:
        lines.append("")
        lines.append("\u26a0\ufe0f  BOTTLENECK DETECTED:")
        lines.append(f"  Node: {bottleneck.get('node_id')}")
        lines.append(
            f"  Duration: {bottleneck.get('duration_ms')}ms ({bottleneck.get('percentage', 0):.1f}% of total)"
        )
        lines.append(f"  Depth: {bottleneck.get('depth')}")

    # Errors
    error_nodes = hierarchy.get("error_nodes", [])
    if error_nodes:
        lines.append("")
        lines.append(f"\u274c Errors in {len(error_nodes)} node(s):")
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
                f"  \U0001f4c1 {root.get('id')} ({root.get('entry_count', 0)} entries, {len(root.get('children', []))} children)"
            )
            _append_tree_preview(root, lines, depth=1, max_depth=2)
        if len(roots) > 3:
            lines.append(f"  ... and {len(roots) - 3} more root(s)")

    return "\n".join(lines)


def _append_tree_preview(node: Dict[str, Any], lines: List[str], depth: int, max_depth: int):
    """Helper to append tree preview to lines."""
    if depth >= max_depth:
        return

    children = node.get("children", [])
    for i, child in enumerate(children[:3]):  # Show first 3 children
        is_last = i == len(children) - 1
        prefix = "  " * depth + ("\u2514\u2500 " if is_last else "\u251c\u2500 ")

        error_marker = "\u274c " if child.get("error_count", 0) > 0 else ""
        duration = child.get("duration_ms", 0)
        duration_str = f" ({duration}ms)" if duration > 0 else ""

        lines.append(
            f"{prefix}{error_marker}{child.get('id')} ({child.get('entry_count', 0)} entries){duration_str}"
        )
        _append_tree_preview(child, lines, depth + 1, max_depth)

    if len(children) > 3:
        prefix = "  " * depth + "\u2514\u2500 "
        lines.append(f"{prefix}... and {len(children) - 3} more")


# ---------------------------------------------------------------------------
# Error flow analysis
# ---------------------------------------------------------------------------


def analyze_error_flow(
    hierarchy: Dict[str, Any],
    include_context: bool = True,
) -> Dict[str, Any]:
    """Analyse error propagation through a hierarchy to identify root causes.

    Traces errors through parent-child relationships to find root causes,
    propagation chains, affected nodes, and impact assessment.

    Args:
        hierarchy: Hierarchy dict from :func:`follow_thread_hierarchy`.
        include_context: Include sample error messages (default: True).

    Returns:
        ErrorFlowResult dict with shape::

            {
                "has_errors": bool,
                "total_error_nodes": int,
                "root_causes": [{"node_id": str, "confidence": float, ...}],
                "propagation_chains": [...],
                "impact_summary": {"total_affected_nodes": int, ...},
                "recommendations": [str, ...]
            }

    Example::

        >>> analysis = analyze_error_flow(hierarchy)
        >>> if analysis["has_errors"]:
        ...     print(f"Root cause: {analysis['root_causes'][0]['node_id']}")
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
    """Format error flow analysis as human-readable text.

    Args:
        error_analysis: Error analysis from :func:`analyze_error_flow`.
        show_chains: Show propagation chains (default: True).
        show_recommendations: Show recommendations (default: True).

    Returns:
        Formatted error flow string.

    Example::

        >>> print(format_error_flow(analyze_error_flow(hierarchy)))
    """
    lines = []

    if not error_analysis.get("has_errors"):
        return "\u2705 No errors detected in hierarchy"

    # Header
    lines.append("=" * 70)
    lines.append("\U0001f50d ERROR FLOW ANALYSIS")
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
        lines.append("\U0001f534 ROOT CAUSE(S)")
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
                path_str = " \u2192 ".join(cause["path"])
                lines.append(f"     Path: {path_str}")

    # Propagation Chains
    if show_chains:
        chains = error_analysis.get("propagation_chains", [])
        if chains:
            lines.append("")
            lines.append("-" * 70)
            lines.append("\U0001f4c8 ERROR PROPAGATION")
            lines.append("-" * 70)

            for chain_data in chains:
                lines.append(f"\n  From: {chain_data['root_cause']}")
                lines.append(f"  Affected nodes: {chain_data['total_affected']}")
                lines.append("  Chain:")

                chain = chain_data.get("chain", [])
                for j, node in enumerate(chain):
                    is_last = j == len(chain) - 1
                    prefix = "     \u2514\u2500" if is_last else "     \u251c\u2500"
                    arrow = " \u2190 ROOT CAUSE" if j == 0 else ""
                    lines.append(
                        f"{prefix} {node['node_id']} ({node['error_count']} errors){arrow}"
                    )

    # Recommendations
    if show_recommendations:
        recommendations = error_analysis.get("recommendations", [])
        if recommendations:
            lines.append("")
            lines.append("-" * 70)
            lines.append("\U0001f4a1 RECOMMENDATIONS")
            lines.append("-" * 70)

            for rec in recommendations:
                lines.append(f"  \u2022 {rec}")

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Correlation chain detection
# ---------------------------------------------------------------------------


def detect_correlation_chains(
    files: List[str],
    root_correlation_id: Optional[str] = None,
    chain_patterns: Optional[List[str]] = None,
    parser_format: Optional[str] = None,
) -> Dict[str, Any]:
    """Detect correlation ID chaining where one request spawns sub-requests.

    Identifies parent-child relationships between correlation IDs by analysing
    log messages for patterns like ``"spawning request {child_id}"``.

    Args:
        files: Log file paths to analyse.
        root_correlation_id: Optional root correlation ID to start from.
        chain_patterns: Optional custom regex patterns for detecting chains.
        parser_format: Optional log format hint.

    Returns:
        CorrelationChainResult dict with shape::

            {
                "chains": [{"parent_correlation_id": str, "child_correlation_id": str, ...}],
                "root_ids": [str, ...],
                "hierarchy": {"parent_id": ["child_id", ...]},
                "total_chains": int,
                "total_correlation_ids": int
            }

    Example::

        >>> chains = detect_correlation_chains(["app.log"], root_correlation_id="req-main")
        >>> for c in chains["chains"]:
        ...     print(f"{c['parent_correlation_id']} -> {c['child_correlation_id']}")
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
        import logler_rs

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
    """Build hierarchy that includes correlation ID chaining relationships.

    Extends :func:`follow_thread_hierarchy` by also detecting when one
    correlation ID spawns sub-requests with different correlation IDs.

    Args:
        files: Log file paths.
        root_identifier: Root correlation ID, thread ID, or span ID.
        include_correlation_chains: Whether to detect chaining (default: True).
        max_depth: Maximum hierarchy depth.
        use_naming_patterns: Enable naming pattern detection.
        use_temporal_inference: Enable temporal inference.
        min_confidence: Minimum confidence score.

    Returns:
        HierarchyResult dict with additional correlation chain information.

    Example::

        >>> h = build_hierarchy_with_correlation_chains(["api.log"], "req-main-001")
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


# ---------------------------------------------------------------------------
# Bottleneck analysis
# ---------------------------------------------------------------------------


def analyze_bottlenecks(
    hierarchy: Dict[str, Any],
    threshold_percentage: float = 20.0,
) -> Dict[str, Any]:
    """Detect performance bottlenecks with optimisation suggestions.

    Analyses hierarchy to identify primary/secondary bottlenecks,
    parallelisation opportunities, caching candidates, and circuit breaker
    recommendations.

    Args:
        hierarchy: Hierarchy from :func:`follow_thread_hierarchy`.
        threshold_percentage: Minimum % of total time to be considered significant.

    Returns:
        BottleneckAnalysis dict with shape::

            {
                "primary_bottleneck": {...} | None,
                "secondary_bottlenecks": [...],
                "optimization_suggestions": [str, ...],
                "parallelization_opportunities": [...],
                "estimated_improvement_ms": float
            }

    Example::

        >>> analysis = analyze_bottlenecks(hierarchy)
        >>> for s in analysis["optimization_suggestions"]:
        ...     print(f"  - {s}")
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

    # Generate optimisation suggestions
    suggestions = []

    # Check for parallelisation opportunities
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


# ---------------------------------------------------------------------------
# Hierarchy diffing
# ---------------------------------------------------------------------------


def diff_hierarchies(
    hierarchy_a: Dict[str, Any],
    hierarchy_b: Dict[str, Any],
    label_a: str = "Before",
    label_b: str = "After",
) -> Dict[str, Any]:
    """Compare two hierarchies to identify performance changes.

    Useful for before/after deployment comparisons, A/B testing,
    or debugging performance regressions.

    Args:
        hierarchy_a: First hierarchy (baseline).
        hierarchy_b: Second hierarchy (comparison).
        label_a: Label for first hierarchy.
        label_b: Label for second hierarchy.

    Returns:
        HierarchyDiffResult dict with shape::

            {
                "summary": {"total_duration_change_ms": float, ...},
                "improved_nodes": [...],
                "degraded_nodes": [...],
                "new_nodes": [...],
                "removed_nodes": [...]
            }

    Example::

        >>> diff = diff_hierarchies(before_h, after_h)
        >>> print(f"Change: {diff['summary']['total_duration_change_pct']:.1f}%")
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
    """Format hierarchy diff as human-readable text.

    Args:
        diff: Diff from :func:`diff_hierarchies`.

    Returns:
        Formatted diff string.
    """
    lines = []

    lines.append("=" * 70)
    lines.append("\U0001f4ca HIERARCHY COMPARISON")
    lines.append(f"   {diff['label_a']} vs {diff['label_b']}")
    lines.append("=" * 70)

    summary = diff["summary"]
    change_ms = summary["total_duration_change_ms"]
    change_pct = summary["total_duration_change_pct"]

    direction = (
        "\u2b07\ufe0f IMPROVED"
        if change_ms < 0
        else "\u2b06\ufe0f DEGRADED" if change_ms > 0 else "\u27a1\ufe0f UNCHANGED"
    )
    lines.append(f"\n{direction}: {abs(change_ms):.0f}ms ({abs(change_pct):.1f}%)")

    if summary["new_errors"] > 0:
        lines.append(f"\u274c New errors: {summary['new_errors']}")
    if summary["resolved_errors"] > 0:
        lines.append(f"\u2705 Resolved errors: {summary['resolved_errors']}")

    if diff["improved_nodes"]:
        lines.append("\n" + "-" * 70)
        lines.append("\u2705 IMPROVED NODES")
        for node in diff["improved_nodes"][:5]:
            lines.append(
                f"  \u2022 {node['id']}: {node['before_ms']:.0f}ms \u2192 {node['after_ms']:.0f}ms "
                f"({node['change_pct']:.1f}%)"
            )

    if diff["degraded_nodes"]:
        lines.append("\n" + "-" * 70)
        lines.append("\u26a0\ufe0f DEGRADED NODES")
        for node in diff["degraded_nodes"][:5]:
            lines.append(
                f"  \u2022 {node['id']}: {node['before_ms']:.0f}ms \u2192 {node['after_ms']:.0f}ms "
                f"(+{node['change_pct']:.1f}%)"
            )

    if diff["new_nodes"]:
        lines.append("\n" + "-" * 70)
        lines.append("\U0001f195 NEW NODES")
        for node in diff["new_nodes"][:5]:
            lines.append(f"  \u2022 {node['id']}: {node['duration_ms']:.0f}ms")

    if diff["removed_nodes"]:
        lines.append("\n" + "-" * 70)
        lines.append("\U0001f5d1\ufe0f REMOVED NODES")
        for node in diff["removed_nodes"][:5]:
            lines.append(f"  \u2022 {node['id']}: was {node['duration_ms']:.0f}ms")

    lines.append("\n" + "=" * 70)

    return "\n".join(lines)
