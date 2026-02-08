"""
BRUTAL HIERARCHY DETECTION TESTS - Mayhem Edition

These tests torture the hierarchy detection, error flow analysis,
and tree formatting with edge cases that break naive implementations.
"""

import json
import pytest
import tempfile
from pathlib import Path


# Imports with graceful fallback
try:
    from logler.investigate import (
        follow_thread_hierarchy,
        analyze_error_flow,
        get_hierarchy_summary,
        format_error_flow,
        RUST_AVAILABLE,
    )
    from logler.tree_formatter import (
        format_tree,
        format_waterfall,
        format_flamegraph,
    )
except ImportError as e:
    if "logler_rs" in str(e):
        RUST_AVAILABLE = False
    else:
        raise


pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust backend required for hierarchy tests"
)


# =============================================================================
# Fixtures for Various Hierarchy Structures
# =============================================================================


@pytest.fixture
def empty_hierarchy():
    """Completely empty hierarchy"""
    return {
        "roots": [],
        "total_nodes": 0,
        "max_depth": 0,
        "total_duration_ms": 0,
        "concurrent_count": 0,
        "bottleneck": None,
        "error_nodes": [],
        "detection_method": "Unknown",
    }


@pytest.fixture
def single_node_hierarchy():
    """Hierarchy with only one node"""
    return {
        "roots": [
            {
                "id": "lonely-node",
                "node_type": "Span",
                "name": "Sole Survivor",
                "parent_id": None,
                "children": [],
                "entry_ids": [1, 2, 3],
                "start_time": "2024-01-15T10:00:00Z",
                "end_time": "2024-01-15T10:00:01Z",
                "duration_ms": 1000,
                "entry_count": 3,
                "error_count": 0,
                "level_counts": {"INFO": 3},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 1,
        "max_depth": 0,
        "total_duration_ms": 1000,
        "concurrent_count": 1,
        "bottleneck": {
            "node_id": "lonely-node",
            "duration_ms": 1000,
            "percentage": 100.0,
            "depth": 0,
        },
        "error_nodes": [],
        "detection_method": "ExplicitParentId",
    }


@pytest.fixture
def wide_hierarchy():
    """Wide hierarchy with many siblings"""
    children = []
    for i in range(100):
        children.append(
            {
                "id": f"child-{i}",
                "node_type": "Span",
                "name": f"Child {i}",
                "parent_id": "root",
                "children": [],
                "entry_ids": [i],
                "start_time": f"2024-01-15T10:00:{i % 60:02d}Z",
                "end_time": f"2024-01-15T10:00:{(i % 60) + 1:02d}Z",
                "duration_ms": 10,
                "entry_count": 1,
                "error_count": 0 if i % 10 != 0 else 1,
                "level_counts": {"INFO": 1} if i % 10 != 0 else {"ERROR": 1},
                "depth": 1,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        )

    return {
        "roots": [
            {
                "id": "root",
                "node_type": "CorrelationGroup",
                "name": "Root with 100 children",
                "parent_id": None,
                "children": children,
                "entry_ids": [0],
                "start_time": "2024-01-15T10:00:00Z",
                "end_time": "2024-01-15T10:02:00Z",
                "duration_ms": 120000,
                "entry_count": 101,
                "error_count": 10,
                "level_counts": {"INFO": 91, "ERROR": 10},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 101,
        "max_depth": 1,
        "total_duration_ms": 120000,
        "concurrent_count": 100,
        "bottleneck": None,
        "error_nodes": [f"child-{i * 10}" for i in range(10)],
        "detection_method": "ExplicitParentId",
    }


@pytest.fixture
def deep_hierarchy():
    """Very deep hierarchy (100 levels)"""

    def build_deep(depth, max_depth):
        node = {
            "id": f"level-{depth}",
            "node_type": "Span",
            "name": f"Level {depth}",
            "parent_id": f"level-{depth - 1}" if depth > 0 else None,
            "children": [],
            "entry_ids": [depth],
            "start_time": "2024-01-15T10:00:00Z",
            "end_time": "2024-01-15T10:00:01Z",
            "duration_ms": 1000 - depth * 5,
            "entry_count": 1,
            "error_count": 0,
            "level_counts": {"INFO": 1},
            "depth": depth,
            "confidence": 1.0 - depth * 0.005,  # Decreasing confidence
            "relationship_evidence": (
                ["Temporal inference"] if depth > 50 else ["Explicit parent_span_id"]
            ),
        }
        if depth < max_depth:
            node["children"] = [build_deep(depth + 1, max_depth)]
        return node

    root = build_deep(0, 99)
    return {
        "roots": [root],
        "total_nodes": 100,
        "max_depth": 99,
        "total_duration_ms": 1000,
        "concurrent_count": 1,
        "bottleneck": {"node_id": "level-0", "duration_ms": 1000, "percentage": 100.0, "depth": 0},
        "error_nodes": [],
        "detection_method": "Mixed",
    }


@pytest.fixture
def multi_root_hierarchy():
    """Hierarchy with multiple independent roots"""
    roots = []
    for i in range(10):
        roots.append(
            {
                "id": f"root-{i}",
                "node_type": "Thread",
                "name": f"Independent Root {i}",
                "parent_id": None,
                "children": [
                    {
                        "id": f"root-{i}-child",
                        "node_type": "Span",
                        "name": f"Child of Root {i}",
                        "parent_id": f"root-{i}",
                        "children": [],
                        "entry_ids": [i * 2 + 1],
                        "start_time": "2024-01-15T10:00:00Z",
                        "end_time": "2024-01-15T10:00:01Z",
                        "duration_ms": 100,
                        "entry_count": 1,
                        "error_count": 0,
                        "level_counts": {"INFO": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    }
                ],
                "entry_ids": [i * 2],
                "start_time": "2024-01-15T10:00:00Z",
                "end_time": "2024-01-15T10:00:02Z",
                "duration_ms": 200,
                "entry_count": 2,
                "error_count": 0,
                "level_counts": {"INFO": 2},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        )

    return {
        "roots": roots,
        "total_nodes": 20,
        "max_depth": 1,
        "total_duration_ms": 2000,
        "concurrent_count": 10,
        "bottleneck": None,
        "error_nodes": [],
        "detection_method": "NamingPattern",
    }


@pytest.fixture
def error_cascade_hierarchy():
    """Hierarchy showing error cascading up the tree"""
    return {
        "roots": [
            {
                "id": "api-gateway",
                "node_type": "CorrelationGroup",
                "name": "API Gateway",
                "parent_id": None,
                "children": [
                    {
                        "id": "auth-service",
                        "node_type": "Span",
                        "name": "Authentication",
                        "parent_id": "api-gateway",
                        "children": [],
                        "entry_ids": [1, 2],
                        "start_time": "2024-01-15T10:00:00.100Z",
                        "end_time": "2024-01-15T10:00:00.150Z",
                        "duration_ms": 50,
                        "entry_count": 2,
                        "error_count": 0,
                        "level_counts": {"INFO": 2},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                    {
                        "id": "db-service",
                        "node_type": "Span",
                        "name": "Database Service",
                        "parent_id": "api-gateway",
                        "children": [
                            {
                                "id": "db-query",
                                "node_type": "Span",
                                "name": "Query Execution",
                                "parent_id": "db-service",
                                "children": [
                                    {
                                        "id": "connection-pool",
                                        "node_type": "Span",
                                        "name": "Connection Pool",
                                        "parent_id": "db-query",
                                        "children": [],
                                        "entry_ids": [10],
                                        "start_time": "2024-01-15T10:00:01.000Z",
                                        "end_time": "2024-01-15T10:00:01.100Z",
                                        "duration_ms": 100,
                                        "entry_count": 1,
                                        "error_count": 1,  # ROOT CAUSE ERROR
                                        "level_counts": {"ERROR": 1},
                                        "depth": 3,
                                        "confidence": 1.0,
                                        "relationship_evidence": [],
                                    }
                                ],
                                "entry_ids": [8, 9],
                                "start_time": "2024-01-15T10:00:00.800Z",
                                "end_time": "2024-01-15T10:00:01.200Z",
                                "duration_ms": 400,
                                "entry_count": 3,
                                "error_count": 1,
                                "level_counts": {"INFO": 2, "ERROR": 1},
                                "depth": 2,
                                "confidence": 1.0,
                                "relationship_evidence": [],
                            }
                        ],
                        "entry_ids": [5, 6, 7],
                        "start_time": "2024-01-15T10:00:00.500Z",
                        "end_time": "2024-01-15T10:00:01.500Z",
                        "duration_ms": 1000,
                        "entry_count": 6,
                        "error_count": 1,
                        "level_counts": {"INFO": 5, "ERROR": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                ],
                "entry_ids": [0],
                "start_time": "2024-01-15T10:00:00.000Z",
                "end_time": "2024-01-15T10:00:02.000Z",
                "duration_ms": 2000,
                "entry_count": 12,
                "error_count": 1,
                "level_counts": {"INFO": 11, "ERROR": 1},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 5,
        "max_depth": 3,
        "total_duration_ms": 2000,
        "concurrent_count": 1,
        "bottleneck": {
            "node_id": "db-service",
            "duration_ms": 1000,
            "percentage": 50.0,
            "depth": 1,
        },
        "error_nodes": ["api-gateway", "db-service", "db-query", "connection-pool"],
        "detection_method": "ExplicitParentId",
    }


@pytest.fixture
def minimal_fields_hierarchy():
    """Hierarchy with minimal/missing fields"""
    return {
        "roots": [
            {
                "id": "minimal",
                "children": [],
                "entry_count": 0,
                "error_count": 0,
                # Missing: node_type, name, parent_id, entry_ids, timestamps, duration, level_counts, depth, confidence
            }
        ],
        "total_nodes": 1,
        "error_nodes": [],
        # Missing: max_depth, total_duration_ms, concurrent_count, bottleneck, detection_method
    }


@pytest.fixture
def zero_duration_hierarchy():
    """Hierarchy with zero duration (instantaneous operations)"""
    return {
        "roots": [
            {
                "id": "instant",
                "node_type": "Span",
                "name": "Instant Operation",
                "parent_id": None,
                "children": [
                    {
                        "id": "instant-child",
                        "node_type": "Span",
                        "name": "Also Instant",
                        "parent_id": "instant",
                        "children": [],
                        "entry_ids": [1],
                        "start_time": "2024-01-15T10:00:00.000Z",
                        "end_time": "2024-01-15T10:00:00.000Z",
                        "duration_ms": 0,
                        "entry_count": 1,
                        "error_count": 0,
                        "level_counts": {"INFO": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    }
                ],
                "entry_ids": [0],
                "start_time": "2024-01-15T10:00:00.000Z",
                "end_time": "2024-01-15T10:00:00.000Z",
                "duration_ms": 0,
                "entry_count": 2,
                "error_count": 0,
                "level_counts": {"INFO": 2},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 2,
        "max_depth": 1,
        "total_duration_ms": 0,
        "concurrent_count": 1,
        "bottleneck": None,
        "error_nodes": [],
        "detection_method": "ExplicitParentId",
    }


@pytest.fixture
def low_confidence_hierarchy():
    """Hierarchy with very low confidence relationships"""
    return {
        "roots": [
            {
                "id": "uncertain-root",
                "node_type": "Thread",
                "name": "Uncertain Root",
                "parent_id": None,
                "children": [
                    {
                        "id": "maybe-child",
                        "node_type": "Span",
                        "name": "Maybe Related",
                        "parent_id": "uncertain-root",
                        "children": [],
                        "entry_ids": [1],
                        "start_time": "2024-01-15T10:00:05Z",
                        "end_time": "2024-01-15T10:00:06Z",
                        "duration_ms": 1000,
                        "entry_count": 1,
                        "error_count": 0,
                        "level_counts": {"INFO": 1},
                        "depth": 1,
                        "confidence": 0.1,  # Very low confidence
                        "relationship_evidence": ["Temporal proximity only"],
                    }
                ],
                "entry_ids": [0],
                "start_time": "2024-01-15T10:00:00Z",
                "end_time": "2024-01-15T10:00:10Z",
                "duration_ms": 10000,
                "entry_count": 2,
                "error_count": 0,
                "level_counts": {"INFO": 2},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 2,
        "max_depth": 1,
        "total_duration_ms": 10000,
        "concurrent_count": 1,
        "bottleneck": None,
        "error_nodes": [],
        "detection_method": "TemporalInference",
    }


@pytest.fixture
def all_errors_hierarchy():
    """Hierarchy where every node has errors"""
    return {
        "roots": [
            {
                "id": "error-root",
                "node_type": "CorrelationGroup",
                "name": "Everything Failed",
                "parent_id": None,
                "children": [
                    {
                        "id": "error-child-1",
                        "node_type": "Span",
                        "name": "Failed Child 1",
                        "parent_id": "error-root",
                        "children": [],
                        "entry_ids": [1],
                        "start_time": "2024-01-15T10:00:00.100Z",
                        "end_time": "2024-01-15T10:00:00.200Z",
                        "duration_ms": 100,
                        "entry_count": 1,
                        "error_count": 1,
                        "level_counts": {"ERROR": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                    {
                        "id": "error-child-2",
                        "node_type": "Span",
                        "name": "Failed Child 2",
                        "parent_id": "error-root",
                        "children": [],
                        "entry_ids": [2],
                        "start_time": "2024-01-15T10:00:00.200Z",
                        "end_time": "2024-01-15T10:00:00.300Z",
                        "duration_ms": 100,
                        "entry_count": 1,
                        "error_count": 1,
                        "level_counts": {"FATAL": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                ],
                "entry_ids": [0],
                "start_time": "2024-01-15T10:00:00.000Z",
                "end_time": "2024-01-15T10:00:00.500Z",
                "duration_ms": 500,
                "entry_count": 3,
                "error_count": 2,
                "level_counts": {"ERROR": 1, "FATAL": 1, "WARN": 1},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 3,
        "max_depth": 1,
        "total_duration_ms": 500,
        "concurrent_count": 1,
        "bottleneck": None,
        "error_nodes": ["error-root", "error-child-1", "error-child-2"],
        "detection_method": "ExplicitParentId",
    }


# =============================================================================
# Error Flow Analysis Tests
# =============================================================================


class TestAnalyzeErrorFlow:
    """Error flow analysis edge cases."""

    def test_empty_hierarchy(self, empty_hierarchy):
        """Analyze empty hierarchy"""
        result = analyze_error_flow(empty_hierarchy)
        assert result["has_errors"] is False
        assert result["total_error_nodes"] == 0

    def test_single_node_no_error(self, single_node_hierarchy):
        """Single node without errors"""
        result = analyze_error_flow(single_node_hierarchy)
        assert result["has_errors"] is False

    def test_single_node_with_error(self):
        """Single node that has an error"""
        hierarchy = {
            "roots": [
                {
                    "id": "error-node",
                    "node_type": "Span",
                    "children": [],
                    "error_count": 1,
                    "depth": 0,
                }
            ],
            "total_nodes": 1,
            "error_nodes": ["error-node"],
        }
        result = analyze_error_flow(hierarchy)
        assert result["has_errors"] is True

    def test_error_cascade(self, error_cascade_hierarchy):
        """Cascading errors traced to root cause"""
        result = analyze_error_flow(error_cascade_hierarchy)
        assert result["has_errors"] is True
        assert len(result["root_causes"]) >= 1
        # Should identify connection-pool as root cause (deepest error)
        root_cause = result["root_causes"][0]
        assert root_cause["node_id"] == "connection-pool"
        assert root_cause["is_leaf"] is True

    def test_all_errors(self, all_errors_hierarchy):
        """All nodes have errors"""
        result = analyze_error_flow(all_errors_hierarchy)
        assert result["has_errors"] is True
        assert result["total_error_nodes"] == 3

    def test_wide_with_scattered_errors(self, wide_hierarchy):
        """Wide hierarchy with scattered errors"""
        result = analyze_error_flow(wide_hierarchy)
        assert result["has_errors"] is True
        # Should have multiple root causes since errors are at leaf level
        assert len(result["root_causes"]) >= 1

    def test_recommendations_generated(self, error_cascade_hierarchy):
        """Recommendations are generated"""
        result = analyze_error_flow(error_cascade_hierarchy)
        assert len(result["recommendations"]) > 0

    def test_impact_summary(self, error_cascade_hierarchy):
        """Impact summary calculated"""
        result = analyze_error_flow(error_cascade_hierarchy)
        impact = result["impact_summary"]
        assert impact["total_affected_nodes"] > 0
        assert 0 <= impact["affected_percentage"] <= 100


class TestFormatErrorFlow:
    """Error flow formatting tests."""

    def test_format_no_errors(self, single_node_hierarchy):
        """Format when no errors"""
        result = analyze_error_flow(single_node_hierarchy)
        formatted = format_error_flow(result)
        assert "No errors" in formatted or "no errors" in formatted.lower()

    def test_format_with_errors(self, error_cascade_hierarchy):
        """Format with errors"""
        result = analyze_error_flow(error_cascade_hierarchy)
        formatted = format_error_flow(result)
        assert "connection-pool" in formatted
        assert len(formatted) > 50  # Should have substantial output

    def test_format_without_recommendations(self, error_cascade_hierarchy):
        """Format without recommendations section"""
        result = analyze_error_flow(error_cascade_hierarchy)
        formatted = format_error_flow(result, show_recommendations=False)
        # Should still work
        assert isinstance(formatted, str)

    def test_format_without_chains(self, error_cascade_hierarchy):
        """Format without propagation chains"""
        result = analyze_error_flow(error_cascade_hierarchy)
        formatted = format_error_flow(result, show_chains=False)
        assert isinstance(formatted, str)


# =============================================================================
# Hierarchy Summary Tests
# =============================================================================


class TestGetHierarchySummary:
    """Hierarchy summary edge cases."""

    def test_empty_summary(self, empty_hierarchy):
        """Summary of empty hierarchy"""
        summary = get_hierarchy_summary(empty_hierarchy)
        assert "0" in summary or "empty" in summary.lower()

    def test_single_node_summary(self, single_node_hierarchy):
        """Summary of single node"""
        summary = get_hierarchy_summary(single_node_hierarchy)
        assert "1" in summary
        assert "lonely-node" in summary or "Sole Survivor" in summary

    def test_wide_summary(self, wide_hierarchy):
        """Summary of wide hierarchy"""
        summary = get_hierarchy_summary(wide_hierarchy)
        assert "101" in summary  # Total nodes

    def test_deep_summary(self, deep_hierarchy):
        """Summary of deep hierarchy"""
        summary = get_hierarchy_summary(deep_hierarchy)
        assert "100" in summary  # Total nodes

    def test_multi_root_summary(self, multi_root_hierarchy):
        """Summary of multi-root hierarchy"""
        summary = get_hierarchy_summary(multi_root_hierarchy)
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_summary_shows_bottleneck(self, single_node_hierarchy):
        """Summary shows bottleneck info when present"""
        summary = get_hierarchy_summary(single_node_hierarchy)
        # Single node hierarchy has a bottleneck defined
        assert "lonely-node" in summary or "bottleneck" in summary.lower()
        # Should include the node id or bottleneck indicator
        assert len(summary) > 0

    def test_summary_with_minimal_fields(self, minimal_fields_hierarchy):
        """Summary with minimal fields doesn't crash"""
        summary = get_hierarchy_summary(minimal_fields_hierarchy)
        assert isinstance(summary, str)


# =============================================================================
# Tree Formatting Tests
# =============================================================================


class TestFormatTree:
    """Tree formatting edge cases."""

    def test_empty_tree(self, empty_hierarchy):
        """Format empty tree"""
        tree = format_tree(empty_hierarchy, use_colors=False)
        assert isinstance(tree, str)

    def test_single_node_tree(self, single_node_hierarchy):
        """Format single node tree"""
        tree = format_tree(single_node_hierarchy, use_colors=False)
        assert "lonely-node" in tree

    def test_wide_tree(self, wide_hierarchy):
        """Format wide tree"""
        tree = format_tree(wide_hierarchy, use_colors=False)
        # Uses 'name' field when available: "Root with 100 children", falls back to 'id'
        assert "Root with 100 children" in tree or "root" in tree
        # Should contain some children (names like "Child 0", "Child 1", etc.)
        assert "Child" in tree or "child-" in tree

    def test_deep_tree(self, deep_hierarchy):
        """Format deep tree"""
        tree = format_tree(deep_hierarchy, use_colors=False)
        assert "level-0" in tree

    def test_deep_tree_with_max_depth(self, deep_hierarchy):
        """Format deep tree with max_depth limit"""
        tree = format_tree(deep_hierarchy, max_depth=5, use_colors=False)
        assert "level-0" in tree
        # Should NOT show levels beyond 5
        assert "level-10" not in tree
        assert "level-50" not in tree

    def test_multi_root_tree(self, multi_root_hierarchy):
        """Format multi-root tree"""
        tree = format_tree(multi_root_hierarchy, use_colors=False)
        # Should show multiple roots (uses 'name' field: "Independent Root 0", etc.)
        assert "Independent Root 0" in tree or "root-0" in tree
        assert "Independent Root 1" in tree or "root-1" in tree

    def test_tree_compact_mode(self, single_node_hierarchy):
        """Compact mode formatting"""
        tree = format_tree(single_node_hierarchy, mode="compact", use_colors=False)
        assert "lonely-node" in tree

    def test_tree_detailed_mode(self, single_node_hierarchy):
        """Detailed mode formatting"""
        tree = format_tree(single_node_hierarchy, mode="detailed", use_colors=False)
        assert "lonely-node" in tree
        # Should have more detail
        assert "duration" in tree.lower() or "type" in tree.lower()

    def test_tree_full_mode(self, single_node_hierarchy):
        """Full mode formatting"""
        tree = format_tree(single_node_hierarchy, mode="full", use_colors=False)
        assert isinstance(tree, str)

    def test_tree_with_errors_highlighted(self, error_cascade_hierarchy):
        """Errors highlighted in tree"""
        tree = format_tree(error_cascade_hierarchy, show_errors=True, use_colors=False)
        # Error indicator should be present
        assert "❌" in tree or "error" in tree.lower() or "ERROR" in tree

    def test_tree_minimal_fields(self, minimal_fields_hierarchy):
        """Tree with minimal fields - should render node with available info"""
        tree = format_tree(minimal_fields_hierarchy, use_colors=False)
        # Should render the minimal node
        assert "minimal" in tree
        # Should produce actual output, not empty string
        assert len(tree) > 5

    def test_tree_zero_duration(self, zero_duration_hierarchy):
        """Tree with zero duration nodes"""
        tree = format_tree(zero_duration_hierarchy, use_colors=False)
        # Uses 'name' field: "Instant Operation"
        assert "Instant" in tree or "instant" in tree

    def test_tree_colors_disabled(self, single_node_hierarchy):
        """Tree with colors disabled"""
        tree = format_tree(single_node_hierarchy, use_colors=False)
        # Should not have ANSI escape codes
        assert "\x1b[" not in tree


# =============================================================================
# Waterfall Formatting Tests
# =============================================================================


class TestFormatWaterfall:
    """Waterfall formatting edge cases."""

    def test_waterfall_empty(self, empty_hierarchy):
        """Waterfall of empty hierarchy - should show empty message"""
        waterfall = format_waterfall(empty_hierarchy, width=80)
        # Empty hierarchy should produce a message indicating no data
        assert (
            "empty" in waterfall.lower()
            or "no " in waterfall.lower()
            or len(waterfall.strip()) == 0
            or "0" in waterfall
        )

    def test_waterfall_single_node(self, single_node_hierarchy):
        """Waterfall of single node"""
        waterfall = format_waterfall(single_node_hierarchy, width=80)
        assert "lonely-node" in waterfall

    def test_waterfall_wide(self, wide_hierarchy):
        """Waterfall of wide hierarchy"""
        waterfall = format_waterfall(wide_hierarchy, width=80)
        # Waterfall now prefers 'name' over 'id' for display
        assert "Root with 100" in waterfall or "root" in waterfall.lower()

    def test_waterfall_respects_width(self, single_node_hierarchy):
        """Waterfall respects width parameter"""
        narrow = format_waterfall(single_node_hierarchy, width=40)
        wide = format_waterfall(single_node_hierarchy, width=120)

        narrow_max = max(len(line) for line in narrow.split("\n"))
        wide_max = max(len(line) for line in wide.split("\n"))

        assert narrow_max <= 45  # Some margin for edge cases
        assert wide_max <= 125

    def test_waterfall_very_narrow(self, single_node_hierarchy):
        """Waterfall with very narrow width - should still render"""
        waterfall = format_waterfall(single_node_hierarchy, width=20)
        # Should produce output even with narrow width
        assert len(waterfall) > 0
        # Should render without crashing
        assert isinstance(waterfall, str)

    def test_waterfall_very_wide(self, single_node_hierarchy):
        """Waterfall with very wide width - should use available space"""
        waterfall = format_waterfall(single_node_hierarchy, width=500)
        # Should produce output
        assert len(waterfall) > 0
        # Should contain the node identifier
        assert "lonely-node" in waterfall or "Sole" in waterfall

    def test_waterfall_zero_duration(self, zero_duration_hierarchy):
        """Waterfall with zero duration - should handle gracefully"""
        waterfall = format_waterfall(zero_duration_hierarchy, width=80)
        # Should produce output even with zero duration
        assert isinstance(waterfall, str)
        assert len(waterfall) > 0

    def test_waterfall_shows_bottleneck(self, single_node_hierarchy):
        """Waterfall shows bottleneck information"""
        waterfall = format_waterfall(single_node_hierarchy, width=80)
        # Should show the bottleneck node
        assert "lonely-node" in waterfall or "Sole" in waterfall
        # Should have visual elements
        assert len(waterfall) > 20


# =============================================================================
# Flamegraph Formatting Tests (if available)
# =============================================================================


class TestFormatFlamegraph:
    """Flamegraph formatting tests."""

    def test_flamegraph_single_node(self, single_node_hierarchy):
        """Flamegraph of single node"""
        try:
            flamegraph = format_flamegraph(single_node_hierarchy, width=80)
            assert isinstance(flamegraph, str)
        except (NotImplementedError, AttributeError):
            pytest.skip("format_flamegraph not implemented")

    def test_flamegraph_deep(self, deep_hierarchy):
        """Flamegraph of deep hierarchy"""
        try:
            flamegraph = format_flamegraph(deep_hierarchy, width=80)
            assert isinstance(flamegraph, str)
        except (NotImplementedError, AttributeError):
            pytest.skip("format_flamegraph not implemented")


# =============================================================================
# Integration Tests with File-Based Hierarchies
# =============================================================================


class TestFollowThreadHierarchy:
    """Integration tests for follow_thread_hierarchy function."""

    @pytest.fixture
    def hierarchy_log_file(self):
        """Create a log file with parent-child span relationships"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            # Root span
            f.write(
                json.dumps(
                    {
                        "timestamp": "2024-01-15T10:00:00Z",
                        "level": "INFO",
                        "message": "Request started",
                        "trace_id": "trace-123",
                        "span_id": "span-root",
                        "service": "api-gateway",
                    }
                )
                + "\n"
            )

            # Child span 1
            f.write(
                json.dumps(
                    {
                        "timestamp": "2024-01-15T10:00:01Z",
                        "level": "INFO",
                        "message": "Auth check",
                        "trace_id": "trace-123",
                        "span_id": "span-auth",
                        "parent_span_id": "span-root",
                        "service": "auth-service",
                    }
                )
                + "\n"
            )

            # Child span 2
            f.write(
                json.dumps(
                    {
                        "timestamp": "2024-01-15T10:00:02Z",
                        "level": "INFO",
                        "message": "DB query",
                        "trace_id": "trace-123",
                        "span_id": "span-db",
                        "parent_span_id": "span-root",
                        "service": "db-service",
                    }
                )
                + "\n"
            )

            # Grandchild span
            f.write(
                json.dumps(
                    {
                        "timestamp": "2024-01-15T10:00:02.500Z",
                        "level": "ERROR",
                        "message": "Connection timeout",
                        "trace_id": "trace-123",
                        "span_id": "span-conn",
                        "parent_span_id": "span-db",
                        "service": "db-service",
                    }
                )
                + "\n"
            )

            temp_path = f.name

        yield temp_path
        Path(temp_path).unlink()

    def test_build_hierarchy_from_file(self, hierarchy_log_file):
        """Build hierarchy from actual log file"""
        hierarchy = follow_thread_hierarchy(files=[hierarchy_log_file], root_identifier="trace-123")
        assert "roots" in hierarchy
        assert hierarchy["total_nodes"] >= 1

    def test_hierarchy_with_max_depth(self, hierarchy_log_file):
        """Build hierarchy with max depth limit"""
        hierarchy = follow_thread_hierarchy(
            files=[hierarchy_log_file], root_identifier="trace-123", max_depth=1
        )
        assert "roots" in hierarchy

    def test_hierarchy_min_confidence(self, hierarchy_log_file):
        """Build hierarchy with min confidence filter"""
        hierarchy = follow_thread_hierarchy(
            files=[hierarchy_log_file], root_identifier="trace-123", min_confidence=0.5
        )
        assert "roots" in hierarchy

    def test_hierarchy_naming_patterns_disabled(self, hierarchy_log_file):
        """Build hierarchy without naming patterns"""
        hierarchy = follow_thread_hierarchy(
            files=[hierarchy_log_file], root_identifier="trace-123", use_naming_patterns=False
        )
        assert "roots" in hierarchy

    def test_hierarchy_temporal_inference_disabled(self, hierarchy_log_file):
        """Build hierarchy without temporal inference"""
        hierarchy = follow_thread_hierarchy(
            files=[hierarchy_log_file], root_identifier="trace-123", use_temporal_inference=False
        )
        assert "roots" in hierarchy

    def test_hierarchy_nonexistent_root(self, hierarchy_log_file):
        """Build hierarchy for non-existent root"""
        hierarchy = follow_thread_hierarchy(
            files=[hierarchy_log_file], root_identifier="does-not-exist"
        )
        # Should return empty or minimal structure
        assert hierarchy.get("total_nodes", 0) == 0 or hierarchy.get("roots", []) == []


# =============================================================================
# Special ID and Name Tests
# =============================================================================


class TestSpecialNodeIdentifiers:
    """Tests for special characters in node IDs and names."""

    def test_unicode_node_ids(self):
        """Node IDs with unicode characters"""
        hierarchy = {
            "roots": [
                {
                    "id": "日本語ノード",
                    "node_type": "Span",
                    "name": "日本語の名前",
                    "children": [],
                    "entry_count": 1,
                    "error_count": 0,
                    "depth": 0,
                    "level_counts": {"INFO": 1},
                }
            ],
            "total_nodes": 1,
            "error_nodes": [],
        }
        tree = format_tree(hierarchy, use_colors=False)
        assert "日本語" in tree

    def test_emoji_in_names(self):
        """Node names with emoji"""
        hierarchy = {
            "roots": [
                {
                    "id": "emoji-node",
                    "node_type": "Span",
                    "name": "Success 🎉✅",
                    "children": [],
                    "entry_count": 1,
                    "error_count": 0,
                    "depth": 0,
                    "level_counts": {"INFO": 1},
                }
            ],
            "total_nodes": 1,
            "error_nodes": [],
        }
        tree = format_tree(hierarchy, use_colors=False)
        assert "🎉" in tree or "Success" in tree

    def test_very_long_node_id(self):
        """Very long node ID"""
        long_id = "x" * 500
        hierarchy = {
            "roots": [
                {
                    "id": long_id,
                    "node_type": "Span",
                    "name": "Long ID Node",
                    "children": [],
                    "entry_count": 1,
                    "error_count": 0,
                    "depth": 0,
                    "level_counts": {"INFO": 1},
                }
            ],
            "total_nodes": 1,
            "error_nodes": [],
        }
        tree = format_tree(hierarchy, use_colors=False)
        # Should handle long ID (possibly truncated)
        assert isinstance(tree, str)

    def test_special_chars_in_ids(self):
        """Special characters in node IDs"""
        hierarchy = {
            "roots": [
                {
                    "id": "node/with/slashes:and:colons@at#hash",
                    "node_type": "Span",
                    "name": "Special Chars Node",
                    "children": [],
                    "entry_count": 1,
                    "error_count": 0,
                    "depth": 0,
                    "level_counts": {"INFO": 1},
                }
            ],
            "total_nodes": 1,
            "error_nodes": [],
        }
        tree = format_tree(hierarchy, use_colors=False)
        assert "Special Chars" in tree or "node/with" in tree
