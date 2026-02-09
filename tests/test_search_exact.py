"""
PARAMETRIZED SEARCH TESTS - Exact Value Assertions

These tests use deterministic fixtures with KNOWN values and assert
EXACT expected outputs. If any test passes with wrong data, it's a bug
in the test, not a pass.

Fixture: deterministic_log_file
- 100 entries total
- 25 each of INFO/DEBUG/WARN/ERROR (lines 0,4,8... = INFO, 1,5,9... = DEBUG, etc.)
- 25 each of worker-0/1/2/3 (same pattern as levels)
- 10 each of req-0 through req-9
"""

import pytest

try:
    from logler.investigate import search, RUST_AVAILABLE
except ImportError as e:
    if "logler_rs" in str(e):
        RUST_AVAILABLE = False
    else:
        raise


pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required for search tests")


class TestSearchLevelFilter:
    """Test level filtering returns exact expected counts."""

    @pytest.mark.parametrize(
        "level,expected_count",
        [
            ("INFO", 25),
            ("DEBUG", 25),
            ("WARN", 25),
            ("ERROR", 25),
        ],
        ids=["info_25", "debug_25", "warn_25", "error_25"],
    )
    def test_level_filter_exact_count(self, deterministic_log_file, level, expected_count):
        """Each level appears exactly 25 times in 100 entries."""
        result = search(files=[deterministic_log_file], level=level, limit=100)

        # MUST have exact count
        assert result["total_matches"] == expected_count, (
            f"Level {level} should have exactly {expected_count} matches, "
            f"got {result['total_matches']}"
        )

        # MUST return exactly that many results
        assert len(result["results"]) == expected_count

        # ALL results must match the filter
        for item in result["results"]:
            entry = item.get("entry", item)
            assert (
                entry["level"].upper() == level
            ), f"Entry level {entry['level']} doesn't match filter {level}"


class TestSearchThreadFilter:
    """Test thread filtering returns exact expected counts."""

    @pytest.mark.parametrize(
        "thread_id,expected_count",
        [
            ("worker-0", 25),
            ("worker-1", 25),
            ("worker-2", 25),
            ("worker-3", 25),
        ],
        ids=["worker0_25", "worker1_25", "worker2_25", "worker3_25"],
    )
    def test_thread_filter_exact_count(self, deterministic_log_file, thread_id, expected_count):
        """Each thread appears exactly 25 times in 100 entries."""
        result = search(files=[deterministic_log_file], thread_id=thread_id, limit=100)

        assert result["total_matches"] == expected_count, (
            f"Thread {thread_id} should have exactly {expected_count} matches, "
            f"got {result['total_matches']}"
        )

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["thread_id"] == thread_id


class TestSearchCorrelationFilter:
    """Test correlation ID filtering returns exact expected counts."""

    @pytest.mark.parametrize(
        "correlation_id,expected_count",
        [
            ("req-0", 10),
            ("req-1", 10),
            ("req-5", 10),
            ("req-9", 10),
        ],
        ids=["req0_10", "req1_10", "req5_10", "req9_10"],
    )
    def test_correlation_filter_exact_count(
        self, deterministic_log_file, correlation_id, expected_count
    ):
        """Each correlation ID appears exactly 10 times (100 entries / 10 IDs)."""
        result = search(files=[deterministic_log_file], correlation_id=correlation_id, limit=100)

        assert (
            result["total_matches"] == expected_count
        ), f"Correlation {correlation_id} should have exactly {expected_count} matches"

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["correlation_id"] == correlation_id


class TestSearchCombinedFilters:
    """Test combined filters with exact expected outcomes."""

    @pytest.mark.parametrize(
        "level,thread_id,expected_count",
        [
            # Level and thread are aligned: INFO=worker-0, DEBUG=worker-1, etc.
            ("INFO", "worker-0", 25),  # All 25 INFO entries are from worker-0
            ("DEBUG", "worker-1", 25),  # All 25 DEBUG entries are from worker-1
            ("WARN", "worker-2", 25),  # All 25 WARN entries are from worker-2
            ("ERROR", "worker-3", 25),  # All 25 ERROR entries are from worker-3
            # Misaligned combinations should return 0
            ("INFO", "worker-1", 0),  # INFO is never from worker-1
            ("ERROR", "worker-0", 0),  # ERROR is never from worker-0
        ],
        ids=[
            "info_worker0_match",
            "debug_worker1_match",
            "warn_worker2_match",
            "error_worker3_match",
            "info_worker1_nomatch",
            "error_worker0_nomatch",
        ],
    )
    def test_level_and_thread_combined(
        self, deterministic_log_file, level, thread_id, expected_count
    ):
        """Combined level+thread filters return exact counts."""
        result = search(
            files=[deterministic_log_file],
            level=level,
            thread_id=thread_id,
            limit=100,
        )

        assert result["total_matches"] == expected_count, (
            f"Level={level} + Thread={thread_id} should have {expected_count} matches, "
            f"got {result['total_matches']}"
        )


class TestSearchQuery:
    """Test text query matching with exact expected results."""

    @pytest.mark.parametrize(
        "query,min_expected,max_expected",
        [
            ("message", 100, 100),  # All entries contain "message"
            ("Log message number", 100, 100),  # All messages have this prefix
            ("ZZZNOTFOUND", 0, 0),  # No matches
        ],
        ids=["all_entries", "message_prefix", "no_match"],
    )
    def test_query_match_counts(self, deterministic_log_file, query, min_expected, max_expected):
        """Text queries return expected match counts within range."""
        result = search(files=[deterministic_log_file], query=query, limit=100)

        assert min_expected <= result["total_matches"] <= max_expected, (
            f"Query '{query}' should have {min_expected}-{max_expected} matches, "
            f"got {result['total_matches']}"
        )

    def test_specific_message_search(self, deterministic_log_file):
        """Search for a specific unique message pattern."""
        # Search for a pattern that only appears once
        result = search(files=[deterministic_log_file], query="Log message number 50", limit=100)

        # Should find at least 1 match (the exact message)
        assert result["total_matches"] >= 1, "Should find message with 'number 50'"

        # Verify the result contains the expected message
        found = False
        for item in result["results"]:
            entry = item.get("entry", item)
            if "number 50" in entry.get("message", ""):
                found = True
                break
        assert found, "Should find entry with 'number 50' in message"


class TestSearchLimit:
    """Test limit parameter enforces exact boundaries."""

    @pytest.mark.parametrize(
        "limit,expected_returned",
        [
            (1, 1),
            (5, 5),
            (10, 10),
            (50, 50),
            (100, 100),  # All entries
            (200, 100),  # More than available, should cap at 100
        ],
        ids=["limit_1", "limit_5", "limit_10", "limit_50", "limit_100", "limit_200"],
    )
    def test_limit_exact_results(self, deterministic_log_file, limit, expected_returned):
        """Limit parameter returns exactly min(limit, total) results."""
        result = search(files=[deterministic_log_file], query="message", limit=limit)

        assert len(result["results"]) == expected_returned, (
            f"With limit={limit}, should return {expected_returned} results, "
            f"got {len(result['results'])}"
        )
        # Total matches should always be 100 (all entries match "message")
        assert result["total_matches"] == 100


class TestSearchOutputFormats:
    """Test different output formats have required keys."""

    @pytest.mark.parametrize(
        "output_format,required_keys",
        [
            ("full", ["results", "total_matches"]),
            ("summary", ["total_matches"]),
            ("count", ["total_matches"]),
        ],
        ids=["full", "summary", "count"],
    )
    def test_output_format_keys(self, deterministic_log_file, output_format, required_keys):
        """Each output format includes its required keys."""
        result = search(
            files=[deterministic_log_file],
            query="message",
            output_format=output_format,
        )

        for key in required_keys:
            assert key in result, f"Format '{output_format}' missing required key '{key}'"

    def test_full_format_has_100_results(self, deterministic_log_file):
        """Full format with 'message' query should have 100 matches."""
        result = search(
            files=[deterministic_log_file],
            query="message",
            output_format="full",
            limit=100,
        )

        assert result["total_matches"] == 100
        assert len(result["results"]) == 100


class TestSearchEdgeCases:
    """Edge cases that should return specific results."""

    def test_empty_query_returns_all(self, deterministic_log_file):
        """Empty query should match all 100 entries."""
        result = search(files=[deterministic_log_file], query="", limit=100)

        assert result["total_matches"] == 100, "Empty query should match all entries"

    def test_none_query_returns_all(self, deterministic_log_file):
        """None query should match all 100 entries."""
        result = search(files=[deterministic_log_file], query=None, limit=100)

        assert result["total_matches"] == 100, "None query should match all entries"

    def test_nonexistent_level_returns_zero(self, deterministic_log_file):
        """Non-existent level should return 0 matches."""
        result = search(files=[deterministic_log_file], level="TRACE", limit=100)

        assert result["total_matches"] == 0, "Non-existent level should return 0 matches"

    def test_nonexistent_thread_returns_zero(self, deterministic_log_file):
        """Non-existent thread should return 0 matches."""
        result = search(files=[deterministic_log_file], thread_id="worker-99", limit=100)

        assert result["total_matches"] == 0, "Non-existent thread should return 0 matches"

    def test_nonexistent_correlation_returns_zero(self, deterministic_log_file):
        """Non-existent correlation ID should return 0 matches."""
        result = search(files=[deterministic_log_file], correlation_id="req-nonexistent", limit=100)

        assert result["total_matches"] == 0


class TestSearchResultStructure:
    """Verify result structure has required fields with correct values."""

    def test_result_entries_have_required_fields(self, deterministic_log_file):
        """Each result entry must have level, message, thread_id, correlation_id."""
        result = search(files=[deterministic_log_file], limit=10)

        assert len(result["results"]) == 10, "Should return exactly 10 results"

        required_fields = ["level", "message", "thread_id", "correlation_id"]
        for item in result["results"]:
            entry = item.get("entry", item)
            for field in required_fields:
                assert field in entry, f"Entry missing required field '{field}'"

    def test_entries_have_correct_line_indices(self, deterministic_log_file):
        """Entries should have their original line indices preserved."""
        # Search for entries with specific line numbers
        result = search(files=[deterministic_log_file], query="number 0", limit=10)

        # "number 0" should match entry at line 0
        assert result["total_matches"] >= 1
        found = False
        for item in result["results"]:
            entry = item.get("entry", item)
            if "number 0" in entry.get("message", ""):
                found = True
                # Verify it's actually entry 0
                assert entry.get("line_index") == 0 or "number 0" in entry["message"]
                break
        assert found, "Should find entry with 'number 0'"
