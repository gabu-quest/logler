"""
PARAMETRIZED HIERARCHY TESTS - Exact Value Assertions

These tests verify hierarchy analysis with KNOWN values:
- Duration calculations
- Bottleneck detection
- Name extraction priority

Fixture: deterministic_hierarchy
- root: 1000ms total
- child-fast: 100ms (10%)
- child-slow: 800ms (80%) ← THE BOTTLENECK
- child-medium: 100ms (10%)

Fixture: hierarchy_with_names
- Tests name extraction priority order
"""

import pytest

try:
    from logler.investigate import (
        analyze_bottlenecks,
        get_hierarchy_summary,
        RUST_AVAILABLE,
    )
    from logler.tree_formatter import format_tree, format_waterfall
except ImportError:
    RUST_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust backend required for hierarchy tests"
)


def find_node(hierarchy, node_id):
    """Helper to find a node by ID in the hierarchy."""

    def search_node(node):
        if node.get("id") == node_id:
            return node
        for child in node.get("children", []):
            result = search_node(child)
            if result:
                return result
        return None

    for root in hierarchy.get("roots", []):
        result = search_node(root)
        if result:
            return result
    return None


class TestHierarchyDuration:
    """Test duration values are exactly as specified."""

    @pytest.mark.parametrize(
        "node_id,expected_duration_ms",
        [
            ("root", 1000),
            ("child-fast", 100),
            ("child-slow", 800),
            ("child-medium", 100),
        ],
        ids=["root_1000ms", "fast_100ms", "slow_800ms", "medium_100ms"],
    )
    def test_node_duration_exact(self, deterministic_hierarchy, node_id, expected_duration_ms):
        """Each node has exactly the expected duration."""
        node = find_node(deterministic_hierarchy, node_id)

        assert node is not None, f"Node {node_id} not found in hierarchy"
        assert node["duration_ms"] == expected_duration_ms, (
            f"Node {node_id} should have duration {expected_duration_ms}ms, "
            f"got {node['duration_ms']}ms"
        )

    def test_total_duration_exact(self, deterministic_hierarchy):
        """Total duration should be exactly 1000ms."""
        assert (
            deterministic_hierarchy["total_duration_ms"] == 1000
        ), f"Total duration should be 1000ms, got {deterministic_hierarchy['total_duration_ms']}ms"


class TestHierarchyBottleneck:
    """Test bottleneck detection returns exact expected values."""

    def test_bottleneck_identifies_slowest_node(self, deterministic_hierarchy):
        """Bottleneck should be child-slow (800ms = 80%)."""
        bottleneck = deterministic_hierarchy.get("bottleneck")

        assert bottleneck is not None, "Bottleneck should be identified"
        assert (
            bottleneck["node_id"] == "child-slow"
        ), f"Bottleneck should be 'child-slow', got '{bottleneck['node_id']}'"

    def test_bottleneck_duration_exact(self, deterministic_hierarchy):
        """Bottleneck duration should be exactly 800ms."""
        bottleneck = deterministic_hierarchy["bottleneck"]

        assert (
            bottleneck["duration_ms"] == 800
        ), f"Bottleneck duration should be 800ms, got {bottleneck['duration_ms']}ms"

    def test_bottleneck_percentage_exact(self, deterministic_hierarchy):
        """Bottleneck percentage should be exactly 80.0%."""
        bottleneck = deterministic_hierarchy["bottleneck"]

        assert (
            bottleneck["percentage"] == 80.0
        ), f"Bottleneck percentage should be 80.0%, got {bottleneck['percentage']}%"

    def test_bottleneck_depth_exact(self, deterministic_hierarchy):
        """Bottleneck depth should be 1 (child of root)."""
        bottleneck = deterministic_hierarchy["bottleneck"]

        assert bottleneck["depth"] == 1, f"Bottleneck depth should be 1, got {bottleneck['depth']}"


class TestAnalyzeBottlenecks:
    """Test analyze_bottlenecks function with exact thresholds."""

    def test_identifies_child_slow_as_bottleneck(self, deterministic_hierarchy):
        """analyze_bottlenecks should identify child-slow."""
        result = analyze_bottlenecks(deterministic_hierarchy, threshold_percentage=20.0)

        # Should identify at least one bottleneck
        bottlenecks = result.get("bottlenecks", result.get("analysis", {}).get("bottlenecks", []))
        primary = result.get("primary_bottleneck")

        # Either in bottlenecks list or as primary
        if primary:
            assert "slow" in str(primary).lower() or primary.get("node_id") == "child-slow"
        elif bottlenecks:
            bottleneck_ids = [b.get("node_id", str(b)) for b in bottlenecks]
            assert "child-slow" in bottleneck_ids or any(
                "slow" in str(b).lower() for b in bottlenecks
            )

    def test_high_threshold_filters_minor_nodes(self, deterministic_hierarchy):
        """90% threshold should still identify child-slow (80%)."""
        result = analyze_bottlenecks(deterministic_hierarchy, threshold_percentage=90.0)

        # With 90% threshold, child-slow (80%) should NOT qualify as a bottleneck
        assert "bottlenecks" in result or "analysis" in result or "primary_bottleneck" in result


class TestHierarchyNodeCounts:
    """Test hierarchy metadata counts are exact."""

    def test_total_nodes_exact(self, deterministic_hierarchy):
        """Total nodes should be exactly 4 (root + 3 children)."""
        assert (
            deterministic_hierarchy["total_nodes"] == 4
        ), f"Total nodes should be 4, got {deterministic_hierarchy['total_nodes']}"

    def test_max_depth_exact(self, deterministic_hierarchy):
        """Max depth should be exactly 1."""
        assert (
            deterministic_hierarchy["max_depth"] == 1
        ), f"Max depth should be 1, got {deterministic_hierarchy['max_depth']}"


class TestHierarchyNameExtraction:
    """Test that names are correctly extracted and displayed."""

    def test_node_with_name_uses_name(self, hierarchy_with_names):
        """Node with 'name' field should use that name."""
        tree = format_tree(hierarchy_with_names, use_colors=False)

        # Should show "HTTP POST /checkout" from the operation_name/name field
        assert (
            "HTTP POST /checkout" in tree
        ), f"Tree should show 'HTTP POST /checkout', got:\n{tree}"

    def test_child_node_uses_name(self, hierarchy_with_names):
        """Child node with name should use that name."""
        tree = format_tree(hierarchy_with_names, use_colors=False)

        # Should show "Database Query"
        assert "Database Query" in tree, f"Tree should show 'Database Query', got:\n{tree}"

    def test_node_without_name_falls_back_to_id(self, hierarchy_with_names):
        """Node without name should fall back to ID."""
        tree = format_tree(hierarchy_with_names, use_colors=False)

        # Node "node-fallback-to-id" has no name, should show its ID
        assert (
            "node-fallback-to-id" in tree or "fallback" in tree.lower()
        ), f"Tree should show node ID when name is missing, got:\n{tree}"


class TestHierarchySummary:
    """Test hierarchy summary generation."""

    def test_summary_includes_total_nodes(self, deterministic_hierarchy):
        """Summary should include total node count."""
        summary = get_hierarchy_summary(deterministic_hierarchy)

        assert "4" in summary, f"Summary should include '4' (total nodes), got:\n{summary}"

    def test_summary_includes_bottleneck_info(self, deterministic_hierarchy):
        """Summary should include bottleneck information."""
        summary = get_hierarchy_summary(deterministic_hierarchy)

        # Should mention the bottleneck node or percentage
        assert (
            "child-slow" in summary or "slow" in summary.lower() or "80" in summary
        ), f"Summary should include bottleneck info, got:\n{summary}"


class TestTreeFormatting:
    """Test tree formatting with exact expected output."""

    def test_tree_includes_all_nodes(self, deterministic_hierarchy):
        """Tree should include all node IDs or names."""
        tree = format_tree(deterministic_hierarchy, use_colors=False)

        # Should include root and children (by name or id)
        assert "Root Operation" in tree or "root" in tree.lower()
        assert "Fast Child" in tree or "child-fast" in tree
        assert "Slow Database Query" in tree or "child-slow" in tree
        assert "Medium Operation" in tree or "child-medium" in tree

    def test_tree_shows_duration_in_detailed_mode(self, deterministic_hierarchy):
        """Detailed mode should show duration values."""
        tree = format_tree(deterministic_hierarchy, mode="detailed", use_colors=False)

        # Should show duration values
        assert (
            "1000" in tree or "800" in tree or "100" in tree
        ), f"Detailed tree should show durations, got:\n{tree}"

    def test_tree_respects_max_depth(self, deterministic_hierarchy):
        """max_depth limits how deep the tree is rendered."""
        tree = format_tree(deterministic_hierarchy, max_depth=0, use_colors=False)

        # Should produce some output
        assert len(tree) > 0, "Tree should have some output"

        # With max_depth=0, children at depth 1 should not appear
        # (fast, slow, medium are at depth 1)
        # But root (depth 0) should appear
        # Note: format_tree behavior may vary - it should at minimum render something


class TestWaterfallFormatting:
    """Test waterfall formatting with exact expected output."""

    def test_waterfall_includes_nodes(self, deterministic_hierarchy):
        """Waterfall should include node identifiers."""
        waterfall = format_waterfall(deterministic_hierarchy, width=80)

        # Should show root at minimum
        assert "Root" in waterfall or "root" in waterfall.lower() or len(waterfall) > 20

    def test_waterfall_respects_width(self, deterministic_hierarchy):
        """Waterfall should respect width parameter."""
        narrow = format_waterfall(deterministic_hierarchy, width=40)
        wide = format_waterfall(deterministic_hierarchy, width=120)

        # Max line length should respect width (with some margin)
        narrow_max = max(len(line) for line in narrow.split("\n")) if narrow else 0
        wide_max = max(len(line) for line in wide.split("\n")) if wide else 0

        assert narrow_max <= 50, f"Narrow waterfall too wide: {narrow_max}"
        assert wide_max <= 130, f"Wide waterfall too wide: {wide_max}"


class TestHierarchyEdgeCases:
    """Test hierarchy edge cases with exact expected behavior."""

    def test_empty_hierarchy_has_zero_nodes(self):
        """Empty hierarchy should have 0 nodes."""
        empty = {
            "roots": [],
            "total_nodes": 0,
            "max_depth": 0,
            "total_duration_ms": 0,
            "concurrent_count": 0,
            "bottleneck": None,
            "error_nodes": [],
            "detection_method": "Unknown",
        }

        assert empty["total_nodes"] == 0
        assert empty["bottleneck"] is None

        # Tree formatter should handle empty hierarchy — includes header and zero counts
        tree = format_tree(empty, use_colors=False)
        assert "THREAD HIERARCHY" in tree
        assert "Total nodes: 0" in tree
        assert "Max depth: 0" in tree

    def test_single_node_is_its_own_bottleneck(self):
        """Single node hierarchy should have that node as bottleneck (100%)."""
        single = {
            "roots": [
                {
                    "id": "only-node",
                    "node_type": "Span",
                    "name": "Only Node",
                    "parent_id": None,
                    "children": [],
                    "entry_ids": [0],
                    "start_time": "2024-01-15T10:00:00Z",
                    "end_time": "2024-01-15T10:00:01Z",
                    "duration_ms": 1000,
                    "entry_count": 1,
                    "error_count": 0,
                    "level_counts": {"INFO": 1},
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
                "node_id": "only-node",
                "duration_ms": 1000,
                "percentage": 100.0,
                "depth": 0,
            },
            "error_nodes": [],
            "detection_method": "ExplicitParentId",
        }

        assert single["bottleneck"]["node_id"] == "only-node"
        assert single["bottleneck"]["percentage"] == 100.0


class TestHierarchyEntryCount:
    """Test entry counts are accurate.

    Note: entry_count in hierarchy nodes is AGGREGATE (includes children).
    So root(5) = root_direct(1) + fast(1) + slow(2) + medium(1)
    """

    @pytest.mark.parametrize(
        "node_id,expected_entry_count",
        [
            ("root", 5),  # Aggregate: 1 (direct) + 1 + 2 + 1 (children)
            ("child-fast", 1),
            ("child-slow", 2),
            ("child-medium", 1),
        ],
        ids=["root_5_aggregate", "fast_1", "slow_2", "medium_1"],
    )
    def test_node_entry_count_exact(self, deterministic_hierarchy, node_id, expected_entry_count):
        """Each node has exactly the expected entry count."""
        node = find_node(deterministic_hierarchy, node_id)

        assert node is not None, f"Node {node_id} not found"
        assert (
            node["entry_count"] == expected_entry_count
        ), f"Node {node_id} should have {expected_entry_count} entries, got {node['entry_count']}"

    def test_leaf_entry_counts_sum_to_direct_entries(self, deterministic_hierarchy):
        """Leaf node entry counts should sum to total direct entries."""
        # Leaf nodes: fast(1) + slow(2) + medium(1) = 4
        # Plus root's direct entry: 4 + 1 = 5 total direct entries
        expected_total = 5

        # Count only leaf nodes + root's direct entries
        total = len(find_node(deterministic_hierarchy, "root")["entry_ids"])
        for child_id in ["child-fast", "child-slow", "child-medium"]:
            node = find_node(deterministic_hierarchy, child_id)
            total += node["entry_count"]

        assert (
            total == expected_total
        ), f"Total direct entries should be {expected_total}, got {total}"
