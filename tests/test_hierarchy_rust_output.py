import json

import pytest

from logler.investigate import follow_thread_hierarchy, RUST_AVAILABLE


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required for hierarchy tests")
def test_rust_hierarchy_roots_bottleneck_and_errors(tmp_path):
    entries = [
        {
            "timestamp": "2024-01-15T10:00:00.000Z",
            "level": "INFO",
            "message": "root start",
            "trace_id": "trace-123",
            "span_id": "span-root",
        },
        {
            "timestamp": "2024-01-15T10:00:00.200Z",
            "level": "INFO",
            "message": "child start",
            "trace_id": "trace-123",
            "span_id": "span-child",
            "parent_span_id": "span-root",
        },
        {
            "timestamp": "2024-01-15T10:00:00.500Z",
            "level": "ERROR",
            "message": "child error",
            "trace_id": "trace-123",
            "span_id": "span-child",
            "parent_span_id": "span-root",
        },
        {
            "timestamp": "2024-01-15T10:00:00.900Z",
            "level": "INFO",
            "message": "child end",
            "trace_id": "trace-123",
            "span_id": "span-child",
            "parent_span_id": "span-root",
        },
        {
            "timestamp": "2024-01-15T10:00:01.000Z",
            "level": "INFO",
            "message": "root end",
            "trace_id": "trace-123",
            "span_id": "span-root",
        },
    ]

    log_path = tmp_path / "trace.jsonl"
    log_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")

    hierarchy = follow_thread_hierarchy(
        files=[str(log_path)],
        root_identifier="trace-123",
        use_naming_patterns=False,
        use_temporal_inference=False,
    )

    roots = hierarchy.get("roots", [])
    assert [root.get("id") for root in roots] == ["span-root"]
    assert hierarchy.get("total_nodes") == 2
    assert roots[0].get("children")[0].get("id") == "span-child"

    bottleneck = hierarchy.get("bottleneck")
    assert bottleneck is not None
    # span-child has highest self-time: 700ms (no children)
    # span-root self-time: 1000ms - 700ms = 300ms
    assert bottleneck.get("node_id") == "span-child"
    # 700ms / 1000ms total = 70%
    assert abs(bottleneck.get("percentage", 0.0) - 70.0) < 0.1

    error_nodes = hierarchy.get("error_nodes", [])
    assert set(error_nodes) == {"span-child"}
    assert len(error_nodes) == 1

    assert hierarchy.get("detection_method") == "ExplicitParentId"
    assert hierarchy.get("detection_methods") == ["ExplicitParentId"]
