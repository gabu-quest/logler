"""
Tests for marimo tour notebooks.

Ensures all tour notebooks execute without errors.
"""

import subprocess
import sys
from pathlib import Path

import pytest

TOURS_DIR = Path(__file__).parent.parent / "examples" / "tours"

# Tours that involve blocking operations (live watching) - skip these
SKIP_TOURS = {"tour_13_live_watching.py"}

EXPECTED_OUTPUT = {
    "tour_01_fundamentals.py": [
        "=== Log File Metadata ===",
        "=== Format Parsing ===",
        "Found",
    ],
    "tour_02_thread_tracking.py": [
        "=== Thread: payment-1 ===",
        "=== Request: req-001 (Successful Order) ===",
        "=== Request: req-002 (Failed Order) ===",
        "=== Comparison: req-001 vs req-002 ===",
    ],
    "tour_03_hierarchy.py": [
        "=== Hierarchy Built ===",
        "=== Compact Tree View ===",
        "=== Waterfall Timeline ===",
        "=== Bottleneck Detected ===",
        "=== Error Analysis ===",
    ],
    "tour_04_investigation.py": [
        "=== Investigation Session Created ===",
        "=== Investigation History ===",
        "=== Investigation Report (truncated) ===",
        "=== SQL: Counts by Level ===",
    ],
    "tour_05_patterns.py": [
        "=== Patterns Found ===",
        "=== Top 3 Most Frequent Issues ===",
        "=== Issues by Component ===",
        "=== Pattern Severity Assessment ===",
    ],
    "tour_06_flamegraph.py": [
        "=== Hierarchy Stats ===",
        "FLAMEGRAPH VISUALIZATION",
        "=== Waterfall View (Timing) ===",
        "=== Flamegraph Interpretation ===",
    ],
    "tour_07_error_flow.py": [
        "=== Hierarchy Overview ===",
        "=== Error Flow Analysis ===",
        "=== ROOT CAUSES ===",
        "=== PROPAGATION CHAINS ===",
        "=== IMPACT SUMMARY ===",
    ],
    "tour_08_comparison.py": [
        "=== Hierarchy Comparison ===",
        "=== DEGRADED NODES",
        "=== Thread Comparison ===",
        "=== Time Period Comparison ===",
        "=== Cross-Service Timeline ===",
    ],
    "tour_09_tracing_exports.py": [
        "=== Jaeger Export ===",
        "=== Jaeger Spans ===",
        "=== Zipkin Export ===",
        "=== Zipkin Spans ===",
    ],
    "tour_10_sampling.py": [
        "=== Representative Sampling ===",
        "=== Diverse Sampling ===",
        "=== Chronological Sampling ===",
        "=== Errors-Focused Sampling ===",
        "=== Strategy Comparison ===",
    ],
    "tour_11_ai_insights.py": [
        "=== Automatic Analysis ===",
        "=== INSIGHTS ===",
        "=== Error Explanation ===",
        "=== Suggested Next Actions ===",
        "INVESTIGATION WORKFLOW",
    ],
    "tour_12_multi_file_interleaving.py": [
        "Created 5 log files:",
        "CROSS-SERVICE TIMELINE",
        "REQUEST WATERFALL",
        "DISTRIBUTED HIERARCHY",
        "ERROR FLOW ANALYSIS",
    ],
    "tour_14_performance.py": [
        "SEARCH BENCHMARKS",
        "OUTPUT FORMAT COMPARISON",
        "PERFORMANCE SUMMARY",
    ],
}

FORBIDDEN_OUTPUT = {
    "tour_03_hierarchy.py": ["No timing information available"],
    "tour_06_flamegraph.py": ["No timing information available", "No hierarchy data"],
}


def get_tour_files():
    """Get all tour notebook files."""
    return sorted(TOURS_DIR.glob("tour_*.py"))


@pytest.fixture(scope="module")
def tour_files():
    """Fixture providing list of tour files."""
    return get_tour_files()


class TestTourNotebooks:
    """Test that all tour notebooks execute without errors."""

    @pytest.mark.parametrize(
        "tour_file",
        [f for f in get_tour_files() if f.name not in SKIP_TOURS],
        ids=lambda f: f.name,
    )
    def test_tour_executes(self, tour_file):
        """Each tour notebook should execute without errors."""
        result = subprocess.run(
            [sys.executable, str(tour_file)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"Tour {tour_file.name} failed with:\n"
            f"STDOUT:\n{result.stdout[-2000:] if result.stdout else '(empty)'}\n"
            f"STDERR:\n{result.stderr[-2000:] if result.stderr else '(empty)'}"
        )
        stdout = result.stdout or ""
        assert stdout.strip(), f"Tour {tour_file.name} produced no stdout"

        required_tokens = EXPECTED_OUTPUT.get(tour_file.name, [])
        for token in required_tokens:
            assert token in stdout, f"Tour {tour_file.name} missing output: {token!r}"

        forbidden_tokens = FORBIDDEN_OUTPUT.get(tour_file.name, [])
        for token in forbidden_tokens:
            assert token not in stdout, f"Tour {tour_file.name} had bad output: {token!r}"

    def test_all_tours_exist(self, tour_files):
        """Verify expected tours exist."""
        tour_names = {f.name for f in tour_files}
        # Check a few key tours exist
        assert "tour_01_fundamentals.py" in tour_names
        assert "tour_02_thread_tracking.py" in tour_names
        assert "tour_03_hierarchy.py" in tour_names

    def test_no_invalid_timedelta_args(self, tour_files):
        """Ensure no tours use invalid timedelta(ms=...) syntax."""
        for tour_file in tour_files:
            content = tour_file.read_text()
            # Check for the invalid ms= argument
            assert "timedelta(ms=" not in content, (
                f"{tour_file.name} uses invalid timedelta(ms=...) - "
                "should be timedelta(milliseconds=...)"
            )
            assert "_td(ms=" not in content, (
                f"{tour_file.name} uses invalid _td(ms=...) - " "should be _td(milliseconds=...)"
            )
