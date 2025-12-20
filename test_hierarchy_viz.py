"""Test script for hierarchy visualization"""

# Mock hierarchy data (what would be returned from Rust)
mock_hierarchy = {
    "roots": [
        {
            "id": "req-001",
            "node_type": "CorrelationGroup",
            "name": "Request Processing",
            "parent_id": None,
            "children": [
                {
                    "id": "span-auth",
                    "node_type": "Span",
                    "name": "Authentication",
                    "parent_id": "req-001",
                    "children": [
                        {
                            "id": "span-auth-cache",
                            "node_type": "Span",
                            "name": "Cache Lookup",
                            "parent_id": "span-auth",
                            "children": [],
                            "entry_ids": [],
                            "start_time": "2024-01-15T10:00:00.100Z",
                            "end_time": "2024-01-15T10:00:00.120Z",
                            "duration_ms": 20,
                            "entry_count": 2,
                            "error_count": 0,
                            "level_counts": {"DEBUG": 1, "INFO": 1},
                            "depth": 2,
                            "confidence": 1.0,
                            "relationship_evidence": ["Explicit parent_span_id: span-auth"]
                        }
                    ],
                    "entry_ids": [],
                    "start_time": "2024-01-15T10:00:00.050Z",
                    "end_time": "2024-01-15T10:00:00.150Z",
                    "duration_ms": 100,
                    "entry_count": 4,
                    "error_count": 0,
                    "level_counts": {"INFO": 2, "DEBUG": 2},
                    "depth": 1,
                    "confidence": 1.0,
                    "relationship_evidence": ["Explicit parent_span_id: span-root"]
                },
                {
                    "id": "span-db-query",
                    "node_type": "Span",
                    "name": "Database Query",
                    "parent_id": "req-001",
                    "children": [],
                    "entry_ids": [],
                    "start_time": "2024-01-15T10:00:00.200Z",
                    "end_time": "2024-01-15T10:00:01.520Z",
                    "duration_ms": 1320,
                    "entry_count": 4,
                    "error_count": 0,
                    "level_counts": {"INFO": 2, "DEBUG": 1, "WARN": 1},
                    "depth": 1,
                    "confidence": 1.0,
                    "relationship_evidence": ["Explicit parent_span_id: span-root"]
                },
                {
                    "id": "span-ext-api",
                    "node_type": "Span",
                    "name": "External API Call",
                    "parent_id": "req-001",
                    "children": [
                        {
                            "id": "span-ext-api-http",
                            "node_type": "Span",
                            "name": "HTTP Request",
                            "parent_id": "span-ext-api",
                            "children": [],
                            "entry_ids": [],
                            "start_time": "2024-01-15T10:00:01.650Z",
                            "end_time": "2024-01-15T10:00:02.800Z",
                            "duration_ms": 1150,
                            "entry_count": 2,
                            "error_count": 0,
                            "level_counts": {"DEBUG": 1, "INFO": 1},
                            "depth": 2,
                            "confidence": 1.0,
                            "relationship_evidence": ["Explicit parent_span_id: span-ext-api"]
                        },
                        {
                            "id": "span-ext-api-parse",
                            "node_type": "Span",
                            "name": "Response Parsing",
                            "parent_id": "span-ext-api",
                            "children": [],
                            "entry_ids": [],
                            "start_time": "2024-01-15T10:00:02.850Z",
                            "end_time": "2024-01-15T10:00:02.900Z",
                            "duration_ms": 50,
                            "entry_count": 2,
                            "error_count": 0,
                            "level_counts": {"INFO": 2},
                            "depth": 2,
                            "confidence": 1.0,
                            "relationship_evidence": ["Explicit parent_span_id: span-ext-api"]
                        }
                    ],
                    "entry_ids": [],
                    "start_time": "2024-01-15T10:00:01.600Z",
                    "end_time": "2024-01-15T10:00:02.920Z",
                    "duration_ms": 1320,
                    "entry_count": 6,
                    "error_count": 0,
                    "level_counts": {"INFO": 4, "DEBUG": 2},
                    "depth": 1,
                    "confidence": 1.0,
                    "relationship_evidence": ["Explicit parent_span_id: span-root"]
                }
            ],
            "entry_ids": [],
            "start_time": "2024-01-15T10:00:00.000Z",
            "end_time": "2024-01-15T10:00:03.150Z",
            "duration_ms": 3150,
            "entry_count": 19,
            "error_count": 0,
            "level_counts": {"INFO": 15, "DEBUG": 3, "WARN": 1},
            "depth": 0,
            "confidence": 1.0,
            "relationship_evidence": []
        }
    ],
    "total_nodes": 7,
    "max_depth": 2,
    "total_duration_ms": 3150,
    "concurrent_count": 2,
    "bottleneck": {
        "node_id": "span-db-query",
        "duration_ms": 1320,
        "percentage": 41.9,
        "depth": 1
    },
    "error_nodes": [],
    "detection_method": "ExplicitParentId"
}

# Test tree formatter
import sys
sys.path.insert(0, '/home/user/logler')

from tree_formatter import format_tree, format_waterfall, print_tree, print_waterfall
from src.logler.investigate import get_hierarchy_summary

print("=" * 80)
print("TESTING HIERARCHY VISUALIZATION")
print("=" * 80)
print()

# Test 1: Summary
print("TEST 1: Hierarchy Summary")
print("-" * 80)
summary = get_hierarchy_summary(mock_hierarchy)
print(summary)
print()

# Test 2: ASCII Tree (no colors)
print("TEST 2: ASCII Tree (Compact Mode)")
print("-" * 80)
tree_ascii = format_tree(mock_hierarchy, mode="compact", use_colors=False)
print(tree_ascii)
print()

# Test 3: Detailed Tree (no colors)
print("TEST 3: ASCII Tree (Detailed Mode)")
print("-" * 80)
tree_detailed = format_tree(mock_hierarchy, mode="detailed", use_colors=False)
print(tree_detailed)
print()

# Test 4: Waterfall Timeline
print("TEST 4: Waterfall Timeline")
print("-" * 80)
waterfall = format_waterfall(mock_hierarchy, width=100)
print(waterfall)
print()

# Test 5: Full Mode with Confidence
print("TEST 5: ASCII Tree (Full Mode with Confidence)")
print("-" * 80)
tree_full = format_tree(mock_hierarchy, mode="full", show_confidence=True, use_colors=False)
print(tree_full)
print()

print("=" * 80)
print("ALL TESTS COMPLETED SUCCESSFULLY!")
print("=" * 80)
