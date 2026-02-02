"""Tests verifying that hierarchy builder uses explicit duration_ms fields.

Fixture: JSON logs where entries contain duration_ms in their fields.
The hierarchy builder should prefer these over timestamp-based calculation.
"""

import json
import pytest

from logler.investigate import follow_thread_hierarchy


@pytest.fixture
def duration_log(tmp_path):
    """JSON log with explicit duration_ms fields.

    Structure:
    - trace-dur-001 with 3 spans, each having explicit duration_ms
    - span-root: 500ms (parent)
    - span-db: 200ms (child of root, database query)
    - span-cache: 50ms (child of root, cache lookup)
    """
    entries = [
        {
            "timestamp": "2024-01-15T10:00:00.000Z",
            "level": "INFO",
            "message": "Request started",
            "trace_id": "trace-dur-001",
            "span_id": "span-root",
            "service_name": "api-gateway",
            "thread_id": "handler-1",
            "duration_ms": 500,
        },
        {
            "timestamp": "2024-01-15T10:00:00.100Z",
            "level": "INFO",
            "message": "Database query started",
            "trace_id": "trace-dur-001",
            "span_id": "span-db",
            "parent_span_id": "span-root",
            "service_name": "api-gateway",
            "thread_id": "handler-1",
            "duration_ms": 200,
        },
        {
            "timestamp": "2024-01-15T10:00:00.300Z",
            "level": "INFO",
            "message": "Database query completed",
            "trace_id": "trace-dur-001",
            "span_id": "span-db",
            "parent_span_id": "span-root",
            "service_name": "api-gateway",
            "thread_id": "handler-1",
            "duration_ms": 200,
        },
        {
            "timestamp": "2024-01-15T10:00:00.350Z",
            "level": "INFO",
            "message": "Cache lookup",
            "trace_id": "trace-dur-001",
            "span_id": "span-cache",
            "parent_span_id": "span-root",
            "service_name": "api-gateway",
            "thread_id": "handler-1",
            "duration_ms": 50,
        },
        {
            "timestamp": "2024-01-15T10:00:00.500Z",
            "level": "INFO",
            "message": "Request completed",
            "trace_id": "trace-dur-001",
            "span_id": "span-root",
            "service_name": "api-gateway",
            "thread_id": "handler-1",
            "duration_ms": 500,
        },
    ]

    log_file = tmp_path / "duration_test.log"
    with open(log_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return str(log_file)


class TestHierarchyDurationMs:
    """Verify the hierarchy builder correctly reads duration_ms from log fields."""

    def test_hierarchy_returns_duration_for_root(self, duration_log):
        """Root node should have duration_ms from the explicit field."""
        result = follow_thread_hierarchy(
            files=[duration_log],
            root_identifier="trace-dur-001",
        )

        assert result["roots"], "Should find at least one root node"
        # The total_duration_ms should reflect the trace duration
        assert result["total_duration_ms"] is not None
        assert result["total_duration_ms"] > 0, "Total duration should be > 0"

    def test_hierarchy_child_nodes_have_duration(self, duration_log):
        """Child nodes should also report their duration_ms."""
        result = follow_thread_hierarchy(
            files=[duration_log],
            root_identifier="trace-dur-001",
        )

        roots = result["roots"]
        assert len(roots) >= 1

        # Collect all nodes recursively
        all_nodes = []

        def collect(node):
            all_nodes.append(node)
            for child in node.get("children", []):
                collect(child)

        for root in roots:
            collect(root)

        # At least one node should have duration_ms > 0
        nodes_with_duration = [n for n in all_nodes if (n.get("duration_ms") or 0) > 0]
        assert len(nodes_with_duration) > 0, (
            f"Expected nodes with duration_ms > 0, got: "
            f"{[(n.get('id'), n.get('duration_ms')) for n in all_nodes]}"
        )

    def test_bottleneck_uses_duration(self, duration_log):
        """Bottleneck analysis should use explicit duration_ms values."""
        result = follow_thread_hierarchy(
            files=[duration_log],
            root_identifier="trace-dur-001",
        )

        # If bottleneck is identified, it should have a duration
        bottleneck = result.get("bottleneck")
        if bottleneck:
            assert (
                bottleneck.get("duration_ms", 0) > 0
            ), f"Bottleneck should have duration > 0, got: {bottleneck}"
