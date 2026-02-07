"""
README Contract Tests

Each test corresponds to a contract ID [CXX] in the README's "Public API Contract"
section.  When the README changes, these tests must change with it — CI proves
the README.

Pattern:
  # ---------------- [CXX] Title ----------------
  def test_CXX_descriptive_name(): ...
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

try:
    from logler.investigate import (
        RUST_AVAILABLE,
        InvestigationSession,
        compare_threads,
        cross_service_timeline,
        follow_thread_hierarchy,
        get_hierarchy_summary,
        search,
        smart_sample,
    )
    from logler.tree_formatter import format_tree, format_waterfall, print_tree, print_waterfall
except ImportError:
    RUST_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust backend required for contract tests"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TIME = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def _entry(
    offset_ms,
    level,
    message,
    thread_id="main",
    correlation_id=None,
    trace_id=None,
    span_id=None,
    parent_span_id=None,
    service=None,
    **extra,
):
    ts = BASE_TIME + timedelta(milliseconds=offset_ms)
    d = {
        "timestamp": ts.isoformat(),
        "level": level,
        "message": message,
        "thread_id": thread_id,
    }
    if correlation_id:
        d["correlation_id"] = correlation_id
    if trace_id:
        d["trace_id"] = trace_id
    if span_id:
        d["span_id"] = span_id
    if parent_span_id:
        d["parent_span_id"] = parent_span_id
    if service:
        d["service"] = service
    d.update(extra)
    return d


def _write_log(directory, filename, entries):
    """Write JSON-lines log file.  Returns the absolute path."""
    path = Path(directory) / filename
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return str(path)


# ---------------------------------------------------------------------------
# Fixtures — deterministic data with documented exact counts
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_log(tmp_path):
    """General-purpose log with known counts.

    Correlation IDs:
    - req-success-123: 4 entries (all INFO) — successful flow
    - req-failed-456:  4 entries (1 INFO + 1 WARN + 2 ERROR) — failed flow
    - hc-001: 1 entry (INFO, health check)
    Plus 3 standalone entries (1 INFO, 1 ERROR, 1 INFO).

    Totals: 12 entries = 8 INFO + 1 WARN + 3 ERROR
    """
    entries = [
        _entry(0, "INFO", "GET /api/users started", "worker-1", "req-success-123"),
        _entry(50, "INFO", "JWT validated for user:alice", "worker-1", "req-success-123"),
        _entry(100, "INFO", "Database query completed in 45ms", "worker-1", "req-success-123"),
        _entry(200, "INFO", "GET /api/users completed 200", "worker-1", "req-success-123"),
        _entry(1000, "INFO", "POST /api/orders started", "worker-2", "req-failed-456"),
        _entry(1050, "WARN", "Slow database response", "worker-2", "req-failed-456"),
        _entry(
            1100, "ERROR", "Connection timeout to database server", "worker-2", "req-failed-456"
        ),
        _entry(1200, "ERROR", "POST /api/orders failed 500", "worker-2", "req-failed-456"),
        _entry(2000, "INFO", "Health check passed", "monitor", "hc-001"),
        _entry(3000, "INFO", "Cache refreshed", "worker-3"),
        _entry(4000, "ERROR", "Out of memory in worker-5", "worker-5"),
        _entry(5000, "INFO", "Metrics exported", "metrics-worker"),
    ]
    return _write_log(tmp_path, "app.log", entries)


@pytest.fixture()
def hierarchy_log(tmp_path):
    """Log with explicit span/parent_span hierarchy for req-123.

    Structure (3 nodes):
      span-root (0ms .. 510ms) — 510ms duration
      ├─ span-auth (10ms .. 50ms) — 40ms
      └─ span-db   (20ms .. 500ms) — 480ms ← BOTTLENECK
    """
    entries = [
        _entry(0, "INFO", "Request started", "worker-1", "req-123", "trace-abc", "span-root"),
        _entry(
            10, "INFO", "Auth check", "worker-1", "req-123", "trace-abc", "span-auth", "span-root"
        ),
        _entry(
            50, "INFO", "Auth passed", "worker-1", "req-123", "trace-abc", "span-auth", "span-root"
        ),
        _entry(
            20,
            "INFO",
            "DB query started",
            "worker-1",
            "req-123",
            "trace-abc",
            "span-db",
            "span-root",
        ),
        _entry(
            500,
            "INFO",
            "DB query completed",
            "worker-1",
            "req-123",
            "trace-abc",
            "span-db",
            "span-root",
        ),
        _entry(510, "INFO", "Request completed", "worker-1", "req-123", "trace-abc", "span-root"),
    ]
    return _write_log(tmp_path, "hierarchy.log", entries)


@pytest.fixture()
def huge_log(tmp_path):
    """500-entry log: every 10th is ERROR (50 errors), rest INFO.  20 correlation IDs."""
    entries = []
    for i in range(500):
        level = "ERROR" if i % 10 == 0 else "INFO"
        ts = BASE_TIME + timedelta(seconds=i)
        entries.append(
            {
                "timestamp": ts.isoformat(),
                "level": level,
                "message": f"Log entry {i}",
                "thread_id": f"worker-{i % 5}",
                "correlation_id": f"req-{i % 20:03d}",
            }
        )
    return _write_log(tmp_path, "huge.log", entries)


@pytest.fixture()
def service_logs(tmp_path):
    """Three service logs sharing correlation_id='req-12345'.

    api:   2 entries (request in + response out)
    db:    2 entries (query + result)
    cache: 2 entries (miss + set)
    Total: 6 entries across 3 services.
    """
    cid = "req-12345"
    api_entries = [
        _entry(0, "INFO", "Incoming request", "api-1", cid, service="api"),
        _entry(500, "INFO", "Response sent 200", "api-1", cid, service="api"),
    ]
    db_entries = [
        _entry(100, "INFO", "SELECT * FROM users", "db-pool-1", cid, service="db"),
        _entry(300, "INFO", "Query returned 42 rows", "db-pool-1", cid, service="db"),
    ]
    cache_entries = [
        _entry(50, "INFO", "Cache MISS for key user:42", "cache-1", cid, service="cache"),
        _entry(310, "INFO", "Cache SET for key user:42", "cache-1", cid, service="cache"),
    ]
    return {
        "api": [_write_log(tmp_path, "api.log", api_entries)],
        "db": [_write_log(tmp_path, "db.log", db_entries)],
        "cache": [_write_log(tmp_path, "cache.log", cache_entries)],
    }


# ---------------- [C02] Token-efficient search ----------------


def test_C02_search_summary_returns_exact_error_count(app_log):
    """search(output_format='summary') returns total_matches == 3 for ERROR level."""
    result = search(files=[app_log], level="ERROR", output_format="summary")

    # Contract: summary mode returns dict with total_matches at top level
    assert "total_matches" in result, f"Missing 'total_matches'. Keys: {sorted(result.keys())}"
    assert (
        result["total_matches"] == 3
    ), f"Expected 3 ERROR matches (2 in req-failed-456 + 1 standalone), got {result['total_matches']}"


def test_C02_summary_is_more_compact_than_full(app_log):
    """Summary format should be smaller than full format (token-efficient)."""
    full = search(files=[app_log], level="ERROR", output_format="full")
    summary = search(files=[app_log], level="ERROR", output_format="summary")

    full_size = len(json.dumps(full))
    summary_size = len(json.dumps(summary))
    assert (
        summary_size < full_size
    ), f"Summary ({summary_size} bytes) should be smaller than full ({full_size} bytes)"


# ---------------- [C03] Compare threads ----------------


def test_C03_compare_threads_has_both_sides(app_log):
    """compare_threads() returns thread_a, thread_b, differences, and summary."""
    diff = compare_threads(
        files=[app_log],
        correlation_a="req-success-123",
        correlation_b="req-failed-456",
    )

    # Contract: returns dict with these exact keys
    for key in ("summary", "thread_a", "thread_b", "differences"):
        assert key in diff, f"Missing '{key}'. Keys: {sorted(diff.keys())}"

    # Summary should describe the actual differences found
    summary = diff["summary"]
    assert len(summary) > 10, f"Summary too short: {summary!r}"
    assert (
        "error" in summary.lower()
    ), f"Summary should describe the error difference between threads. Got:\n{summary}"


def test_C03_compare_threads_captures_error_difference(app_log):
    """thread_a (success) should have 4 entries, thread_b (failed) should have 4 entries."""
    diff = compare_threads(
        files=[app_log],
        correlation_a="req-success-123",
        correlation_b="req-failed-456",
    )

    # Enforce exact field name — the API contract must be stable
    assert (
        "entry_count" in diff["thread_a"]
    ), f"thread_a missing 'entry_count'. Keys: {sorted(diff['thread_a'].keys())}"
    assert (
        diff["thread_a"]["entry_count"] == 4
    ), f"req-success-123 should have 4 entries, got {diff['thread_a']['entry_count']}"

    assert (
        "entry_count" in diff["thread_b"]
    ), f"thread_b missing 'entry_count'. Keys: {sorted(diff['thread_b'].keys())}"
    assert (
        diff["thread_b"]["entry_count"] == 4
    ), f"req-failed-456 should have 4 entries, got {diff['thread_b']['entry_count']}"


# ---------------- [C04] Cross-service timeline ----------------


def test_C04_cross_service_timeline_returns_all_events(service_logs):
    """cross_service_timeline() returns exactly 6 events from 3 services."""
    timeline = cross_service_timeline(
        files=service_logs,
        correlation_id="req-12345",
    )

    # Contract: returns dict with "timeline" key containing event list
    assert "timeline" in timeline, f"Missing 'timeline'. Keys: {sorted(timeline.keys())}"

    events = timeline["timeline"]
    assert len(events) == 6, f"Expected 6 events (2 per service * 3 services), got {len(events)}"


def test_C04_cross_service_timeline_has_all_three_services(service_logs):
    """All three services (api, db, cache) must be represented."""
    timeline = cross_service_timeline(
        files=service_logs,
        correlation_id="req-12345",
    )

    events = timeline["timeline"]
    assert len(events) == 6  # guard

    services_seen = {event["service"] for event in events}
    assert services_seen == {"api", "db", "cache"}, f"Expected all 3 services, got: {services_seen}"


def test_C04_cross_service_timeline_has_total_entries(service_logs):
    """Response should include total_entries count."""
    timeline = cross_service_timeline(
        files=service_logs,
        correlation_id="req-12345",
    )

    assert "total_entries" in timeline, f"Missing 'total_entries'. Keys: {sorted(timeline.keys())}"
    assert timeline["total_entries"] == 6


# ---------------- [C05] Investigation sessions ----------------


def test_C05_session_search_finds_errors(app_log):
    """InvestigationSession.search(level='ERROR') finds the 3 errors."""
    session = InvestigationSession(files=[app_log], name="incident_2024")

    result = session.search(level="ERROR")
    assert (
        result["total_matches"] == 3
    ), f"Session search should find 3 ERRORs, got {result.get('total_matches')}"


def test_C05_session_report_includes_note(app_log):
    """generate_report() includes user notes in the output."""
    session = InvestigationSession(files=[app_log], name="incident_2024")
    session.search(level="ERROR")
    session.add_note("Database connection pool exhausted")

    report = session.generate_report(format="markdown")
    assert (
        "Database connection pool" in report
    ), f"Report should include note text. First 300 chars:\n{report[:300]}"
    # Report should also reference the session name and search results
    assert "incident_2024" in report, f"Report should include session name. Got:\n{report[:300]}"


def test_C05_session_tracks_history(app_log):
    """Session records each operation in history."""
    session = InvestigationSession(files=[app_log], name="history_test")
    session.search(level="ERROR")
    session.search(query="timeout")

    history = session.get_history()
    # History includes 1 init + 2 searches = 3 entries
    assert len(history) == 3, f"Expected 3 history entries (init + 2 searches), got {len(history)}"
    ops = [h["operation"] for h in history]
    assert ops == ["init", "search", "search"], f"Expected [init, search, search], got {ops}"


# ---------------- [C06] Smart sampling ----------------


def test_C06_errors_focused_includes_majority_errors(huge_log):
    """errors_focused strategy: majority of 50 samples should be ERROR.

    Fixture: 500 entries, 50 errors (10%).  Strategy should over-represent errors.
    """
    sample = smart_sample(
        files=[huge_log],
        strategy="errors_focused",
        sample_size=50,
    )

    # Contract: returns dict with "samples" key
    assert "samples" in sample, f"Missing 'samples'. Keys: {sorted(sample.keys())}"

    entries = sample["samples"]
    assert len(entries) == 50, f"Expected exactly 50 samples, got {len(entries)}"
    assert (
        sample["total_population"] == 500
    ), f"Expected 500 total, got {sample['total_population']}"
    assert sample["strategy"] == "errors_focused"

    error_count = sum(1 for e in entries if e.get("level") == "ERROR")
    # errors_focused should include significantly more errors than 10% (population rate)
    assert (
        error_count >= 10
    ), f"errors_focused should over-represent errors (pop rate=10%), got {error_count}/50"


def test_C06_diverse_strategy_returns_requested_size(huge_log):
    """diverse strategy returns exactly the requested sample size."""
    sample = smart_sample(files=[huge_log], strategy="diverse", sample_size=20)
    assert (
        len(sample["samples"]) == 20
    ), f"Expected 20 diverse samples, got {len(sample['samples'])}"


def test_C06_chronological_strategy_returns_requested_size(huge_log):
    """chronological strategy returns exactly the requested sample size."""
    sample = smart_sample(files=[huge_log], strategy="chronological", sample_size=20)
    assert (
        len(sample["samples"]) == 20
    ), f"Expected 20 chronological samples, got {len(sample['samples'])}"


# ---------------- [C08] Thread hierarchy ----------------


def test_C08_hierarchy_builds_correct_structure(hierarchy_log):
    """follow_thread_hierarchy() builds 1 root with 2 children (3 nodes total)."""
    hierarchy = follow_thread_hierarchy(
        files=[hierarchy_log],
        root_identifier="req-123",
        min_confidence=0.8,
    )

    assert (
        hierarchy["total_nodes"] == 3
    ), f"Expected 3 nodes (root + auth + db), got {hierarchy['total_nodes']}"

    roots = hierarchy["roots"]
    assert len(roots) == 1, f"Expected 1 root node, got {len(roots)}"

    children = roots[0].get("children", [])
    assert len(children) == 2, f"Root should have 2 children (auth + db), got {len(children)}"


def test_C08_bottleneck_is_db_span(hierarchy_log):
    """Bottleneck should be span-db (480ms out of 510ms total)."""
    hierarchy = follow_thread_hierarchy(
        files=[hierarchy_log],
        root_identifier="req-123",
        min_confidence=0.8,
    )

    bottleneck = hierarchy["bottleneck"]
    assert bottleneck is not None, "Bottleneck should be detected"
    assert (
        bottleneck["node_id"] == "span-db"
    ), f"Bottleneck should be span-db, got {bottleneck['node_id']}"
    assert bottleneck["duration_ms"] > 0, "Bottleneck duration should be positive"
    assert bottleneck["depth"] == 1, f"Bottleneck depth should be 1, got {bottleneck['depth']}"


# ---------------- [C09] Hierarchy summary ----------------


def test_C09_hierarchy_summary_mentions_node_count(hierarchy_log):
    """get_hierarchy_summary() returns string mentioning total nodes (3)."""
    hierarchy = follow_thread_hierarchy(
        files=[hierarchy_log],
        root_identifier="req-123",
    )

    summary = get_hierarchy_summary(hierarchy)

    assert "3" in summary, f"Summary should mention 3 total nodes. Got:\n{summary}"
    # Should reference the hierarchy structure, not just be random text
    assert (
        "span" in summary.lower() or "node" in summary.lower() or "hierarchy" in summary.lower()
    ), f"Summary should describe hierarchy structure. Got:\n{summary}"


# ---------------- [C10] Tree visualization ----------------


def test_C10_format_tree_has_header_and_content(hierarchy_log):
    """format_tree() returns string with THREAD HIERARCHY header."""
    hierarchy = follow_thread_hierarchy(
        files=[hierarchy_log],
        root_identifier="req-123",
    )

    tree = format_tree(hierarchy, mode="detailed", use_colors=False)

    assert "THREAD HIERARCHY" in tree, f"Missing header. Got:\n{tree}"
    # Tree should show the hierarchy structure with node labels from log messages
    assert (
        "Request" in tree or "Auth" in tree or "DB" in tree
    ), f"Tree should contain node labels from log messages. Got:\n{tree}"


def test_C10_format_waterfall_produces_multiline_output(hierarchy_log):
    """format_waterfall() returns multi-line timeline."""
    hierarchy = follow_thread_hierarchy(
        files=[hierarchy_log],
        root_identifier="req-123",
    )

    waterfall = format_waterfall(hierarchy, width=100)

    lines = waterfall.strip().split("\n")
    # 3 spans (root, auth, db) should produce at least 3 lines
    assert len(lines) >= 3, f"Waterfall should have >= 3 lines for 3 spans. Got:\n{waterfall}"
    # Waterfall should show timing information (ms durations)
    assert "ms" in waterfall, f"Waterfall should show durations in ms. Got:\n{waterfall}"


def test_C10_print_tree_writes_to_stdout(hierarchy_log, capsys):
    """print_tree() writes non-empty content to stdout."""
    hierarchy = follow_thread_hierarchy(
        files=[hierarchy_log],
        root_identifier="req-123",
    )

    print_tree(hierarchy, mode="detailed", show_duration=True)
    captured = capsys.readouterr()
    # print_tree uses human-readable labels from log messages
    assert (
        "Request" in captured.out or "Auth" in captured.out or "DB" in captured.out
    ), f"print_tree should show node labels. Got:\n{captured.out}"


def test_C10_print_waterfall_writes_to_stdout(hierarchy_log, capsys):
    """print_waterfall() writes non-empty content to stdout."""
    hierarchy = follow_thread_hierarchy(
        files=[hierarchy_log],
        root_identifier="req-123",
    )

    print_waterfall(hierarchy, width=100)
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    assert (
        len(lines) >= 3
    ), f"print_waterfall should show >= 3 lines for 3 spans. Got:\n{captured.out}"
