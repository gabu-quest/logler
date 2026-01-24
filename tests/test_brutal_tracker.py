"""
BRUTAL THREAD TRACKER TESTS - Chaos Edition

These tests throw every conceivable edge case at the ThreadTracker
to ensure it handles real-world chaos gracefully.
"""

import pytest
from datetime import datetime, timezone, timedelta
from logler.parser import LogEntry
from logler.tracker import ThreadTracker


class TestBasicTracking:
    """Basic tracking functionality under stress."""

    @pytest.fixture
    def tracker(self):
        return ThreadTracker()

    def test_track_empty_entry(self, tracker):
        """Track an entry with no metadata"""
        entry = LogEntry(line_number=1, raw="Just a message")
        tracker.track(entry)
        # Should not crash, but won't track anything
        assert tracker.get_all_threads() == []
        assert tracker.get_all_traces() == []

    def test_track_thread_only(self, tracker):
        """Track entry with only thread_id"""
        entry = LogEntry(line_number=1, raw="test", thread_id="worker-1", level="INFO")
        tracker.track(entry)
        thread = tracker.get_thread("worker-1")
        assert thread is not None
        assert thread["thread_id"] == "worker-1"
        assert thread["log_count"] == 1

    def test_track_trace_only(self, tracker):
        """Track entry with only trace_id"""
        entry = LogEntry(line_number=1, raw="test", trace_id="abcd1234abcd1234", span_id="efef5678")
        tracker.track(entry)
        trace = tracker.get_trace("abcd1234abcd1234")
        assert trace is not None
        assert len(trace["spans"]) == 1

    def test_track_correlation_only(self, tracker):
        """Track entry with only correlation_id"""
        entry = LogEntry(line_number=1, raw="test", correlation_id="req-123")
        tracker.track(entry)
        corr = tracker.get_by_correlation("req-123")
        assert len(corr) == 1


class TestThreadTracking:
    """Thread tracking edge cases."""

    @pytest.fixture
    def tracker(self):
        return ThreadTracker()

    def test_multiple_entries_same_thread(self, tracker):
        """Multiple entries for same thread"""
        for i in range(100):
            # Use minutes and seconds to stay within valid ranges
            minute = i // 60
            second = i % 60
            entry = LogEntry(
                line_number=i,
                raw=f"Message {i}",
                thread_id="worker-1",
                level="INFO",
                timestamp=datetime(2024, 1, 1, 10, minute, second, tzinfo=timezone.utc),
            )
            tracker.track(entry)

        thread = tracker.get_thread("worker-1")
        assert thread["log_count"] == 100
        assert thread["first_seen"] == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert thread["last_seen"] == datetime(2024, 1, 1, 10, 1, 39, tzinfo=timezone.utc)

    def test_thread_error_counting(self, tracker):
        """Count errors per thread"""
        levels = ["INFO", "ERROR", "INFO", "FATAL", "INFO", "CRITICAL", "DEBUG"]
        for i, level in enumerate(levels):
            entry = LogEntry(line_number=i, raw=f"Message {i}", thread_id="worker-1", level=level)
            tracker.track(entry)

        thread = tracker.get_thread("worker-1")
        assert thread["error_count"] == 3  # ERROR, FATAL, CRITICAL

    def test_thread_with_correlation_ids(self, tracker):
        """Thread accumulates correlation IDs"""
        for i in range(5):
            entry = LogEntry(
                line_number=i, raw=f"Message {i}", thread_id="worker-1", correlation_id=f"req-{i}"
            )
            tracker.track(entry)

        thread = tracker.get_thread("worker-1")
        assert len(thread["correlation_ids"]) == 5

    def test_many_threads(self, tracker):
        """Track many different threads"""
        for i in range(1000):
            entry = LogEntry(
                line_number=i, raw=f"Message {i}", thread_id=f"worker-{i}", level="INFO"
            )
            tracker.track(entry)

        all_threads = tracker.get_all_threads()
        assert len(all_threads) == 1000

    def test_out_of_order_timestamps(self, tracker):
        """Entries arrive out of timestamp order"""
        timestamps = [
            datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),  # Middle
            datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),  # First
            datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc),  # Last
        ]
        for i, ts in enumerate(timestamps):
            entry = LogEntry(line_number=i, raw=f"Message {i}", thread_id="worker-1", timestamp=ts)
            tracker.track(entry)

        thread = tracker.get_thread("worker-1")
        assert thread["first_seen"] == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert thread["last_seen"] == datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

    def test_entries_with_none_timestamp(self, tracker):
        """Some entries have None timestamp"""
        for i in range(5):
            ts = datetime(2024, 1, 1, 10, 0, i, tzinfo=timezone.utc) if i % 2 == 0 else None
            entry = LogEntry(line_number=i, raw=f"Message {i}", thread_id="worker-1", timestamp=ts)
            tracker.track(entry)

        thread = tracker.get_thread("worker-1")
        assert thread["log_count"] == 5
        # First/last should be from entries that have timestamps
        assert thread["first_seen"] is not None

    def test_all_entries_none_timestamp(self, tracker):
        """All entries have None timestamp"""
        for i in range(5):
            entry = LogEntry(
                line_number=i, raw=f"Message {i}", thread_id="worker-1", timestamp=None
            )
            tracker.track(entry)

        thread = tracker.get_thread("worker-1")
        assert thread["log_count"] == 5
        assert thread["first_seen"] is None
        assert thread["last_seen"] is None


class TestTraceTracking:
    """Trace and span tracking edge cases."""

    @pytest.fixture
    def tracker(self):
        return ThreadTracker()

    def test_single_span_trace(self, tracker):
        """Trace with single span"""
        entry = LogEntry(
            line_number=1,
            raw="test",
            trace_id="trace-123",
            span_id="span-1",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        tracker.track(entry)

        trace = tracker.get_trace("trace-123")
        assert trace is not None
        assert len(trace["spans"]) == 1
        assert trace["spans"][0]["span_id"] == "span-1"

    def test_multi_span_trace(self, tracker):
        """Trace with multiple spans"""
        for i in range(10):
            entry = LogEntry(
                line_number=i,
                raw=f"Span {i}",
                trace_id="trace-123",
                span_id=f"span-{i}",
                timestamp=datetime(2024, 1, 1, 10, 0, i, tzinfo=timezone.utc),
            )
            tracker.track(entry)

        trace = tracker.get_trace("trace-123")
        assert len(trace["spans"]) == 10

    def test_trace_duration_calculation(self, tracker):
        """Trace duration calculated correctly"""
        entry1 = LogEntry(
            line_number=1,
            raw="start",
            trace_id="trace-123",
            span_id="span-1",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        entry2 = LogEntry(
            line_number=2,
            raw="end",
            trace_id="trace-123",
            span_id="span-2",
            timestamp=datetime(2024, 1, 1, 10, 0, 5, tzinfo=timezone.utc),  # 5 seconds later
        )
        tracker.track(entry1)
        tracker.track(entry2)

        trace = tracker.get_trace("trace-123")
        assert trace["duration_ms"] == 5000.0

    def test_trace_service_tracking(self, tracker):
        """Services tracked within trace"""
        services = ["auth", "api", "db", "cache"]
        for i, svc in enumerate(services):
            entry = LogEntry(
                line_number=i,
                raw=f"Service {svc}",
                trace_id="trace-123",
                span_id=f"span-{i}",
                service_name=svc,
            )
            tracker.track(entry)

        trace = tracker.get_trace("trace-123")
        assert set(trace["services"]) == set(services)

    def test_trace_entries_without_span_id(self, tracker):
        """Trace entries without span_id"""
        entry = LogEntry(
            line_number=1,
            raw="test",
            trace_id="trace-123",
            span_id=None,  # No span ID
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        tracker.track(entry)

        trace = tracker.get_trace("trace-123")
        # Should still track the trace, but spans list might be empty
        assert trace is not None

    def test_many_traces(self, tracker):
        """Track many different traces"""
        for i in range(500):
            entry = LogEntry(
                line_number=i, raw=f"Trace {i}", trace_id=f"trace-{i}", span_id=f"span-{i}"
            )
            tracker.track(entry)

        all_traces = tracker.get_all_traces()
        assert len(all_traces) == 500

    def test_nonexistent_trace(self, tracker):
        """Get non-existent trace returns None"""
        result = tracker.get_trace("does-not-exist")
        assert result is None


class TestCorrelationTracking:
    """Correlation ID tracking edge cases."""

    @pytest.fixture
    def tracker(self):
        return ThreadTracker()

    def test_single_correlation_entry(self, tracker):
        """Single entry per correlation"""
        entry = LogEntry(line_number=1, raw="test", correlation_id="req-123")
        tracker.track(entry)

        entries = tracker.get_by_correlation("req-123")
        assert len(entries) == 1

    def test_multiple_entries_same_correlation(self, tracker):
        """Multiple entries with same correlation ID"""
        for i in range(20):
            entry = LogEntry(line_number=i, raw=f"Message {i}", correlation_id="req-123")
            tracker.track(entry)

        entries = tracker.get_by_correlation("req-123")
        assert len(entries) == 20

    def test_many_correlations(self, tracker):
        """Track many different correlation IDs"""
        for i in range(1000):
            entry = LogEntry(line_number=i, raw=f"Request {i}", correlation_id=f"req-{i}")
            tracker.track(entry)

        all_corr = tracker.get_all_correlations()
        assert len(all_corr) == 1000

    def test_nonexistent_correlation(self, tracker):
        """Get non-existent correlation returns empty list"""
        result = tracker.get_by_correlation("does-not-exist")
        assert result == []


class TestCombinedTracking:
    """Combined thread, trace, and correlation tracking."""

    @pytest.fixture
    def tracker(self):
        return ThreadTracker()

    def test_entry_with_all_ids(self, tracker):
        """Entry with thread, trace, and correlation IDs"""
        entry = LogEntry(
            line_number=1,
            raw="Full entry",
            thread_id="worker-1",
            trace_id="trace-123",
            span_id="span-1",
            correlation_id="req-456",
            service_name="api",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        tracker.track(entry)

        thread = tracker.get_thread("worker-1")
        trace = tracker.get_trace("trace-123")
        corr = tracker.get_by_correlation("req-456")

        assert thread is not None
        assert trace is not None
        assert len(corr) == 1

    def test_cross_thread_correlation(self, tracker):
        """Same correlation ID across different threads"""
        for i in range(5):
            entry = LogEntry(
                line_number=i,
                raw=f"Thread {i}",
                thread_id=f"worker-{i}",
                correlation_id="shared-req",
            )
            tracker.track(entry)

        corr = tracker.get_by_correlation("shared-req")
        assert len(corr) == 5

        # Each thread should have the correlation ID
        for i in range(5):
            thread = tracker.get_thread(f"worker-{i}")
            assert "shared-req" in thread["correlation_ids"]

    def test_thread_sorted_by_log_count(self, tracker):
        """get_all_threads returns sorted by log count"""
        # Create threads with different log counts
        for _ in range(10):
            entry = LogEntry(line_number=1, raw="many", thread_id="busy-worker")
            tracker.track(entry)
        for _ in range(5):
            entry = LogEntry(line_number=2, raw="some", thread_id="medium-worker")
            tracker.track(entry)
        for _ in range(1):
            entry = LogEntry(line_number=3, raw="one", thread_id="lazy-worker")
            tracker.track(entry)

        threads = tracker.get_all_threads()
        assert threads[0]["thread_id"] == "busy-worker"
        assert threads[0]["log_count"] == 10
        assert threads[1]["thread_id"] == "medium-worker"
        assert threads[2]["thread_id"] == "lazy-worker"


class TestEdgeCaseIDs:
    """Edge cases in ID formats."""

    @pytest.fixture
    def tracker(self):
        return ThreadTracker()

    def test_empty_string_thread_id(self, tracker):
        """Empty string as thread ID"""
        entry = LogEntry(line_number=1, raw="test", thread_id="")
        tracker.track(entry)
        # Empty string is falsy, should not be tracked
        assert tracker.get_all_threads() == []

    def test_whitespace_thread_id(self, tracker):
        """Whitespace-only thread ID"""
        entry = LogEntry(line_number=1, raw="test", thread_id="   ")
        tracker.track(entry)
        # Depends on implementation - test that it doesn't crash
        threads = tracker.get_all_threads()
        # May or may not track whitespace-only ID
        assert isinstance(threads, list)

    def test_very_long_thread_id(self, tracker):
        """Very long thread ID"""
        long_id = "x" * 10000
        entry = LogEntry(line_number=1, raw="test", thread_id=long_id)
        tracker.track(entry)
        thread = tracker.get_thread(long_id)
        assert thread is not None

    def test_unicode_thread_id(self, tracker):
        """Unicode characters in thread ID"""
        entry = LogEntry(line_number=1, raw="test", thread_id="ワーカー-1")
        tracker.track(entry)
        thread = tracker.get_thread("ワーカー-1")
        assert thread is not None

    def test_special_chars_in_ids(self, tracker):
        """Special characters in IDs"""
        special_ids = [
            "thread/with/slashes",
            "thread:with:colons",
            "thread@with@at",
            "thread#with#hash",
            "thread$with$dollar",
            "thread%with%percent",
            "thread&with&amp",
            "thread=with=equals",
        ]
        for i, tid in enumerate(special_ids):
            entry = LogEntry(line_number=i, raw="test", thread_id=tid)
            tracker.track(entry)

        for tid in special_ids:
            thread = tracker.get_thread(tid)
            assert thread is not None, f"Failed for ID: {tid}"


class TestTimezoneHandling:
    """Timezone edge cases."""

    @pytest.fixture
    def tracker(self):
        return ThreadTracker()

    def test_mixed_timezones(self, tracker):
        """Entries with different timezones"""
        tz_utc = timezone.utc
        tz_plus5 = timezone(timedelta(hours=5))
        tz_minus8 = timezone(timedelta(hours=-8))

        entries = [
            LogEntry(
                line_number=1,
                raw="UTC",
                thread_id="worker-1",
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=tz_utc),
            ),
            LogEntry(
                line_number=2,
                raw="Plus 5",
                thread_id="worker-1",
                timestamp=datetime(2024, 1, 1, 17, 0, 0, tzinfo=tz_plus5),  # Same as 12:00 UTC
            ),
            LogEntry(
                line_number=3,
                raw="Minus 8",
                thread_id="worker-1",
                timestamp=datetime(2024, 1, 1, 4, 0, 0, tzinfo=tz_minus8),  # Same as 12:00 UTC
            ),
        ]

        for entry in entries:
            tracker.track(entry)

        thread = tracker.get_thread("worker-1")
        assert thread["log_count"] == 3
        # All should be equal when normalized to UTC

    def test_naive_vs_aware_timestamps(self, tracker):
        """Mix of timezone-aware and naive timestamps - known limitation"""
        aware_entry = LogEntry(
            line_number=1,
            raw="Aware",
            thread_id="worker-1",
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        naive_entry = LogEntry(
            line_number=2,
            raw="Naive",
            thread_id="worker-1",
            timestamp=datetime(2024, 1, 1, 13, 0, 0),  # No timezone
        )

        # Track the aware entry first
        tracker.track(aware_entry)

        # Mixing aware and naive timestamps will cause TypeError in Python
        # This documents a known limitation of the tracker
        with pytest.raises(TypeError):
            tracker.track(naive_entry)


class TestHighVolume:
    """High volume stress tests."""

    def test_million_entries(self):
        """Track a million entries (reduced for test speed)"""
        tracker = ThreadTracker()
        # Use 100k instead of 1M for reasonable test time
        for i in range(100000):
            entry = LogEntry(
                line_number=i,
                raw=f"Message {i}",
                thread_id=f"worker-{i % 100}",  # 100 threads
                correlation_id=f"req-{i % 1000}",  # 1000 correlations
                timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            )
            tracker.track(entry)

        threads = tracker.get_all_threads()
        assert len(threads) == 100

        correlations = tracker.get_all_correlations()
        assert len(correlations) == 1000

        # Verify counts
        for thread in threads:
            assert thread["log_count"] == 1000


class TestStateIsolation:
    """Verify state isolation between trackers."""

    def test_independent_trackers(self):
        """Two trackers don't share state"""
        tracker1 = ThreadTracker()
        tracker2 = ThreadTracker()

        entry1 = LogEntry(line_number=1, raw="test", thread_id="tracker1-thread")
        entry2 = LogEntry(line_number=2, raw="test", thread_id="tracker2-thread")

        tracker1.track(entry1)
        tracker2.track(entry2)

        assert tracker1.get_thread("tracker1-thread") is not None
        assert tracker1.get_thread("tracker2-thread") is None

        assert tracker2.get_thread("tracker2-thread") is not None
        assert tracker2.get_thread("tracker1-thread") is None
