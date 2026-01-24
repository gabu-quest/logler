"""
Contract Tests for README Code Snippets

This file validates that all code examples in README.md work as documented.
Each test corresponds to a Contract ID [CXX] in the README's Public API Contract section.

The test suite proves the README is accurate - when the API changes, these tests
must change with it. CI enforces that documentation matches implementation.
"""

import json
import pytest
import tempfile
from pathlib import Path


# Import with Rust backend check
try:
    from logler.investigate import (
        analyze_with_insights,
        search,
        compare_threads,
        cross_service_timeline,
        InvestigationSession,
        smart_sample,
        explain,
        follow_thread_hierarchy,
        get_hierarchy_summary,
        RUST_AVAILABLE,
    )
except ImportError:
    RUST_AVAILABLE = False

try:
    from logler.tree_formatter import print_tree, print_waterfall

    TREE_FORMATTER_AVAILABLE = True
except ImportError:
    TREE_FORMATTER_AVAILABLE = False


pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required")


# =============================================================================
# Shared Fixtures
# =============================================================================


@pytest.fixture
def app_log():
    """Create a realistic app.log for contract tests"""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        entries = [
            # Mix of levels
            {
                "timestamp": "2024-01-15T10:00:00Z",
                "level": "INFO",
                "message": "Server started",
                "thread_id": "main",
                "correlation_id": "req-001",
            },
            {
                "timestamp": "2024-01-15T10:00:01Z",
                "level": "INFO",
                "message": "Request received",
                "thread_id": "worker-1",
                "correlation_id": "req-001",
            },
            {
                "timestamp": "2024-01-15T10:00:02Z",
                "level": "ERROR",
                "message": "Connection pool exhausted",
                "thread_id": "worker-1",
                "correlation_id": "req-001",
            },
            {
                "timestamp": "2024-01-15T10:00:03Z",
                "level": "WARN",
                "message": "Retrying connection",
                "thread_id": "worker-1",
                "correlation_id": "req-001",
            },
            {
                "timestamp": "2024-01-15T10:00:04Z",
                "level": "INFO",
                "message": "Connection restored",
                "thread_id": "worker-1",
                "correlation_id": "req-001",
            },
            # Another request
            {
                "timestamp": "2024-01-15T10:00:05Z",
                "level": "INFO",
                "message": "Request received",
                "thread_id": "worker-2",
                "correlation_id": "req-002",
            },
            {
                "timestamp": "2024-01-15T10:00:06Z",
                "level": "ERROR",
                "message": "Database timeout",
                "thread_id": "worker-2",
                "correlation_id": "req-002",
            },
            {
                "timestamp": "2024-01-15T10:00:07Z",
                "level": "ERROR",
                "message": "Request failed",
                "thread_id": "worker-2",
                "correlation_id": "req-002",
            },
            # Success request for comparison
            {
                "timestamp": "2024-01-15T10:00:08Z",
                "level": "INFO",
                "message": "Request received",
                "thread_id": "worker-3",
                "correlation_id": "req-success-123",
            },
            {
                "timestamp": "2024-01-15T10:00:09Z",
                "level": "INFO",
                "message": "Request completed",
                "thread_id": "worker-3",
                "correlation_id": "req-success-123",
            },
            # Failed request for comparison
            {
                "timestamp": "2024-01-15T10:00:10Z",
                "level": "INFO",
                "message": "Request received",
                "thread_id": "worker-4",
                "correlation_id": "req-failed-456",
            },
            {
                "timestamp": "2024-01-15T10:00:11Z",
                "level": "ERROR",
                "message": "Service unavailable",
                "thread_id": "worker-4",
                "correlation_id": "req-failed-456",
            },
            # Hierarchy test data with parent_span_id
            {
                "timestamp": "2024-01-15T10:01:00Z",
                "level": "INFO",
                "message": "API call started",
                "thread_id": "api",
                "correlation_id": "req-123",
                "span_id": "span-001",
            },
            {
                "timestamp": "2024-01-15T10:01:01Z",
                "level": "INFO",
                "message": "Auth check",
                "thread_id": "auth",
                "correlation_id": "req-123",
                "span_id": "span-002",
                "parent_span_id": "span-001",
            },
            {
                "timestamp": "2024-01-15T10:01:02Z",
                "level": "INFO",
                "message": "Database query",
                "thread_id": "db",
                "correlation_id": "req-123",
                "span_id": "span-003",
                "parent_span_id": "span-001",
            },
            {
                "timestamp": "2024-01-15T10:01:03Z",
                "level": "INFO",
                "message": "Response sent",
                "thread_id": "api",
                "correlation_id": "req-123",
                "span_id": "span-004",
                "parent_span_id": "span-001",
            },
        ]
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def huge_log():
    """Create a larger log file for smart_sample tests"""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        for i in range(500):
            level = "ERROR" if i % 10 == 0 else "INFO"
            entry = json.dumps(
                {
                    "timestamp": f"2024-01-15T10:{i // 60:02d}:{i % 60:02d}Z",
                    "level": level,
                    "message": f"Log entry {i}",
                    "thread_id": f"worker-{i % 5}",
                    "correlation_id": f"req-{i % 20}",
                }
            )
            f.write(entry + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def multi_service_logs():
    """Create separate log files for multiple services"""
    files = {"api": None, "db": None, "cache": None}
    paths = []

    for service in files.keys():
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=f"_{service}.log") as f:
            for i in range(10):
                entry = json.dumps(
                    {
                        "timestamp": f"2024-01-15T10:00:{i:02d}Z",
                        "level": "INFO",
                        "message": f"{service} processing",
                        "thread_id": f"{service}-worker",
                        "correlation_id": "req-12345",
                        "service": service,
                    }
                )
                f.write(entry + "\n")
            files[service] = [f.name]
            paths.append(f.name)

    yield files

    for path in paths:
        Path(path).unlink()


# =============================================================================
# Contract Tests - README Public API Contract Section
# =============================================================================


class TestC01AutoInsightsAnalysis:
    """[C01] analyze_with_insights returns insights, overview, suggestions"""

    def test_returns_insights_key(self, app_log):
        result = analyze_with_insights(files=[app_log])
        assert "insights" in result, "Result must have 'insights' key"
        assert isinstance(result["insights"], list), "insights must be a list"

    def test_returns_overview(self, app_log):
        result = analyze_with_insights(files=[app_log])
        assert "overview" in result, "Result must have 'overview' key"
        overview = result["overview"]
        assert "total_logs" in overview, "overview must have total_logs"
        assert "error_count" in overview, "overview must have error_count"


class TestC02TokenEfficientSearch:
    """[C02] search with output_format='summary' returns aggregated stats"""

    def test_summary_format_returns_dict(self, app_log):
        errors = search(files=[app_log], level="ERROR", output_format="summary")
        assert isinstance(errors, dict), "search with summary format must return dict"

    def test_summary_format_has_aggregated_data(self, app_log):
        errors = search(files=[app_log], level="ERROR", output_format="summary")
        # Summary format should have summary_stats or similar aggregated data
        assert (
            "total_matches" in errors or "summary_stats" in errors
        ), "Summary format should have aggregated statistics"

    def test_summary_smaller_than_full(self, app_log):
        """Summary format should be more token-efficient than full format"""
        full = search(files=[app_log], level="ERROR", output_format="full")
        summary = search(files=[app_log], level="ERROR", output_format="summary")
        # Summary should have less data than full results with all entries
        full_size = len(json.dumps(full))
        summary_size = len(json.dumps(summary))
        assert summary_size <= full_size, "Summary should not be larger than full output"


class TestC03CompareThreads:
    """[C03] compare_threads compares two request flows"""

    def test_compare_returns_comparison_dict(self, app_log):
        diff = compare_threads(
            files=[app_log], correlation_a="req-success-123", correlation_b="req-failed-456"
        )
        assert isinstance(diff, dict), "compare_threads must return dict"

    def test_compare_has_summary(self, app_log):
        diff = compare_threads(
            files=[app_log], correlation_a="req-success-123", correlation_b="req-failed-456"
        )
        assert "summary" in diff, "Comparison must have 'summary' key"


class TestC04CrossServiceTimeline:
    """[C04] cross_service_timeline shows request flow across services"""

    def test_cross_service_returns_timeline(self, multi_service_logs):
        timeline = cross_service_timeline(files=multi_service_logs, correlation_id="req-12345")
        assert isinstance(timeline, dict), "cross_service_timeline must return dict"

    def test_cross_service_has_entries_or_timeline(self, multi_service_logs):
        timeline = cross_service_timeline(files=multi_service_logs, correlation_id="req-12345")
        # Should have entries from multiple services
        has_entries = "entries" in timeline or "timeline" in timeline or "services" in timeline
        assert has_entries, "Timeline should have entries, timeline, or services key"


class TestC05InvestigationSession:
    """[C05] InvestigationSession tracks investigation progress"""

    def test_session_can_search(self, app_log):
        session = InvestigationSession(files=[app_log], name="incident_2024")
        result = session.search(level="ERROR")
        assert isinstance(result, dict), "session.search must return dict"

    def test_session_can_find_patterns(self, app_log):
        session = InvestigationSession(files=[app_log], name="incident_2024")
        result = session.find_patterns()
        assert isinstance(result, dict), "session.find_patterns must return dict"

    def test_session_can_add_note(self, app_log):
        session = InvestigationSession(files=[app_log], name="incident_2024")
        session.add_note("Database connection pool exhausted")
        # Should not raise

    def test_session_generates_report(self, app_log):
        session = InvestigationSession(files=[app_log], name="incident_2024")
        session.search(level="ERROR")
        session.find_patterns()
        session.add_note("Database connection pool exhausted")
        report = session.generate_report(format="markdown")
        assert isinstance(report, str), "generate_report must return string"
        assert len(report) > 0, "Report should not be empty"


class TestC06SmartSample:
    """[C06] smart_sample returns representative sample of logs"""

    def test_smart_sample_returns_dict(self, huge_log):
        sample = smart_sample(files=[huge_log], strategy="errors_focused", sample_size=50)
        assert isinstance(sample, dict), "smart_sample must return dict"

    def test_smart_sample_respects_size(self, huge_log):
        sample = smart_sample(files=[huge_log], strategy="errors_focused", sample_size=50)
        # Should have sample entries
        entries = sample.get("sample", sample.get("entries", []))
        assert len(entries) <= 50, "Sample should not exceed requested size"

    def test_smart_sample_diverse_strategy(self, huge_log):
        """Diverse strategy should work"""
        sample = smart_sample(files=[huge_log], strategy="diverse", sample_size=20)
        assert isinstance(sample, dict)

    def test_smart_sample_representative_strategy(self, huge_log):
        """Representative strategy should work"""
        sample = smart_sample(files=[huge_log], strategy="representative", sample_size=20)
        assert isinstance(sample, dict)

    def test_smart_sample_chronological_strategy(self, huge_log):
        """Chronological strategy should work"""
        sample = smart_sample(files=[huge_log], strategy="chronological", sample_size=20)
        assert isinstance(sample, dict)


class TestC07ErrorExplanation:
    """[C07] explain provides human-friendly error explanations"""

    def test_explain_returns_string(self):
        explanation = explain(error_message="Connection pool exhausted", context="production")
        assert isinstance(explanation, str), "explain must return string"

    def test_explain_not_empty(self):
        explanation = explain(error_message="Connection pool exhausted", context="production")
        assert len(explanation) > 0, "Explanation should not be empty"

    def test_explain_with_entry(self, app_log):
        """explain() can also take a full entry"""
        entry = {
            "timestamp": "2024-01-15T10:00:00Z",
            "level": "ERROR",
            "message": "Database timeout",
        }
        explanation = explain(entry=entry, context="production")
        assert isinstance(explanation, str)


class TestC08ThreadHierarchy:
    """[C08] follow_thread_hierarchy builds hierarchy tree"""

    def test_hierarchy_returns_dict(self, app_log):
        hierarchy = follow_thread_hierarchy(
            files=[app_log], root_identifier="req-123", min_confidence=0.8
        )
        assert isinstance(hierarchy, dict), "follow_thread_hierarchy must return dict"

    def test_hierarchy_bottleneck_access(self, app_log):
        """Bottleneck access should not raise even if no bottleneck found"""
        hierarchy = follow_thread_hierarchy(
            files=[app_log], root_identifier="req-123", min_confidence=0.8
        )
        # Access bottleneck safely (may be None or missing)
        bottleneck = hierarchy.get("bottleneck")
        # If bottleneck exists, it should have expected fields
        if bottleneck:
            assert "node_id" in bottleneck or "duration_ms" in bottleneck


class TestC09HierarchySummary:
    """[C09] get_hierarchy_summary returns tree overview"""

    def test_summary_returns_string(self, app_log):
        hierarchy = follow_thread_hierarchy(
            files=[app_log], root_identifier="req-123", min_confidence=0.5
        )
        summary = get_hierarchy_summary(hierarchy)
        assert isinstance(summary, str), "get_hierarchy_summary must return string"


@pytest.mark.skipif(not TREE_FORMATTER_AVAILABLE, reason="tree_formatter not available")
class TestC10TreeVisualization:
    """[C10] print_tree and print_waterfall visualize hierarchy"""

    def test_print_tree_works(self, app_log, capsys):
        hierarchy = follow_thread_hierarchy(
            files=[app_log], root_identifier="req-123", min_confidence=0.5
        )
        # Should not raise
        print_tree(hierarchy, mode="detailed", show_duration=True)
        captured = capsys.readouterr()
        # May produce output or be empty if no hierarchy found
        assert isinstance(captured.out, str)

    def test_print_waterfall_works(self, app_log, capsys):
        hierarchy = follow_thread_hierarchy(
            files=[app_log], root_identifier="req-123", min_confidence=0.5
        )
        # Should not raise
        print_waterfall(hierarchy, width=100)
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)
