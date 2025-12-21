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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

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
                        "relationship_evidence": ["Explicit parent_span_id"]
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
                        "relationship_evidence": ["Explicit parent_span_id"]
                    }
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
                "relationship_evidence": []
            }
        ],
        "total_nodes": 3,
        "max_depth": 1,
        "total_duration_ms": 500,
        "concurrent_count": 1,
        "bottleneck": {
            "node_id": "child-1",
            "duration_ms": 100,
            "percentage": 20.0,
            "depth": 1
        },
        "error_nodes": [],
        "detection_method": "ExplicitParentId"
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
                        "relationship_evidence": []
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
                                        "relationship_evidence": []
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
                                "relationship_evidence": []
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
                        "relationship_evidence": []
                    }
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
                "relationship_evidence": []
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
            "depth": 1
        },
        "error_nodes": ["api-gateway", "product-service", "cache-update", "redis-write"],
        "detection_method": "ExplicitParentId"
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
            "relationship_evidence": []
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
        "detection_method": "NamingPattern"
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
        """Test summary shows error information"""
        summary = get_hierarchy_summary(hierarchy_with_errors)

        assert "Errors in" in summary or "error" in summary.lower()

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

        assert "root-1" in tree
        assert "child-1" in tree
        assert "child-2" in tree
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

        # Should show depth 0 and 1
        assert "depth-0" in tree
        assert "depth-1" in tree
        # Should not show depth 2+
        assert "depth-2" not in tree

    def test_error_highlighting(self, hierarchy_with_errors):
        """Test errors are highlighted"""
        tree = format_tree(
            hierarchy_with_errors,
            mode="compact",
            show_errors=True,
            use_colors=False
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
        assert "root-1" in waterfall

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
        narrow_max_len = max(len(line) for line in waterfall_narrow.split('\n'))
        wide_max_len = max(len(line) for line in waterfall_wide.split('\n'))

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
            "roots": [{
                "id": "single",
                "node_type": "Span",
                "children": [],
                "entry_count": 1,
                "error_count": 0,
                "depth": 0,
                "duration_ms": 100,
                "start_time": "2024-01-15T10:00:00Z",
                "end_time": "2024-01-15T10:00:00.100Z",
                "level_counts": {"INFO": 1}
            }],
            "total_nodes": 1,
            "max_depth": 0,
            "total_duration_ms": 100,
            "concurrent_count": 1,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "ExplicitParentId"
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
                    "level_counts": {"INFO": 5}
                },
                {
                    "id": "root-b",
                    "node_type": "Thread",
                    "children": [],
                    "entry_count": 3,
                    "error_count": 0,
                    "depth": 0,
                    "duration_ms": 50,
                    "level_counts": {"INFO": 3}
                }
            ],
            "total_nodes": 2,
            "max_depth": 0,
            "total_duration_ms": 100,
            "concurrent_count": 2,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "Mixed"
        }

        tree = format_tree(multi_root, use_colors=False)
        assert "root-a" in tree
        assert "root-b" in tree


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
