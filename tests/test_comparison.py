"""Tests for comparison.py OOM prevention and correctness fixes."""

from unittest.mock import patch, call


from logler.comparison import (
    _analyze_thread,
    _DEFAULT_TIMELINE_LIMIT,
    compare_threads,
    compare_time_periods,
    cross_service_timeline,
)


# ---------------------------------------------------------------------------
# Fix 1: compare_time_periods pushes time filters to Rust
# ---------------------------------------------------------------------------


class TestCompareTimePeriodsTimeFilters:
    """Verify compare_time_periods() calls search() with time_start/time_end
    instead of fetching everything and filtering in Python."""

    @patch("logler.comparison.search")
    @patch("logler._search_core.RUST_AVAILABLE", True)
    def test_compare_time_periods_uses_time_filters(self, mock_search):
        """search() must receive time_start/time_end — no single limit=0 call."""
        mock_search.return_value = {"results": []}

        result = compare_time_periods(
            files=["app.log"],
            period_a_start="2024-01-01T14:00:00Z",
            period_a_end="2024-01-01T15:00:00Z",
            period_b_start="2024-01-01T15:00:00Z",
            period_b_end="2024-01-01T16:00:00Z",
        )

        # Must be exactly 2 calls — one per period
        assert mock_search.call_count == 2

        call_a = mock_search.call_args_list[0]
        call_b = mock_search.call_args_list[1]

        # Period A: time_start and time_end match
        assert call_a == call(
            ["app.log"],
            time_start="2024-01-01T14:00:00Z",
            time_end="2024-01-01T15:00:00Z",
            limit=0,
        )

        # Period B: time_start and time_end match
        assert call_b == call(
            ["app.log"],
            time_start="2024-01-01T15:00:00Z",
            time_end="2024-01-01T16:00:00Z",
            limit=0,
        )

        # Both periods empty → zero logs, zero errors
        assert result["period_a"]["total_logs"] == 0
        assert result["period_a"]["error_count"] == 0
        assert result["period_b"]["total_logs"] == 0
        assert result["period_b"]["error_count"] == 0

    @patch("logler.comparison.search")
    @patch("logler._search_core.RUST_AVAILABLE", True)
    def test_compare_time_periods_passes_results_to_analysis(self, mock_search):
        """Entries from each search call feed into the correct period analysis."""
        entry_a = {
            "entry": {
                "timestamp": "2024-01-01T14:30:00Z",
                "level": "ERROR",
                "message": "boom",
            }
        }
        entry_b = {
            "entry": {
                "timestamp": "2024-01-01T15:30:00Z",
                "level": "INFO",
                "message": "ok",
            }
        }

        mock_search.side_effect = [
            {"results": [entry_a]},
            {"results": [entry_b]},
        ]

        result = compare_time_periods(
            files=["app.log"],
            period_a_start="2024-01-01T14:00:00Z",
            period_a_end="2024-01-01T15:00:00Z",
            period_b_start="2024-01-01T15:00:00Z",
            period_b_end="2024-01-01T16:00:00Z",
        )

        assert result["period_a"]["total_logs"] == 1
        assert result["period_a"]["error_count"] == 1
        assert result["period_b"]["total_logs"] == 1
        assert result["period_b"]["error_count"] == 0


# ---------------------------------------------------------------------------
# Fix 1b: cross_service_timeline fallback is capped
# ---------------------------------------------------------------------------


class TestCrossServiceTimelineFallbackCap:
    """Verify the fallback (no correlation/trace ID) uses a capped limit."""

    @patch("logler.comparison.search")
    @patch("logler._search_core.RUST_AVAILABLE", True)
    def test_cross_service_timeline_fallback_capped(self, mock_search):
        """Fallback path must use limit=_DEFAULT_TIMELINE_LIMIT, not limit=0."""
        mock_search.return_value = {"results": []}

        cross_service_timeline(files={"svc": ["svc.log"]})

        assert mock_search.call_count == 1
        _, kwargs = mock_search.call_args
        assert kwargs["limit"] == _DEFAULT_TIMELINE_LIMIT

    def test_default_timeline_limit_value(self):
        """Constant must be 10_000."""
        assert _DEFAULT_TIMELINE_LIMIT == 10_000


# ---------------------------------------------------------------------------
# Fix 3: _analyze_thread uses min/max timestamps for duration
# ---------------------------------------------------------------------------


class TestAnalyzeThreadDuration:
    """Verify _analyze_thread computes duration from min/max, not positional."""

    def test_sorted_entries(self):
        """Sorted entries: duration == last - first (same as before)."""
        entries = [
            {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "a"},
            {"timestamp": "2024-01-01T10:00:01Z", "level": "INFO", "message": "b"},
            {"timestamp": "2024-01-01T10:00:03Z", "level": "INFO", "message": "c"},
        ]
        result = _analyze_thread(entries, "t1")
        assert result["duration_ms"] == 3000

    def test_unordered_entries(self):
        """Out-of-order entries: duration must still be max - min."""
        entries = [
            {"timestamp": "2024-01-01T10:00:02Z", "level": "INFO", "message": "middle"},
            {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "earliest"},
            {"timestamp": "2024-01-01T10:00:05Z", "level": "INFO", "message": "latest"},
            {"timestamp": "2024-01-01T10:00:01Z", "level": "INFO", "message": "second"},
        ]
        result = _analyze_thread(entries, "t1")
        # max(10:00:05) - min(10:00:00) = 5000ms
        assert result["duration_ms"] == 5000

    def test_single_entry(self):
        """Single entry: duration is 0 (fewer than 2 timestamps)."""
        entries = [
            {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "only"},
        ]
        result = _analyze_thread(entries, "t1")
        assert result["duration_ms"] == 0

    def test_empty_entries(self):
        """No entries: full return shape with zeroes."""
        result = _analyze_thread([], "t1")
        assert result["id"] == "t1"
        assert result["entries"] == []
        assert result["entry_count"] == 0
        assert result["duration_ms"] == 0
        assert result["error_count"] == 0
        assert result["log_levels"] == {}
        assert result["unique_messages"] == 0

    def test_entries_with_missing_timestamps(self):
        """Entries missing timestamps are skipped — duration from valid ones."""
        entries = [
            {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "a"},
            {"level": "INFO", "message": "no ts"},
            {"timestamp": "", "level": "INFO", "message": "empty ts"},
            {"timestamp": "2024-01-01T10:00:04Z", "level": "INFO", "message": "b"},
        ]
        result = _analyze_thread(entries, "t1")
        assert result["duration_ms"] == 4000

    def test_entries_with_only_one_valid_timestamp(self):
        """Only one valid timestamp among many entries: duration is 0."""
        entries = [
            {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "a"},
            {"level": "INFO", "message": "no ts"},
            {"timestamp": "", "level": "INFO", "message": "empty ts"},
        ]
        result = _analyze_thread(entries, "t1")
        assert result["duration_ms"] == 0

    def test_reverse_ordered_entries(self):
        """Reverse-ordered entries: old code would compute negative, new code uses min/max."""
        entries = [
            {"timestamp": "2024-01-01T10:00:05Z", "level": "INFO", "message": "latest"},
            {"timestamp": "2024-01-01T10:00:03Z", "level": "INFO", "message": "mid"},
            {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "earliest"},
        ]
        result = _analyze_thread(entries, "t1")
        # Must be positive 5000, not negative -5000
        assert result["duration_ms"] == 5000

    def test_other_fields_still_correct(self):
        """min/max change doesn't break other analysis fields."""
        entries = [
            {"timestamp": "2024-01-01T10:00:03Z", "level": "ERROR", "message": "fail"},
            {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "ok"},
            {"timestamp": "2024-01-01T10:00:01Z", "level": "WARN", "message": "hmm"},
        ]
        result = _analyze_thread(entries, "t1")
        assert result["id"] == "t1"
        assert result["entry_count"] == 3
        assert result["error_count"] == 1
        assert result["log_levels"] == {"ERROR": 1, "INFO": 1, "WARN": 1}
        assert result["unique_messages"] == 3
        assert result["duration_ms"] == 3000


# ---------------------------------------------------------------------------
# compare_threads integration (uses follow_thread mock)
# ---------------------------------------------------------------------------


class TestCompareThreads:
    """Verify compare_threads produces correct diffs and survives edge cases."""

    @patch("logler.comparison.follow_thread")
    @patch("logler._search_core.RUST_AVAILABLE", True)
    def test_two_threads_duration_and_errors(self, mock_follow):
        """Duration diff and error diff computed from two real threads."""
        mock_follow.side_effect = [
            {
                "entries": [
                    {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "start"},
                    {"timestamp": "2024-01-01T10:00:02Z", "level": "INFO", "message": "end"},
                ]
            },
            {
                "entries": [
                    {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "start"},
                    {"timestamp": "2024-01-01T10:00:05Z", "level": "ERROR", "message": "crash"},
                ]
            },
        ]

        result = compare_threads(["app.log"], correlation_a="ok", correlation_b="fail")

        assert result["thread_a"]["duration_ms"] == 2000
        assert result["thread_b"]["duration_ms"] == 5000
        assert result["differences"]["duration_diff_ms"] == 3000
        assert result["thread_a"]["error_count"] == 0
        assert result["thread_b"]["error_count"] == 1
        assert result["differences"]["error_diff"] == 1

    @patch("logler.comparison.follow_thread")
    @patch("logler._search_core.RUST_AVAILABLE", True)
    def test_one_thread_empty(self, mock_follow):
        """Empty thread must not crash — exercises entry_count in empty return."""
        mock_follow.side_effect = [
            {"entries": []},
            {
                "entries": [
                    {"timestamp": "2024-01-01T10:00:00Z", "level": "ERROR", "message": "fail"},
                    {"timestamp": "2024-01-01T10:00:01Z", "level": "ERROR", "message": "fail2"},
                ]
            },
        ]

        result = compare_threads(["app.log"], correlation_a="gone", correlation_b="here")

        assert result["thread_a"]["entry_count"] == 0
        assert result["thread_b"]["entry_count"] == 2
        assert result["differences"]["entry_count_diff"] == 2
        assert result["differences"]["error_diff"] == 2

    @patch("logler.comparison.follow_thread")
    @patch("logler._search_core.RUST_AVAILABLE", True)
    def test_identical_threads(self, mock_follow):
        """Identical threads: all diffs are zero, summary says 'similar'."""
        entries = [
            {"timestamp": "2024-01-01T10:00:00Z", "level": "INFO", "message": "hello"},
        ]
        mock_follow.side_effect = [
            {"entries": entries},
            {"entries": entries},
        ]

        result = compare_threads(["app.log"], thread_a="t1", thread_b="t1")

        assert result["differences"]["duration_diff_ms"] == 0
        assert result["differences"]["error_diff"] == 0
        assert result["differences"]["entry_count_diff"] == 0
        assert "similar" in result["summary"].lower()
