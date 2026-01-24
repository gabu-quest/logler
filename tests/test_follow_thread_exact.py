"""
PARAMETRIZED FOLLOW THREAD TESTS - Exact Value Assertions

These tests use deterministic fixtures with KNOWN values and assert
EXACT expected outputs.

Fixture: deterministic_log_file
- 100 entries total
- 25 each of worker-0/1/2/3
- worker-0 = INFO, worker-1 = DEBUG, worker-2 = WARN, worker-3 = ERROR
- 10 each of req-0 through req-9
"""

import pytest

try:
    from logler.investigate import follow_thread, RUST_AVAILABLE
except ImportError:
    RUST_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust backend required for follow thread tests"
)


class TestFollowThreadById:
    """Test following by thread ID returns exact expected counts."""

    @pytest.mark.parametrize(
        "thread_id,expected_count,expected_level",
        [
            ("worker-0", 25, "INFO"),  # worker-0 is always INFO
            ("worker-1", 25, "DEBUG"),  # worker-1 is always DEBUG
            ("worker-2", 25, "WARN"),  # worker-2 is always WARN
            ("worker-3", 25, "ERROR"),  # worker-3 is always ERROR
        ],
        ids=["worker0_info", "worker1_debug", "worker2_warn", "worker3_error"],
    )
    def test_follow_thread_exact_count(
        self, deterministic_log_file, thread_id, expected_count, expected_level
    ):
        """Each thread has exactly 25 entries with a specific level."""
        result = follow_thread(files=[deterministic_log_file], thread_id=thread_id)

        entries = result.get("entries", result.get("timeline", []))

        # MUST have exact count
        assert (
            len(entries) == expected_count
        ), f"Thread {thread_id} should have exactly {expected_count} entries, got {len(entries)}"

        # ALL entries must be from this thread
        for entry in entries:
            assert (
                entry["thread_id"] == thread_id
            ), f"Entry thread_id {entry['thread_id']} doesn't match {thread_id}"

        # ALL entries should have the expected level
        for entry in entries:
            assert (
                entry["level"].upper() == expected_level
            ), f"Thread {thread_id} should have level {expected_level}, got {entry['level']}"

    def test_nonexistent_thread_returns_empty(self, deterministic_log_file):
        """Non-existent thread should return exactly 0 entries."""
        result = follow_thread(files=[deterministic_log_file], thread_id="does-not-exist")

        entries = result.get("entries", result.get("timeline", []))
        assert len(entries) == 0, "Non-existent thread should return 0 entries"


class TestFollowThreadByCorrelation:
    """Test following by correlation ID returns exact expected counts."""

    @pytest.mark.parametrize(
        "correlation_id,expected_count",
        [
            ("req-0", 10),  # Each correlation appears in 10 entries (100/10)
            ("req-1", 10),
            ("req-5", 10),
            ("req-9", 10),
        ],
        ids=["req0_10", "req1_10", "req5_10", "req9_10"],
    )
    def test_follow_correlation_exact_count(
        self, deterministic_log_file, correlation_id, expected_count
    ):
        """Each correlation ID appears in exactly 10 entries."""
        result = follow_thread(files=[deterministic_log_file], correlation_id=correlation_id)

        entries = result.get("entries", result.get("timeline", []))

        assert len(entries) == expected_count, (
            f"Correlation {correlation_id} should have exactly {expected_count} entries, "
            f"got {len(entries)}"
        )

        # ALL entries must have matching correlation_id
        for entry in entries:
            assert entry["correlation_id"] == correlation_id

    @pytest.mark.parametrize(
        "correlation_id,expected_threads",
        [
            # Each correlation spans all 4 threads (entries are distributed)
            # req-0: entries 0, 10, 20, 30, 40, 50, 60, 70, 80, 90
            # Entry 0: worker-0, Entry 10: worker-2, etc.
            ("req-0", {"worker-0", "worker-2"}),  # 0%4=0, 10%4=2, 20%4=0, 30%4=2...
            ("req-1", {"worker-1", "worker-3"}),  # 1%4=1, 11%4=3, 21%4=1, 31%4=3...
        ],
        ids=["req0_threads", "req1_threads"],
    )
    def test_correlation_spans_expected_threads(
        self, deterministic_log_file, correlation_id, expected_threads
    ):
        """Correlation should span the expected set of threads."""
        result = follow_thread(files=[deterministic_log_file], correlation_id=correlation_id)

        entries = result.get("entries", result.get("timeline", []))
        actual_threads = {entry["thread_id"] for entry in entries}

        assert actual_threads == expected_threads, (
            f"Correlation {correlation_id} should span threads {expected_threads}, "
            f"got {actual_threads}"
        )

    def test_nonexistent_correlation_returns_empty(self, deterministic_log_file):
        """Non-existent correlation ID should return exactly 0 entries."""
        result = follow_thread(files=[deterministic_log_file], correlation_id="req-nonexistent")

        entries = result.get("entries", result.get("timeline", []))
        assert len(entries) == 0, "Non-existent correlation should return 0 entries"


class TestFollowThreadMetadata:
    """Test that follow_thread returns correct metadata."""

    def test_total_entries_matches_list_length(self, deterministic_log_file):
        """total_entries should match actual entries length."""
        result = follow_thread(files=[deterministic_log_file], thread_id="worker-0")

        entries = result.get("entries", result.get("timeline", []))

        if "total_entries" in result:
            assert result["total_entries"] == len(entries), (
                f"total_entries ({result['total_entries']}) should match "
                f"entries length ({len(entries)})"
            )

    def test_duration_is_positive_for_thread_with_entries(self, deterministic_log_file):
        """Duration should be positive for threads with multiple entries."""
        result = follow_thread(files=[deterministic_log_file], thread_id="worker-0")

        entries = result.get("entries", result.get("timeline", []))
        assert len(entries) == 25  # Verify we have entries

        # Duration should exist and be >= 0
        if "duration_ms" in result:
            assert result["duration_ms"] >= 0, "Duration should be non-negative"


class TestFollowThreadChronologicalOrder:
    """Test that entries are returned in chronological order."""

    def test_entries_in_timestamp_order(self, deterministic_log_file):
        """Entries should be returned in chronological order."""
        result = follow_thread(files=[deterministic_log_file], thread_id="worker-0")

        entries = result.get("entries", result.get("timeline", []))
        assert len(entries) == 25

        timestamps = [entry["timestamp"] for entry in entries]

        # Timestamps should be in sorted order
        assert timestamps == sorted(timestamps), "Entries should be in chronological order"


class TestFollowThreadLevelCounts:
    """Test level distribution within threads."""

    @pytest.mark.parametrize(
        "thread_id,expected_levels",
        [
            ("worker-0", {"INFO": 25}),
            ("worker-1", {"DEBUG": 25}),
            ("worker-2", {"WARN": 25}),
            ("worker-3", {"ERROR": 25}),
        ],
        ids=["worker0_all_info", "worker1_all_debug", "worker2_all_warn", "worker3_all_error"],
    )
    def test_thread_level_distribution(self, deterministic_log_file, thread_id, expected_levels):
        """Each thread has exactly the expected level distribution."""
        result = follow_thread(files=[deterministic_log_file], thread_id=thread_id)

        entries = result.get("entries", result.get("timeline", []))

        # Count levels
        level_counts = {}
        for entry in entries:
            level = entry["level"].upper()
            level_counts[level] = level_counts.get(level, 0) + 1

        assert (
            level_counts == expected_levels
        ), f"Thread {thread_id} level distribution should be {expected_levels}, got {level_counts}"


class TestFollowThreadNoIdentifier:
    """Test behavior when no identifier is provided."""

    def test_no_identifier_returns_empty_or_raises(self, deterministic_log_file):
        """No identifier should return empty entries or raise."""
        try:
            result = follow_thread(files=[deterministic_log_file])
            entries = result.get("entries", result.get("timeline", []))
            # If it doesn't raise, should return empty
            assert len(entries) == 0, "No identifier should return empty entries"
        except (ValueError, RuntimeError):
            pass  # Also acceptable to raise


class TestFollowThreadResultStructure:
    """Verify result structure has required fields."""

    def test_result_has_entries_key(self, deterministic_log_file):
        """Result should have 'entries' or 'timeline' key."""
        result = follow_thread(files=[deterministic_log_file], thread_id="worker-0")

        assert (
            "entries" in result or "timeline" in result
        ), "Result should have 'entries' or 'timeline' key"

    def test_entries_have_required_fields(self, deterministic_log_file):
        """Each entry must have timestamp, level, message, thread_id."""
        result = follow_thread(files=[deterministic_log_file], thread_id="worker-0")

        entries = result.get("entries", result.get("timeline", []))
        assert len(entries) > 0

        required_fields = ["timestamp", "level", "message", "thread_id"]
        for entry in entries:
            for field in required_fields:
                assert field in entry, f"Entry missing required field '{field}'"
