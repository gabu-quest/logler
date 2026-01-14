import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
    # Logler Tour: Comparison & Diffing

    When debugging, comparing things is essential:
    - Before vs after deployment
    - Successful vs failed requests
    - Different time periods

    **What you'll learn:**
    1. Comparing hierarchies (performance diff)
    2. Comparing threads/requests
    3. Comparing time periods
    4. Cross-service timeline analysis
    5. Interpreting comparison results

    Let's dive in!
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Setting Up - Two Versions

    We'll create "before" and "after" logs to simulate
    a deployment that introduced a performance regression.
    """
    )
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    # BEFORE deployment - fast version
    before_logs = []

    before_logs.append(
        {
            "timestamp": (base_time + timedelta(ms=0)).isoformat(),
            "level": "INFO",
            "message": "HTTP GET /api/users",
            "trace_id": "trace-before",
            "span_id": "span-root",
            "parent_span_id": None,
            "service": "api",
            "duration_ms": 200,
        }
    )

    before_logs.append(
        {
            "timestamp": (base_time + timedelta(ms=10)).isoformat(),
            "level": "INFO",
            "message": "Database query",
            "trace_id": "trace-before",
            "span_id": "span-db",
            "parent_span_id": "span-root",
            "service": "postgres",
            "duration_ms": 50,
        }
    )

    before_logs.append(
        {
            "timestamp": (base_time + timedelta(ms=70)).isoformat(),
            "level": "INFO",
            "message": "Cache lookup",
            "trace_id": "trace-before",
            "span_id": "span-cache",
            "parent_span_id": "span-root",
            "service": "redis",
            "duration_ms": 10,
        }
    )

    before_logs.append(
        {
            "timestamp": (base_time + timedelta(ms=90)).isoformat(),
            "level": "INFO",
            "message": "Response formatting",
            "trace_id": "trace-before",
            "span_id": "span-format",
            "parent_span_id": "span-root",
            "service": "api",
            "duration_ms": 20,
        }
    )

    # AFTER deployment - slow version (regression!)
    after_logs = []

    after_logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=60, ms=0)).isoformat(),
            "level": "INFO",
            "message": "HTTP GET /api/users",
            "trace_id": "trace-after",
            "span_id": "span-root",
            "parent_span_id": None,
            "service": "api",
            "duration_ms": 800,  # 4x slower!
        }
    )

    after_logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=60, ms=10)).isoformat(),
            "level": "INFO",
            "message": "Database query",
            "trace_id": "trace-after",
            "span_id": "span-db",
            "parent_span_id": "span-root",
            "service": "postgres",
            "duration_ms": 400,  # 8x slower! (regression here)
        }
    )

    after_logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=60, ms=420)).isoformat(),
            "level": "WARN",
            "message": "Cache miss",
            "trace_id": "trace-after",
            "span_id": "span-cache",
            "parent_span_id": "span-root",
            "service": "redis",
            "duration_ms": 15,
        }
    )

    after_logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=60, ms=450)).isoformat(),
            "level": "INFO",
            "message": "Response formatting",
            "trace_id": "trace-after",
            "span_id": "span-format",
            "parent_span_id": "span-root",
            "service": "api",
            "duration_ms": 25,
        }
    )

    # New span added after deployment
    after_logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=60, ms=480)).isoformat(),
            "level": "INFO",
            "message": "Audit logging",
            "trace_id": "trace-after",
            "span_id": "span-audit",
            "parent_span_id": "span-root",
            "service": "audit-service",
            "duration_ms": 100,
        }
    )

    # Write files
    temp_dir = tempfile.mkdtemp()
    before_file = Path(temp_dir) / "before.log"
    after_file = Path(temp_dir) / "after.log"

    with open(before_file, "w") as _f:
        for _log in before_logs:
            _f.write(json.dumps(_log) + "\n")

    with open(after_file, "w") as _f:
        for _log in after_logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created before.log: {len(before_logs)} entries, 200ms total")
    print(f"Created after.log: {len(after_logs)} entries, 800ms total")
    print("\nRegression: Database query went from 50ms to 400ms!")
    return Path, after_file, after_logs, base_time, before_file, before_logs, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Comparing Hierarchies

    The `diff_hierarchies()` function compares two traces
    to identify performance changes.
    """
    )
    return


@app.cell
def _():
    from logler.investigate import (
        follow_thread_hierarchy,
        diff_hierarchies,
        format_hierarchy_diff,
        compare_threads,
        compare_time_periods,
        cross_service_timeline,
    )

    return (
        compare_threads,
        compare_time_periods,
        cross_service_timeline,
        diff_hierarchies,
        follow_thread_hierarchy,
        format_hierarchy_diff,
    )


@app.cell
def _(after_file, before_file, follow_thread_hierarchy):
    # Build both hierarchies
    hierarchy_before = follow_thread_hierarchy(
        files=[str(before_file)], root_identifier="trace-before"
    )

    hierarchy_after = follow_thread_hierarchy(
        files=[str(after_file)], root_identifier="trace-after"
    )

    print(
        f"Before: {hierarchy_before.get('total_duration_ms', 0)}ms, {hierarchy_before['total_nodes']} nodes"
    )
    print(
        f"After: {hierarchy_after.get('total_duration_ms', 0)}ms, {hierarchy_after['total_nodes']} nodes"
    )
    return hierarchy_after, hierarchy_before


@app.cell
def _(diff_hierarchies, hierarchy_after, hierarchy_before):
    # Compare the hierarchies
    diff = diff_hierarchies(
        hierarchy_before, hierarchy_after, label_a="Before Deploy", label_b="After Deploy"
    )

    print("=== Hierarchy Comparison ===\n")
    _summary = diff["summary"]
    print(
        f"Duration change: {_summary['total_duration_change_ms']:+.0f}ms ({_summary['total_duration_change_pct']:+.1f}%)"
    )
    print(f"Node count change: {_summary['node_count_change']:+d}")
    print(f"New errors: {_summary['new_errors']}")
    print(f"Resolved errors: {_summary['resolved_errors']}")
    return (diff,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Identifying Regressions

    The diff shows which nodes got slower (degraded) or faster (improved).
    """
    )
    return


@app.cell
def _(diff):
    print("=== DEGRADED NODES (Got Slower) ===\n")
    for _node in diff["degraded_nodes"]:
        print(f"❌ {_node['id']}")
        print(f"   Before: {_node['before_ms']:.0f}ms")
        print(f"   After: {_node['after_ms']:.0f}ms")
        print(f"   Change: {_node['change_ms']:+.0f}ms ({_node['change_pct']:+.1f}%)")
        print()

    print("=== IMPROVED NODES (Got Faster) ===\n")
    if diff["improved_nodes"]:
        for _node in diff["improved_nodes"]:
            print(f"✅ {_node['id']}: {_node['change_ms']:+.0f}ms")
    else:
        print("(none)")

    print("\n=== NEW NODES ===\n")
    for _node in diff["new_nodes"]:
        print(f"➕ {_node['id']}: {_node['duration_ms']:.0f}ms")

    print("\n=== REMOVED NODES ===\n")
    if diff["removed_nodes"]:
        for _node in diff["removed_nodes"]:
            print(f"➖ {_node['id']}")
    else:
        print("(none)")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Formatted Diff Report

    Use `format_hierarchy_diff()` for a complete formatted report.
    """
    )
    return


@app.cell
def _(diff, format_hierarchy_diff):
    diff_report = format_hierarchy_diff(diff)
    print(diff_report)
    return (diff_report,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. Comparing Threads/Requests

    Compare two specific requests to find what's different.
    Perfect for "why did this request fail but that one succeed?"
    """
    )
    return


@app.cell
def _():
    import json as _json
    import tempfile as _tempfile
    from pathlib import Path as _Path
    from datetime import datetime as _datetime, timezone as _tz, timedelta as _td

    # Create logs with successful and failed requests
    _base = _datetime(2024, 1, 15, 10, 0, 0, tzinfo=_tz.utc)
    _compare_logs = []

    # Successful request (req-success)
    _compare_logs.extend(
        [
            {
                "timestamp": (_base + _td(ms=0)).isoformat(),
                "level": "INFO",
                "message": "Request started",
                "correlation_id": "req-success",
            },
            {
                "timestamp": (_base + _td(ms=10)).isoformat(),
                "level": "INFO",
                "message": "Cache hit",
                "correlation_id": "req-success",
            },
            {
                "timestamp": (_base + _td(ms=20)).isoformat(),
                "level": "INFO",
                "message": "Response sent",
                "correlation_id": "req-success",
            },
        ]
    )

    # Failed request (req-failed)
    _compare_logs.extend(
        [
            {
                "timestamp": (_base + _td(ms=100)).isoformat(),
                "level": "INFO",
                "message": "Request started",
                "correlation_id": "req-failed",
            },
            {
                "timestamp": (_base + _td(ms=110)).isoformat(),
                "level": "WARN",
                "message": "Cache miss",
                "correlation_id": "req-failed",
            },
            {
                "timestamp": (_base + _td(ms=120)).isoformat(),
                "level": "INFO",
                "message": "Database query",
                "correlation_id": "req-failed",
            },
            {
                "timestamp": (_base + _td(ms=500)).isoformat(),
                "level": "ERROR",
                "message": "Database timeout",
                "correlation_id": "req-failed",
            },
            {
                "timestamp": (_base + _td(ms=510)).isoformat(),
                "level": "ERROR",
                "message": "Request failed",
                "correlation_id": "req-failed",
            },
        ]
    )

    _compare_dir = _tempfile.mkdtemp()
    compare_file = _Path(_compare_dir) / "compare.log"
    with open(compare_file, "w") as _f:
        for _log in _compare_logs:
            _f.write(_json.dumps(_log) + "\n")

    print("Created compare.log with successful and failed requests")
    return (compare_file,)


@app.cell
def _(compare_file, compare_threads):
    # Compare successful vs failed request
    thread_comparison = compare_threads(
        files=[str(compare_file)], correlation_a="req-success", correlation_b="req-failed"
    )

    print("=== Thread Comparison ===\n")
    print(thread_comparison["summary"])
    return (thread_comparison,)


@app.cell
def _(thread_comparison):
    print("=== Differences ===\n")
    _diffs = thread_comparison["differences"]

    print(f"Duration difference: {_diffs['duration_diff_ms']:+.0f}ms")
    print(f"Error difference: {_diffs['error_diff']:+d}")

    print("\nOnly in successful request:")
    for _msg in _diffs.get("only_in_a", [])[:3]:
        print(f"  • {_msg}")

    print("\nOnly in failed request:")
    for _msg in _diffs.get("only_in_b", [])[:3]:
        print(f"  • {_msg}")

    if _diffs.get("level_changes"):
        print(f"\nLevel changes: {_diffs['level_changes']}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 6. Comparing Time Periods

    Compare logs from different time periods to find what changed.
    Great for "what happened after the deployment at 3pm?"
    """
    )
    return


@app.cell
def _():
    import json as _json2
    import tempfile as _tempfile2
    from pathlib import Path as _Path2
    from datetime import datetime as _dt2, timezone as _tz2, timedelta as _td2

    _base2 = _dt2(2024, 1, 15, 14, 0, 0, tzinfo=_tz2.utc)
    _period_logs = []

    # Period A: Before deployment (14:00-15:00) - healthy
    for _i in range(20):
        _period_logs.append(
            {
                "timestamp": (_base2 + _td2(minutes=_i * 3)).isoformat(),
                "level": "INFO",
                "message": "Request processed successfully",
                "thread_id": f"worker-{_i % 3}",
            }
        )

    # Period B: After deployment (15:00-16:00) - problems
    for _i in range(30):
        _level = "ERROR" if _i % 5 == 0 else "INFO"
        _msg = "Database connection failed" if _level == "ERROR" else "Request processed"
        _period_logs.append(
            {
                "timestamp": (_base2 + _td2(hours=1, minutes=_i * 2)).isoformat(),
                "level": _level,
                "message": _msg,
                "thread_id": f"worker-{_i % 5}",
            }
        )

    _period_dir = _tempfile2.mkdtemp()
    period_file = _Path2(_period_dir) / "periods.log"
    with open(period_file, "w") as _f:
        for _log in _period_logs:
            _f.write(_json2.dumps(_log) + "\n")

    print("Created periods.log spanning 14:00-16:00")
    return (period_file,)


@app.cell
def _(compare_time_periods, period_file):
    # Compare before and after deployment
    period_comparison = compare_time_periods(
        files=[str(period_file)],
        period_a_start="2024-01-15T14:00:00Z",
        period_a_end="2024-01-15T15:00:00Z",
        period_b_start="2024-01-15T15:00:00Z",
        period_b_end="2024-01-15T16:00:00Z",
    )

    print("=== Time Period Comparison ===\n")
    print(period_comparison.get("summary", "No summary available"))
    return (period_comparison,)


@app.cell
def _(period_comparison):
    print("=== Period Details ===\n")

    _pa = period_comparison.get("period_a", {})
    _pb = period_comparison.get("period_b", {})

    print("Period A (before):")
    print(f"  Total logs: {_pa.get('total_logs', 0)}")
    print(f"  Error rate: {_pa.get('error_rate', 0):.1%}")

    print("\nPeriod B (after):")
    print(f"  Total logs: {_pb.get('total_logs', 0)}")
    print(f"  Error rate: {_pb.get('error_rate', 0):.1%}")

    _changes = period_comparison.get("changes", {})
    if _changes:
        print("\nChanges:")
        print(f"  Volume change: {_changes.get('log_volume_change_pct', 0):+.0f}%")
        if _changes.get("new_errors"):
            print(f"  New errors: {_changes['new_errors']}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've learned how to compare logs:

    - **`diff_hierarchies()`** - Compare two traces for performance changes
    - **`format_hierarchy_diff()`** - Format the comparison
    - **`compare_threads()`** - Compare two requests/threads
    - **`compare_time_periods()`** - Before/after time analysis
    - **`cross_service_timeline()`** - Unified multi-service view

    **Key Insights:**
    - Hierarchy diff finds performance regressions
    - Thread comparison reveals why one request failed
    - Time period comparison finds deployment impacts

    **Next Steps:**
    - **Tour 09**: Distributed tracing exports
    - **Tour 10**: Smart sampling strategies
    """
    )
    return


@app.cell
def _(temp_dir):
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return (shutil,)


if __name__ == "__main__":
    app.run()
