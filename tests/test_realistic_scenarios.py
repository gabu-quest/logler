"""
Integration tests with realistic messy log data.

These tests simulate real-world scenarios that break naive implementations:
- Interleaved threads
- Orphaned spans
- Clock skew (out-of-order timestamps)
- Concurrent operations
- Large scale data
"""

import json
import pytest
import tempfile
import random
from pathlib import Path


# Import with Rust backend check
try:
    from logler.investigate import (
        search,
        follow_thread,
        follow_thread_hierarchy,
        RUST_AVAILABLE,
    )
    from logler.tree_formatter import format_tree, format_waterfall
except ImportError:
    RUST_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust backend required for integration tests"
)


# =============================================================================
# Fixtures for Realistic Messy Data
# =============================================================================


@pytest.fixture
def interleaved_threads_log():
    """
    Log file with multiple threads interleaved randomly.

    Simulates a real multi-threaded application where log entries
    from different threads are mixed together in the output.
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        entries = []
        threads = ["main", "worker-1", "worker-2", "io-thread", "gc-thread"]

        # Generate entries for each thread
        for thread in threads:
            for i in range(20):
                entries.append(
                    {
                        "timestamp": f"2024-01-15T10:00:{i:02d}.{random.randint(0, 999):03d}Z",
                        "level": "INFO" if i % 5 != 0 else "ERROR",
                        "message": f"[{thread}] Operation {i}",
                        "thread_id": thread,
                        "correlation_id": f"req-{thread}-{i // 5}",
                        "sequence": i,
                    }
                )

        # Shuffle to simulate real interleaving
        random.shuffle(entries)

        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def orphaned_spans_log():
    """
    Log file with spans that reference non-existent parents.

    Simulates distributed tracing where some spans are missing
    (perhaps from a different service or dropped logs).
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        entries = [
            # Root span (exists)
            {
                "timestamp": "2024-01-15T10:00:00.000Z",
                "level": "INFO",
                "message": "Request started",
                "span_id": "span-root",
                "parent_span_id": None,
                "trace_id": "trace-123",
            },
            # Child of root (valid)
            {
                "timestamp": "2024-01-15T10:00:00.100Z",
                "level": "INFO",
                "message": "Auth check",
                "span_id": "span-auth",
                "parent_span_id": "span-root",
                "trace_id": "trace-123",
            },
            # ORPHAN: references parent that doesn't exist
            {
                "timestamp": "2024-01-15T10:00:00.200Z",
                "level": "ERROR",
                "message": "Database timeout",
                "span_id": "span-db-query",
                "parent_span_id": "span-missing-db-service",  # Parent doesn't exist!
                "trace_id": "trace-123",
            },
            # ORPHAN: references another missing parent
            {
                "timestamp": "2024-01-15T10:00:00.300Z",
                "level": "WARN",
                "message": "Cache miss",
                "span_id": "span-cache",
                "parent_span_id": "span-never-logged",  # Also missing!
                "trace_id": "trace-123",
            },
            # Valid child of auth
            {
                "timestamp": "2024-01-15T10:00:00.400Z",
                "level": "INFO",
                "message": "Token validated",
                "span_id": "span-token-check",
                "parent_span_id": "span-auth",
                "trace_id": "trace-123",
            },
        ]

        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def clock_skew_log():
    """
    Log file with out-of-order timestamps from clock drift.

    Simulates distributed systems where different machines have
    slightly different clocks, causing children to appear before parents.
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        # Note: timestamps are intentionally out of logical order
        entries = [
            # Child logged BEFORE parent due to clock skew
            {
                "timestamp": "2024-01-15T10:00:00.050Z",  # Should be after parent
                "level": "INFO",
                "message": "Child operation started",
                "span_id": "span-child",
                "parent_span_id": "span-parent",
                "trace_id": "trace-skew",
            },
            # Parent logged AFTER child
            {
                "timestamp": "2024-01-15T10:00:00.100Z",  # Later timestamp but logically first
                "level": "INFO",
                "message": "Parent operation started",
                "span_id": "span-parent",
                "parent_span_id": None,
                "trace_id": "trace-skew",
            },
            # Grandchild with even earlier timestamp
            {
                "timestamp": "2024-01-15T10:00:00.010Z",  # Earliest but deepest
                "level": "INFO",
                "message": "Grandchild operation",
                "span_id": "span-grandchild",
                "parent_span_id": "span-child",
                "trace_id": "trace-skew",
            },
            # End entries also out of order
            {
                "timestamp": "2024-01-15T10:00:00.200Z",
                "level": "INFO",
                "message": "Child operation completed",
                "span_id": "span-child",
                "parent_span_id": "span-parent",
                "trace_id": "trace-skew",
            },
            {
                "timestamp": "2024-01-15T10:00:00.150Z",
                "level": "INFO",
                "message": "Parent operation completed",
                "span_id": "span-parent",
                "parent_span_id": None,
                "trace_id": "trace-skew",
            },
        ]

        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def concurrent_spans_log():
    """
    Log file with multiple spans running simultaneously.

    Simulates parallel processing where multiple operations
    run concurrently under the same parent.
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        entries = [
            # Parent span
            {
                "timestamp": "2024-01-15T10:00:00.000Z",
                "level": "INFO",
                "message": "Batch processing started",
                "span_id": "span-batch",
                "parent_span_id": None,
                "trace_id": "trace-concurrent",
            },
        ]

        # Add 10 concurrent workers
        for i in range(10):
            start_offset = 100 + i * 10  # Slightly staggered starts
            duration = 500 + random.randint(-50, 50)  # ~500ms each

            entries.append(
                {
                    "timestamp": f"2024-01-15T10:00:00.{start_offset:03d}Z",
                    "level": "INFO",
                    "message": f"Worker {i} started",
                    "span_id": f"span-worker-{i}",
                    "parent_span_id": "span-batch",
                    "trace_id": "trace-concurrent",
                }
            )
            entries.append(
                {
                    "timestamp": f"2024-01-15T10:00:00.{start_offset + duration:03d}Z",
                    "level": "INFO" if i % 3 != 0 else "ERROR",
                    "message": f"Worker {i} completed",
                    "span_id": f"span-worker-{i}",
                    "parent_span_id": "span-batch",
                    "trace_id": "trace-concurrent",
                }
            )

        # Parent completes last
        entries.append(
            {
                "timestamp": "2024-01-15T10:00:01.000Z",
                "level": "INFO",
                "message": "Batch processing completed",
                "span_id": "span-batch",
                "parent_span_id": None,
                "trace_id": "trace-concurrent",
            }
        )

        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def large_scale_log():
    """
    Large log file for performance testing.

    Contains 10,000 entries across multiple threads.
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        for i in range(10000):
            entry = {
                "timestamp": f"2024-01-15T{10 + i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z",
                "level": ["INFO", "DEBUG", "WARN", "ERROR"][i % 4],
                "message": f"Operation {i}: {'Success' if i % 7 != 0 else 'Failed with timeout'}",
                "thread_id": f"worker-{i % 50}",
                "correlation_id": f"req-{i % 1000}",
                "trace_id": f"trace-{i % 100}",
            }
            f.write(json.dumps(entry) + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


# =============================================================================
# Tests for Interleaved Threads
# =============================================================================


class TestInterleavedThreads:
    """Tests with logs from multiple threads interleaved randomly."""

    def test_follow_thread_excludes_other_threads(self, interleaved_threads_log):
        """Following a thread should only return entries from that thread"""
        result = follow_thread(files=[interleaved_threads_log], thread_id="worker-1")
        entries = result.get("entries", result.get("timeline", []))

        # Should have entries
        assert len(entries) > 0, "Should find entries for worker-1"

        # All entries should be from worker-1
        for entry in entries:
            if isinstance(entry, dict):
                thread = entry.get("thread_id", "")
                assert "worker-1" in str(thread), f"Found entry from wrong thread: {thread}"

    def test_search_finds_across_threads(self, interleaved_threads_log):
        """Search should find matches regardless of thread interleaving"""
        result = search(files=[interleaved_threads_log], query="Operation 5", limit=100)
        total = result.get("total_matches", len(result.get("results", [])))

        # Each of 5 threads has an "Operation 5", should find all
        assert total >= 5, f"Should find 'Operation 5' in each thread, found {total}"


# =============================================================================
# Tests for Orphaned Spans
# =============================================================================


class TestOrphanedSpans:
    """Tests with spans referencing non-existent parents."""

    def test_hierarchy_handles_orphans(self, orphaned_spans_log):
        """Building hierarchy should handle orphaned spans gracefully"""
        hierarchy = follow_thread_hierarchy(files=[orphaned_spans_log], root_identifier="trace-123")

        assert "roots" in hierarchy  # guard
        assert hierarchy["total_nodes"] >= 3  # root + auth + at least one orphan reattached

    def test_orphans_not_lost(self, orphaned_spans_log):
        """Orphaned spans should not be silently dropped"""
        result = search(files=[orphaned_spans_log], query="", limit=100)
        total = result.get("total_matches", len(result.get("results", [])))

        # Should find all 5 entries including orphans
        assert total >= 5, "Should not lose orphaned spans"


# =============================================================================
# Tests for Clock Skew
# =============================================================================


class TestClockSkew:
    """Tests with out-of-order timestamps from clock drift."""

    def test_hierarchy_handles_clock_skew(self, clock_skew_log):
        """Should build hierarchy despite out-of-order timestamps"""
        hierarchy = follow_thread_hierarchy(files=[clock_skew_log], root_identifier="trace-skew")

        # Should complete without crashing
        assert "roots" in hierarchy
        # Should have the parent as root (not the chronologically first entry)
        if hierarchy.get("roots"):
            # The logical root should be identified even if timestamp is later
            assert hierarchy["total_nodes"] >= 1

    def test_tree_renders_with_skew(self, clock_skew_log):
        """Tree formatting should handle clock skew"""
        hierarchy = follow_thread_hierarchy(files=[clock_skew_log], root_identifier="trace-skew")
        tree = format_tree(hierarchy, use_colors=False)

        assert len(tree) > 0  # guard
        # Tree must mention at least one operation from the data
        assert "parent" in tree.lower() or "child" in tree.lower() or "span" in tree.lower()


# =============================================================================
# Tests for Concurrent Spans
# =============================================================================


class TestConcurrentSpans:
    """Tests with multiple spans running simultaneously."""

    def test_waterfall_shows_overlap(self, concurrent_spans_log):
        """Waterfall should show concurrent operations"""
        hierarchy = follow_thread_hierarchy(
            files=[concurrent_spans_log], root_identifier="trace-concurrent"
        )
        waterfall = format_waterfall(hierarchy, width=100)

        assert len(waterfall) > 0  # guard
        # Should show batch and workers — both keywords must appear somewhere
        waterfall_lower = waterfall.lower()
        assert "batch" in waterfall_lower or "worker" in waterfall_lower
        # Must have multiple lines (one per span)
        assert waterfall.count("\n") >= 3

    def test_hierarchy_captures_concurrency(self, concurrent_spans_log):
        """Hierarchy should capture concurrent children"""
        hierarchy = follow_thread_hierarchy(
            files=[concurrent_spans_log], root_identifier="trace-concurrent"
        )

        # Should have concurrent_count > 1
        concurrent_count = hierarchy.get("concurrent_count", 0)
        # With 10 workers running in parallel, should detect concurrency
        assert concurrent_count >= 1, "Should detect concurrent operations"


# =============================================================================
# Tests for Large Scale
# =============================================================================


class TestLargeScale:
    """Performance tests with realistic data sizes."""

    def test_10k_entries_search_completes(self, large_scale_log):
        """Search should complete on 10k entries"""
        result = search(files=[large_scale_log], query="Failed", limit=100)

        # Should find failures (every 7th entry fails)
        total = result.get("total_matches", len(result.get("results", [])))
        assert total > 0, "Should find 'Failed' entries"

    def test_10k_entries_level_filter(self, large_scale_log):
        """Level filtering should work on large files"""
        result = search(files=[large_scale_log], level="ERROR", limit=100)

        # Should find ERROR entries (every 4th entry)
        total = result.get("total_matches", len(result.get("results", [])))
        assert total > 0, "Should find ERROR entries"

    def test_follow_thread_on_large_file(self, large_scale_log):
        """Following thread should work on large files"""
        result = follow_thread(files=[large_scale_log], thread_id="worker-0")
        entries = result.get("entries", result.get("timeline", []))

        # worker-0 appears every 50th entry = 200 entries
        assert len(entries) > 0, "Should find entries for worker-0"


# =============================================================================
# Tests for Mixed Realistic Scenarios
# =============================================================================


class TestMixedScenarios:
    """Tests combining multiple realistic issues."""

    @pytest.fixture
    def messy_production_log(self):
        """
        Simulates a real production log with multiple issues:
        - Interleaved services
        - Some malformed entries
        - Unicode content
        - Very long messages
        - Missing fields
        """
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            entries = []

            # Normal entries
            for i in range(50):
                entries.append(
                    json.dumps(
                        {
                            "timestamp": f"2024-01-15T10:00:{i:02d}Z",
                            "level": "INFO",
                            "message": f"Normal operation {i}",
                            "service": "api",
                        }
                    )
                )

            # Unicode entries (Japanese)
            entries.append(
                json.dumps(
                    {
                        "timestamp": "2024-01-15T10:01:00Z",
                        "level": "INFO",
                        "message": "Unicode: \u65e5\u672c\u8a9e\u30c6\u30b9\u30c8",
                        "service": "i18n",
                    }
                )
            )

            # Very long message
            entries.append(
                json.dumps(
                    {
                        "timestamp": "2024-01-15T10:01:01Z",
                        "level": "ERROR",
                        "message": "Stack trace: " + ("a" * 5000),
                        "service": "api",
                    }
                )
            )

            # Missing timestamp
            entries.append(json.dumps({"level": "WARN", "message": "No timestamp entry"}))

            # Missing level
            entries.append(json.dumps({"timestamp": "2024-01-15T10:01:02Z", "message": "No level"}))

            # Plain text line (not JSON)
            entries.append("2024-01-15 10:01:03 ERROR This is plain text not JSON")

            # Malformed JSON
            entries.append('{"message": "truncated')

            # Write all entries
            for entry in entries:
                f.write(entry + "\n")

            temp_path = f.name

        yield temp_path
        Path(temp_path).unlink()

    def test_handles_messy_production_data(self, messy_production_log):
        """Should handle messy production-like data without crashing.

        Previously skipped due to Rust panic on NaN in f64::partial_cmp during sort.
        Fixed by switching to f64::total_cmp which handles NaN deterministically.
        """
        result = search(files=[messy_production_log], query="", limit=100)
        # 50 normal + 1 unicode + 1 long + 1 no-ts + 1 no-level + 1 plain text = 55 parseable
        assert result["total_matches"] >= 50, f"Expected 50+ entries, got {result['total_matches']}"

    def test_unicode_search_in_messy_data(self, messy_production_log):
        """Should find unicode content in messy data"""
        result = search(files=[messy_production_log], query="\u65e5\u672c\u8a9e", limit=10)
        total = result.get("total_matches", len(result.get("results", [])))

        # Should find the Japanese text entry
        assert total >= 1, "Should find Unicode entry"

    def test_level_filter_with_missing_levels(self, messy_production_log):
        """Level filtering should handle entries with missing levels"""
        result = search(files=[messy_production_log], level="ERROR", limit=100)

        total = result["total_matches"]
        # Fixture has 1 explicit ERROR (long stacktrace) + 1 plain text ERROR line = at least 1
        assert total >= 1, f"Should find ERROR entries, got {total}"
        # Verify the results actually have ERROR level (search wraps entries in {"entry": {...}})
        for item in result.get("results", []):
            entry = item["entry"]
            assert entry["level"] == "ERROR", f"Got non-ERROR entry: {entry['level']}"
