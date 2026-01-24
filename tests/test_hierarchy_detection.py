"""
Unit tests for hierarchy detection and visualization.

Tests cover:
- Hierarchy building from various log formats
- Parent-child relationship detection
- Naming pattern detection
- Error flow analysis
- Tree and waterfall formatting
"""

import pytest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from logler.investigate import (
    analyze_error_flow,
    format_error_flow,
    get_hierarchy_summary,
)
from logler.tree_formatter import (
    format_tree,
    format_waterfall,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def simple_hierarchy():
    """Simple hierarchy with no errors"""
    return {
        "roots": [
            {
                "id": "root-1",
                "node_type": "CorrelationGroup",
                "name": "Main Request",
                "parent_id": None,
                "children": [
                    {
                        "id": "child-1",
                        "node_type": "Span",
                        "name": "Database Query",
                        "parent_id": "root-1",
                        "children": [],
                        "entry_ids": [],
                        "start_time": "2024-01-15T10:00:00.100Z",
                        "end_time": "2024-01-15T10:00:00.200Z",
                        "duration_ms": 100,
                        "entry_count": 5,
                        "error_count": 0,
                        "level_counts": {"INFO": 3, "DEBUG": 2},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": ["Explicit parent_span_id"],
                    },
                    {
                        "id": "child-2",
                        "node_type": "Span",
                        "name": "Cache Lookup",
                        "parent_id": "root-1",
                        "children": [],
                        "entry_ids": [],
                        "start_time": "2024-01-15T10:00:00.250Z",
                        "end_time": "2024-01-15T10:00:00.300Z",
                        "duration_ms": 50,
                        "entry_count": 3,
                        "error_count": 0,
                        "level_counts": {"INFO": 2, "DEBUG": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": ["Explicit parent_span_id"],
                    },
                ],
                "entry_ids": [],
                "start_time": "2024-01-15T10:00:00.000Z",
                "end_time": "2024-01-15T10:00:00.500Z",
                "duration_ms": 500,
                "entry_count": 10,
                "error_count": 0,
                "level_counts": {"INFO": 8, "DEBUG": 2},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 3,
        "max_depth": 1,
        "total_duration_ms": 500,
        "concurrent_count": 1,
        "bottleneck": {"node_id": "child-1", "duration_ms": 100, "percentage": 20.0, "depth": 1},
        "error_nodes": [],
        "detection_method": "ExplicitParentId",
    }


@pytest.fixture
def hierarchy_with_errors():
    """Hierarchy with cascading errors"""
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
                        "entry_ids": [],
                        "start_time": "2024-01-15T10:00:00.100Z",
                        "end_time": "2024-01-15T10:00:00.150Z",
                        "duration_ms": 50,
                        "entry_count": 3,
                        "error_count": 0,
                        "level_counts": {"INFO": 3},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                    {
                        "id": "product-service",
                        "node_type": "Span",
                        "name": "Product Service",
                        "parent_id": "api-gateway",
                        "children": [
                            {
                                "id": "cache-update",
                                "node_type": "Span",
                                "name": "Cache Update",
                                "parent_id": "product-service",
                                "children": [
                                    {
                                        "id": "redis-write",
                                        "node_type": "Span",
                                        "name": "Redis Write",
                                        "parent_id": "cache-update",
                                        "children": [],
                                        "entry_ids": [],
                                        "start_time": "2024-01-15T10:00:01.000Z",
                                        "end_time": "2024-01-15T10:00:01.050Z",
                                        "duration_ms": 50,
                                        "entry_count": 2,
                                        "error_count": 1,
                                        "level_counts": {"ERROR": 1, "INFO": 1},
                                        "depth": 3,
                                        "confidence": 1.0,
                                        "relationship_evidence": [],
                                    }
                                ],
                                "entry_ids": [],
                                "start_time": "2024-01-15T10:00:00.800Z",
                                "end_time": "2024-01-15T10:00:01.100Z",
                                "duration_ms": 300,
                                "entry_count": 4,
                                "error_count": 1,
                                "level_counts": {"ERROR": 1, "INFO": 3},
                                "depth": 2,
                                "confidence": 1.0,
                                "relationship_evidence": [],
                            }
                        ],
                        "entry_ids": [],
                        "start_time": "2024-01-15T10:00:00.200Z",
                        "end_time": "2024-01-15T10:00:01.200Z",
                        "duration_ms": 1000,
                        "entry_count": 10,
                        "error_count": 1,
                        "level_counts": {"ERROR": 1, "INFO": 8, "WARN": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                ],
                "entry_ids": [],
                "start_time": "2024-01-15T10:00:00.000Z",
                "end_time": "2024-01-15T10:00:01.500Z",
                "duration_ms": 1500,
                "entry_count": 20,
                "error_count": 1,
                "level_counts": {"ERROR": 1, "INFO": 17, "WARN": 1, "DEBUG": 1},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 5,
        "max_depth": 3,
        "total_duration_ms": 1500,
        "concurrent_count": 1,
        "bottleneck": {
            "node_id": "product-service",
            "duration_ms": 1000,
            "percentage": 66.7,
            "depth": 1,
        },
        "error_nodes": ["api-gateway", "product-service", "cache-update", "redis-write"],
        "detection_method": "ExplicitParentId",
    }


@pytest.fixture
def deep_hierarchy():
    """Deep hierarchy for testing max_depth"""

    def make_child(id_prefix, depth, max_depth):
        node = {
            "id": f"{id_prefix}-depth-{depth}",
            "node_type": "Span",
            "name": f"Level {depth}",
            "parent_id": f"{id_prefix}-depth-{depth-1}" if depth > 0 else None,
            "children": [],
            "entry_ids": [],
            "start_time": f"2024-01-15T10:00:00.{depth:03d}Z",
            "end_time": f"2024-01-15T10:00:00.{depth+10:03d}Z",
            "duration_ms": 10 * (max_depth - depth + 1),
            "entry_count": 1,
            "error_count": 0,
            "level_counts": {"INFO": 1},
            "depth": depth,
            "confidence": 1.0,
            "relationship_evidence": [],
        }
        if depth < max_depth:
            node["children"] = [make_child(id_prefix, depth + 1, max_depth)]
        return node

    root = make_child("node", 0, 5)
    return {
        "roots": [root],
        "total_nodes": 6,
        "max_depth": 5,
        "total_duration_ms": 60,
        "concurrent_count": 1,
        "bottleneck": None,
        "error_nodes": [],
        "detection_method": "NamingPattern",
    }


# =============================================================================
# Tests for Error Flow Analysis
# =============================================================================


class TestAnalyzeErrorFlow:
    """Tests for analyze_error_flow function"""

    def test_no_errors(self, simple_hierarchy):
        """Test hierarchy with no errors"""
        result = analyze_error_flow(simple_hierarchy)

        assert result["has_errors"] is False
        assert result["total_error_nodes"] == 0
        assert result["root_causes"] == []
        assert result["propagation_chains"] == []

    def test_cascading_errors(self, hierarchy_with_errors):
        """Test cascading error detection"""
        result = analyze_error_flow(hierarchy_with_errors)

        assert result["has_errors"] is True
        assert result["total_error_nodes"] == 4

        # Root cause should be the leaf node with error (redis-write)
        assert len(result["root_causes"]) >= 1
        root_cause = result["root_causes"][0]
        assert root_cause["node_id"] == "redis-write"
        assert root_cause["is_leaf"] is True
        assert root_cause["confidence"] == 1.0

    def test_error_path(self, hierarchy_with_errors):
        """Test error path is correctly traced"""
        result = analyze_error_flow(hierarchy_with_errors)

        root_cause = result["root_causes"][0]
        path = root_cause["path"]

        # Path should go from root to leaf
        assert path[0] == "api-gateway"
        assert path[-1] == "redis-write"
        assert "cache-update" in path

    def test_propagation_chains(self, hierarchy_with_errors):
        """Test error propagation chains"""
        result = analyze_error_flow(hierarchy_with_errors)

        chains = result["propagation_chains"]
        assert len(chains) >= 1

        chain = chains[0]
        assert chain["root_cause"] == "redis-write"
        assert chain["propagation_type"] == "upward"
        assert chain["total_affected"] >= 2

    def test_recommendations(self, hierarchy_with_errors):
        """Test recommendations are generated"""
        result = analyze_error_flow(hierarchy_with_errors)

        recommendations = result["recommendations"]
        assert len(recommendations) > 0

        # Should recommend investigating root cause first
        assert any("redis-write" in rec for rec in recommendations)

    def test_impact_summary(self, hierarchy_with_errors):
        """Test impact summary calculation"""
        result = analyze_error_flow(hierarchy_with_errors)

        impact = result["impact_summary"]
        assert impact["total_affected_nodes"] == 4
        assert impact["affected_percentage"] == 80.0  # 4 of 5 nodes
        assert impact["max_propagation_depth"] == 3


class TestFormatErrorFlow:
    """Tests for format_error_flow function"""

    def test_no_errors_format(self, simple_hierarchy):
        """Test formatting when no errors"""
        result = analyze_error_flow(simple_hierarchy)
        formatted = format_error_flow(result)

        assert "No errors detected" in formatted

    def test_error_flow_format(self, hierarchy_with_errors):
        """Test error flow formatting"""
        result = analyze_error_flow(hierarchy_with_errors)
        formatted = format_error_flow(result)

        assert "ERROR FLOW ANALYSIS" in formatted
        assert "ROOT CAUSE" in formatted
        assert "redis-write" in formatted
        assert "RECOMMENDATIONS" in formatted

    def test_format_without_recommendations(self, hierarchy_with_errors):
        """Test formatting without recommendations"""
        result = analyze_error_flow(hierarchy_with_errors)
        formatted = format_error_flow(result, show_recommendations=False)

        assert "RECOMMENDATIONS" not in formatted

    def test_format_without_chains(self, hierarchy_with_errors):
        """Test formatting without propagation chains"""
        result = analyze_error_flow(hierarchy_with_errors)
        formatted = format_error_flow(result, show_chains=False)

        assert "ERROR PROPAGATION" not in formatted


# =============================================================================
# Tests for Hierarchy Summary
# =============================================================================


class TestGetHierarchySummary:
    """Tests for get_hierarchy_summary function"""

    def test_basic_summary(self, simple_hierarchy):
        """Test basic hierarchy summary"""
        summary = get_hierarchy_summary(simple_hierarchy)

        assert "Thread Hierarchy Summary" in summary
        assert "Total nodes: 3" in summary
        assert "Max depth: 1" in summary
        assert "ExplicitParentId" in summary

    def test_summary_with_errors(self, hierarchy_with_errors):
        """Test summary shows error information with count"""
        summary = get_hierarchy_summary(hierarchy_with_errors)

        # Should mention errors (4 error nodes in the hierarchy)
        assert "error" in summary.lower(), "Summary should mention errors"
        # Should show node count
        assert "5" in summary or "nodes" in summary.lower()

    def test_summary_with_bottleneck(self, simple_hierarchy):
        """Test summary shows bottleneck"""
        summary = get_hierarchy_summary(simple_hierarchy)

        assert "BOTTLENECK" in summary
        assert "child-1" in summary


# =============================================================================
# Tests for Tree Formatting
# =============================================================================


class TestFormatTree:
    """Tests for format_tree function"""

    def test_compact_mode(self, simple_hierarchy):
        """Test compact tree formatting"""
        tree = format_tree(simple_hierarchy, mode="compact", use_colors=False)

        # Uses 'name' field when available: "Main Request", "Database Query", "Cache Lookup"
        assert "Main Request" in tree or "root-1" in tree
        assert "Database Query" in tree or "child-1" in tree
        assert "Cache Lookup" in tree or "child-2" in tree
        assert "entries" in tree

    def test_detailed_mode(self, simple_hierarchy):
        """Test detailed tree formatting"""
        tree = format_tree(simple_hierarchy, mode="detailed", use_colors=False)

        assert "type=" in tree
        assert "duration=" in tree

    def test_full_mode(self, simple_hierarchy):
        """Test full tree formatting"""
        tree = format_tree(simple_hierarchy, mode="full", use_colors=False)

        assert "Levels:" in tree

    def test_max_depth_limiting(self, deep_hierarchy):
        """Test max_depth limits tree display"""
        tree = format_tree(deep_hierarchy, max_depth=2, use_colors=False)

        # Should show depth 0 and 1 (uses 'name' field: "Level 0", "Level 1")
        assert "Level 0" in tree or "depth-0" in tree
        assert "Level 1" in tree or "depth-1" in tree
        # Should not show depth 2+ (neither name "Level 2" nor id "depth-2")
        assert "Level 2" not in tree and "depth-2" not in tree

    def test_error_highlighting(self, hierarchy_with_errors):
        """Test errors are highlighted"""
        tree = format_tree(
            hierarchy_with_errors, mode="compact", show_errors=True, use_colors=False
        )

        # Error marker should appear
        assert "❌" in tree or "error" in tree.lower()


# =============================================================================
# Tests for Waterfall Formatting
# =============================================================================


class TestFormatWaterfall:
    """Tests for format_waterfall function"""

    def test_basic_waterfall(self, simple_hierarchy):
        """Test basic waterfall formatting"""
        waterfall = format_waterfall(simple_hierarchy, width=80)

        assert "Timeline" in waterfall
        assert "█" in waterfall  # Bar character
        # Waterfall now prefers 'name' over 'id' for display
        assert "Main Request" in waterfall or "root-1" in waterfall

    def test_waterfall_shows_duration(self, simple_hierarchy):
        """Test waterfall shows duration labels"""
        waterfall = format_waterfall(simple_hierarchy, width=80)

        assert "ms" in waterfall or "500" in waterfall

    def test_waterfall_bottleneck(self, simple_hierarchy):
        """Test waterfall shows bottleneck"""
        waterfall = format_waterfall(simple_hierarchy, width=80)

        # Bottleneck info should be shown
        assert "Bottleneck" in waterfall or "child-1" in waterfall

    def test_waterfall_respects_width(self, simple_hierarchy):
        """Test waterfall respects width parameter"""
        waterfall_narrow = format_waterfall(simple_hierarchy, width=60)
        waterfall_wide = format_waterfall(simple_hierarchy, width=100)

        # Wider waterfall should have longer lines
        narrow_max_len = max(len(line) for line in waterfall_narrow.split("\n"))
        wide_max_len = max(len(line) for line in waterfall_wide.split("\n"))

        assert narrow_max_len <= 61  # Allow 1 char margin
        assert wide_max_len <= 101


# =============================================================================
# Tests for Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_empty_hierarchy(self):
        """Test handling of empty hierarchy"""
        empty = {"roots": [], "total_nodes": 0, "error_nodes": []}

        result = analyze_error_flow(empty)
        assert result["has_errors"] is False

        summary = get_hierarchy_summary(empty)
        assert "Total nodes: 0" in summary

    def test_single_node_hierarchy(self):
        """Test hierarchy with single node"""
        single = {
            "roots": [
                {
                    "id": "single",
                    "node_type": "Span",
                    "children": [],
                    "entry_count": 1,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 100,
                    "start_time": "2024-01-15T10:00:00Z",
                    "end_time": "2024-01-15T10:00:00.100Z",
                    "level_counts": {"INFO": 1},
                }
            ],
            "total_nodes": 1,
            "max_depth": 0,
            "total_duration_ms": 100,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "ExplicitParentId",
        }

        tree = format_tree(single, use_colors=False)
        assert "single" in tree

    def test_multiple_roots(self):
        """Test hierarchy with multiple roots"""
        multi_root = {
            "roots": [
                {
                    "id": "root-a",
                    "node_type": "Thread",
                    "children": [],
                    "entry_count": 5,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 100,
                    "level_counts": {"INFO": 5},
                },
                {
                    "id": "root-b",
                    "node_type": "Thread",
                    "children": [],
                    "entry_count": 3,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 50,
                    "level_counts": {"INFO": 3},
                },
            ],
            "total_nodes": 2,
            "max_depth": 0,
            "total_duration_ms": 100,
            "concurrent_count": 2,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "Mixed",
        }

        tree = format_tree(multi_root, use_colors=False)
        assert "root-a" in tree
        assert "root-b" in tree

    def test_orphaned_span_missing_parent(self):
        """Test hierarchy with orphaned spans (parent_id references non-existent node)"""
        orphaned = {
            "roots": [
                {
                    "id": "main",
                    "node_type": "Thread",
                    "parent_id": None,
                    "children": [
                        {
                            "id": "orphan-child",
                            "node_type": "Span",
                            "parent_id": "non-existent-parent",  # Orphaned!
                            "children": [],
                            "entry_count": 2,
                            "error_count": 0,
                            "depth": 1,
                            "duration_ms": 50,
                            "level_counts": {"INFO": 2},
                            "confidence": 0.5,  # Low confidence due to missing parent
                            "relationship_evidence": ["Temporal proximity (parent missing)"],
                        }
                    ],
                    "entry_count": 10,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 200,
                    "level_counts": {"INFO": 10},
                }
            ],
            "total_nodes": 2,
            "max_depth": 1,
            "total_duration_ms": 200,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "Temporal",
        }

        # Should still render without crashing
        tree = format_tree(orphaned, mode="detailed", show_confidence=True, use_colors=False)
        assert "orphan-child" in tree
        assert "main" in tree
        # Low confidence should be shown
        assert "0.5" in tree or "confidence" in tree.lower()

    def test_very_deep_hierarchy(self):
        """Test hierarchy with >50 levels of depth"""

        # Build a very deep hierarchy
        def build_deep_node(depth, max_depth):
            node = {
                "id": f"depth-{depth}",
                "node_type": "Span",
                "parent_id": f"depth-{depth-1}" if depth > 0 else None,
                "children": [],
                "entry_count": 1,
                "error_count": 0,
                "depth": depth,
                "duration_ms": 10,
                "level_counts": {"INFO": 1},
                "confidence": 1.0,
                "relationship_evidence": [],
            }
            if depth < max_depth:
                node["children"] = [build_deep_node(depth + 1, max_depth)]
            return node

        deep = {
            "roots": [build_deep_node(0, 55)],  # 56 levels deep
            "total_nodes": 56,
            "max_depth": 55,
            "total_duration_ms": 560,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "ExplicitParentId",
        }

        # Should render without stack overflow
        tree = format_tree(deep, mode="compact", use_colors=False)
        assert "depth-0" in tree
        assert "depth-55" in tree

        # Test with max_depth limiting
        tree_limited = format_tree(deep, max_depth=5, use_colors=False)
        assert "depth-0" in tree_limited
        assert "depth-4" in tree_limited
        assert "depth-5" not in tree_limited

        # Summary should work
        summary = get_hierarchy_summary(deep)
        assert "Max depth: 55" in summary

    def test_very_wide_hierarchy(self):
        """Test hierarchy with >100 children at one level"""
        children = []
        for i in range(150):
            children.append(
                {
                    "id": f"child-{i:03d}",
                    "node_type": "Span",
                    "parent_id": "root",
                    "children": [],
                    "entry_count": 1,
                    "error_count": 1 if i % 10 == 0 else 0,  # Every 10th has error
                    "depth": 1,
                    "duration_ms": 10 + i,
                    "level_counts": {"INFO": 1} if i % 10 != 0 else {"ERROR": 1},
                    "confidence": 1.0,
                    "relationship_evidence": [],
                }
            )

        wide = {
            "roots": [
                {
                    "id": "root",
                    "node_type": "Thread",
                    "parent_id": None,
                    "children": children,
                    "entry_count": 150,
                    "error_count": 15,
                    "depth": 0,
                    "duration_ms": 5000,
                    "level_counts": {"INFO": 135, "ERROR": 15},
                }
            ],
            "total_nodes": 151,
            "max_depth": 1,
            "total_duration_ms": 5000,
            "concurrent_count": 150,
            "bottleneck": {
                "node_id": "child-149",
                "duration_ms": 159,
                "percentage": 3.2,
                "depth": 1,
            },
            "error_nodes": [f"child-{i*10:03d}" for i in range(15)],
            "detection_method": "ExplicitParentId",
        }

        # Should render without issues
        tree = format_tree(wide, mode="compact", use_colors=False)
        assert "root" in tree
        assert "child-000" in tree
        assert "child-149" in tree

        # Error flow should handle many error nodes
        error_flow = analyze_error_flow(wide)
        assert error_flow["has_errors"] is True
        assert len(error_flow.get("root_causes", [])) > 0

        # Summary should work
        summary = get_hierarchy_summary(wide)
        assert "Total nodes: 151" in summary

    def test_missing_timestamps(self):
        """Test hierarchy with missing timestamp data"""
        no_timestamps = {
            "roots": [
                {
                    "id": "root",
                    "node_type": "Thread",
                    "parent_id": None,
                    "children": [
                        {
                            "id": "child",
                            "node_type": "Span",
                            "parent_id": "root",
                            "children": [],
                            "entry_count": 5,
                            "error_count": 0,
                            "depth": 1,
                            "duration_ms": None,  # No duration!
                            "start_time": None,  # No start!
                            "end_time": None,  # No end!
                            "level_counts": {"INFO": 5},
                            "confidence": 0.6,
                            "relationship_evidence": ["Naming pattern"],
                        }
                    ],
                    "entry_count": 10,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": None,
                    "start_time": None,
                    "end_time": None,
                    "level_counts": {"INFO": 10},
                }
            ],
            "total_nodes": 2,
            "max_depth": 1,
            "total_duration_ms": None,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "NamingPattern",
        }

        # Tree should still work
        tree = format_tree(no_timestamps, mode="compact", use_colors=False)
        assert "root" in tree
        assert "child" in tree

        # Waterfall should handle gracefully
        waterfall = format_waterfall(no_timestamps, width=80)
        # Should return a message about no timing info
        assert "No timing" in waterfall or "root" in waterfall

    def test_all_errors_hierarchy(self):
        """Test hierarchy where every node has errors"""
        all_errors = {
            "roots": [
                {
                    "id": "error-root",
                    "node_type": "Thread",
                    "parent_id": None,
                    "children": [
                        {
                            "id": "error-child-1",
                            "node_type": "Span",
                            "parent_id": "error-root",
                            "children": [
                                {
                                    "id": "error-grandchild",
                                    "node_type": "Span",
                                    "parent_id": "error-child-1",
                                    "children": [],
                                    "entry_count": 3,
                                    "error_count": 3,
                                    "depth": 2,
                                    "duration_ms": 50,
                                    "start_time": "2024-01-15T10:00:00.100Z",
                                    "level_counts": {"ERROR": 3},
                                    "confidence": 1.0,
                                    "relationship_evidence": [],
                                }
                            ],
                            "entry_count": 5,
                            "error_count": 5,
                            "depth": 1,
                            "duration_ms": 100,
                            "start_time": "2024-01-15T10:00:00.050Z",
                            "level_counts": {"ERROR": 5},
                            "confidence": 1.0,
                            "relationship_evidence": [],
                        },
                        {
                            "id": "error-child-2",
                            "node_type": "Span",
                            "parent_id": "error-root",
                            "children": [],
                            "entry_count": 2,
                            "error_count": 2,
                            "depth": 1,
                            "duration_ms": 30,
                            "start_time": "2024-01-15T10:00:00.200Z",
                            "level_counts": {"ERROR": 2},
                            "confidence": 1.0,
                            "relationship_evidence": [],
                        },
                    ],
                    "entry_count": 10,
                    "error_count": 10,
                    "depth": 0,
                    "duration_ms": 300,
                    "start_time": "2024-01-15T10:00:00.000Z",
                    "level_counts": {"ERROR": 10},
                }
            ],
            "total_nodes": 4,
            "max_depth": 2,
            "total_duration_ms": 300,
            "concurrent_count": 2,
            "bottleneck": {
                "node_id": "error-child-1",
                "duration_ms": 100,
                "percentage": 33.3,
                "depth": 1,
            },
            "error_nodes": ["error-root", "error-child-1", "error-child-2", "error-grandchild"],
            "detection_method": "ExplicitParentId",
        }

        # Error flow should identify root causes
        error_flow = analyze_error_flow(all_errors)
        assert error_flow["has_errors"] is True
        assert len(error_flow.get("root_causes", [])) > 0
        # Impact should be 100%
        impact = error_flow.get("impact_summary", {})
        assert impact.get("affected_percentage", 0) == 100.0

        # Tree should show all errors
        tree = format_tree(all_errors, show_errors=True, use_colors=False)
        assert "❌" in tree or "error" in tree.lower()

        # Formatted error flow should have recommendations
        formatted = format_error_flow(error_flow)
        assert "recommendation" in formatted.lower() or "Error Flow" in formatted

    def test_unicode_in_node_names(self):
        """Test hierarchy with unicode characters in names"""
        unicode_hierarchy = {
            "roots": [
                {
                    "id": "主要スレッド",  # Japanese
                    "node_type": "Thread",
                    "parent_id": None,
                    "children": [
                        {
                            "id": "子プロセス-αβγ",  # Mixed
                            "node_type": "Span",
                            "parent_id": "主要スレッド",
                            "children": [],
                            "entry_count": 5,
                            "error_count": 0,
                            "depth": 1,
                            "duration_ms": 100,
                            "level_counts": {"INFO": 5},
                            "name": "データベースクエリ 🔍",  # With emoji
                            "confidence": 1.0,
                            "relationship_evidence": [],
                        }
                    ],
                    "entry_count": 10,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 200,
                    "level_counts": {"INFO": 10},
                    "name": "メインリクエスト",
                }
            ],
            "total_nodes": 2,
            "max_depth": 1,
            "total_duration_ms": 200,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "ExplicitParentId",
        }

        # Should handle unicode without crashing
        tree = format_tree(unicode_hierarchy, mode="detailed", use_colors=False)
        # Uses 'name' field: "メインリクエスト" instead of id "主要スレッド"
        assert "メインリクエスト" in tree or "主要スレッド" in tree
        # Child uses 'name' field: "データベースクエリ 🔍" instead of id "子プロセス-αβγ"
        assert "データベースクエリ" in tree or "子プロセス" in tree

        summary = get_hierarchy_summary(unicode_hierarchy)
        assert "Total nodes: 2" in summary


# =============================================================================
# Tests for Detection Methods
# =============================================================================


class TestDetectionMethods:
    """Tests for different hierarchy detection methods"""

    def test_explicit_parent_span_id_detection(self):
        """Test hierarchy built from explicit parent_span_id"""
        explicit = {
            "roots": [
                {
                    "id": "span-000",
                    "node_type": "Span",
                    "parent_id": None,
                    "children": [
                        {
                            "id": "span-001",
                            "node_type": "Span",
                            "parent_id": "span-000",
                            "children": [],
                            "entry_count": 5,
                            "error_count": 0,
                            "depth": 1,
                            "duration_ms": 50,
                            "level_counts": {"INFO": 5},
                            "confidence": 1.0,  # Should be 1.0 for explicit
                            "relationship_evidence": ["Explicit parent_span_id"],
                        }
                    ],
                    "entry_count": 10,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 100,
                    "level_counts": {"INFO": 10},
                }
            ],
            "total_nodes": 2,
            "max_depth": 1,
            "total_duration_ms": 100,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "Explicit",
        }

        tree = format_tree(explicit, mode="detailed", show_confidence=True, use_colors=False)
        assert "1.0" in tree or "confidence" in tree.lower()
        summary = get_hierarchy_summary(explicit)
        assert "Explicit" in summary

    def test_naming_pattern_detection(self):
        """Test hierarchy built from naming patterns (worker-1.task-a)"""
        naming = {
            "roots": [
                {
                    "id": "worker-1",
                    "node_type": "Thread",
                    "parent_id": None,
                    "children": [
                        {
                            "id": "worker-1.task-a",
                            "node_type": "Thread",
                            "parent_id": "worker-1",
                            "children": [
                                {
                                    "id": "worker-1.task-a.subtask",
                                    "node_type": "Thread",
                                    "parent_id": "worker-1.task-a",
                                    "children": [],
                                    "entry_count": 2,
                                    "error_count": 0,
                                    "depth": 2,
                                    "duration_ms": 20,
                                    "level_counts": {"INFO": 2},
                                    "confidence": 0.8,  # Lower for naming pattern
                                    "relationship_evidence": ["Naming pattern: dot-separated"],
                                }
                            ],
                            "entry_count": 5,
                            "error_count": 0,
                            "depth": 1,
                            "duration_ms": 50,
                            "level_counts": {"INFO": 5},
                            "confidence": 0.8,
                            "relationship_evidence": ["Naming pattern: dot-separated"],
                        }
                    ],
                    "entry_count": 10,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 100,
                    "level_counts": {"INFO": 10},
                }
            ],
            "total_nodes": 3,
            "max_depth": 2,
            "total_duration_ms": 100,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "NamingPattern",
        }

        tree = format_tree(naming, mode="detailed", show_confidence=True, use_colors=False)
        assert "worker-1.task-a" in tree
        summary = get_hierarchy_summary(naming)
        assert "NamingPattern" in summary

    def test_temporal_inference_detection(self):
        """Test hierarchy built from temporal proximity"""
        temporal = {
            "roots": [
                {
                    "id": "main",
                    "node_type": "Thread",
                    "parent_id": None,
                    "children": [
                        {
                            "id": "async-task-1",
                            "node_type": "Thread",
                            "parent_id": "main",
                            "children": [],
                            "entry_count": 3,
                            "error_count": 0,
                            "depth": 1,
                            "duration_ms": 30,
                            "start_time": "2024-01-15T10:00:00.001Z",  # Started 1ms after parent
                            "level_counts": {"INFO": 3},
                            "confidence": 0.6,  # Lower for temporal
                            "relationship_evidence": ["Temporal proximity: 1ms after parent"],
                        }
                    ],
                    "entry_count": 10,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 100,
                    "start_time": "2024-01-15T10:00:00.000Z",
                    "level_counts": {"INFO": 10},
                }
            ],
            "total_nodes": 2,
            "max_depth": 1,
            "total_duration_ms": 100,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "Temporal",
        }

        tree = format_tree(temporal, mode="detailed", show_confidence=True, use_colors=False)
        assert "async-task-1" in tree
        summary = get_hierarchy_summary(temporal)
        assert "Temporal" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
