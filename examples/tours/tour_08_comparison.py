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

    base_steps = [
        ("span-root", None, "api", "HTTP GET /api/users", 0, 220),
        ("span-db", "span-root", "postgres", "Database query", 12, 60),
        ("span-cache", "span-root", "redis", "Cache lookup", 80, 15),
        ("span-format", "span-root", "api", "Response formatting", 110, 25),
    ]

    def _emit_trace(trace_id, base_offset_ms, duration_overrides, cache_warning=False):
        trace_logs = []
        for span_id, parent, service, message, offset_ms, base_duration in base_steps:
            duration = duration_overrides.get(span_id, base_duration)
            is_cache = span_id == "span-cache"
            level = "WARN" if cache_warning and is_cache else "INFO"
            start_message = message if level == "INFO" else "Cache miss"
            end_message = (
                f"{start_message} completed ({duration}ms)"
                if level == "INFO"
                else f"{start_message} resolved ({duration}ms)"
            )
            start_ts = base_time + timedelta(milliseconds=base_offset_ms + offset_ms)
            end_ts = start_ts + timedelta(milliseconds=duration)
            trace_logs.append(
                {
                    "timestamp": start_ts.isoformat(),
                    "level": level,
                    "message": start_message,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "parent_span_id": parent,
                    "service": service,
                    "duration_ms": duration,
                }
            )
            trace_logs.append(
                {
                    "timestamp": end_ts.isoformat(),
                    "level": level,
                    "message": end_message,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "parent_span_id": parent,
                    "service": service,
                    "duration_ms": duration,
                }
            )
        return trace_logs

    # BEFORE deployment - fast version
    before_durations = {
        "span-root": 220,
        "span-db": 60,
        "span-cache": 15,
        "span-format": 25,
    }
    before_logs = _emit_trace("trace-before", 0, before_durations)

    # AFTER deployment - slow version (regression!)
    after_durations = {
        "span-root": 820,  # ~4x slower
        "span-db": 420,  # regression here
        "span-cache": 20,
        "span-format": 30,
    }
    after_logs = _emit_trace("trace-after", 60_000, after_durations, cache_warning=True)

    # New span added after deployment
    audit_start = base_time + timedelta(milliseconds=60_480)
    audit_end = audit_start + timedelta(milliseconds=100)
    after_logs.extend(
        [
            {
                "timestamp": audit_start.isoformat(),
                "level": "INFO",
                "message": "Audit logging",
                "trace_id": "trace-after",
                "span_id": "span-audit",
                "parent_span_id": "span-root",
                "service": "audit-service",
                "duration_ms": 100,
            },
            {
                "timestamp": audit_end.isoformat(),
                "level": "INFO",
                "message": "Audit logging completed (100ms)",
                "trace_id": "trace-after",
                "span_id": "span-audit",
                "parent_span_id": "span-root",
                "service": "audit-service",
                "duration_ms": 100,
            },
        ]
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

    print(f"Created before.log: {len(before_logs)} entries, 220ms total")
    print(f"Created after.log: {len(after_logs)} entries, 820ms total")
    print("\nRegression: Database query went from 60ms to 420ms!")
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

    def _emit_request(correlation_id, offset_ms, cache_hit=True, db_timeout=False):
        _compare_logs.append(
            {
                "timestamp": (_base + _td(milliseconds=offset_ms)).isoformat(),
                "level": "INFO",
                "message": "Request started",
                "correlation_id": correlation_id,
            }
        )
        _compare_logs.append(
            {
                "timestamp": (_base + _td(milliseconds=offset_ms + 10)).isoformat(),
                "level": "INFO" if cache_hit else "WARN",
                "message": "Cache hit" if cache_hit else "Cache miss",
                "correlation_id": correlation_id,
            }
        )
        _compare_logs.append(
            {
                "timestamp": (_base + _td(milliseconds=offset_ms + 20)).isoformat(),
                "level": "INFO",
                "message": "Database query",
                "correlation_id": correlation_id,
            }
        )

        if db_timeout:
            _compare_logs.append(
                {
                    "timestamp": (_base + _td(milliseconds=offset_ms + 420)).isoformat(),
                    "level": "ERROR",
                    "message": "Database timeout",
                    "correlation_id": correlation_id,
                }
            )
            _compare_logs.append(
                {
                    "timestamp": (_base + _td(milliseconds=offset_ms + 430)).isoformat(),
                    "level": "ERROR",
                    "message": "Request failed",
                    "correlation_id": correlation_id,
                }
            )
        else:
            _compare_logs.append(
                {
                    "timestamp": (_base + _td(milliseconds=offset_ms + 60)).isoformat(),
                    "level": "INFO",
                    "message": "Response sent",
                    "correlation_id": correlation_id,
                }
            )

    _emit_request("req-success", 0, cache_hit=True, db_timeout=False)
    _emit_request("req-failed", 100, cache_hit=False, db_timeout=True)

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
