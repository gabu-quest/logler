import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
    # Logler Tour: Pattern Detection

    When investigating large log files, you need to identify recurring patterns
    — repeated errors, frequent messages, and the components that produce them.

    **What you'll learn:**
    1. Finding patterns across thousands of log entries
    2. Ranking the most frequent issues
    3. Grouping issues by component/service
    4. Assessing pattern severity
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
    logs = []

    # Generate diverse log patterns
    patterns = [
        ("api", "ERROR", "Connection timeout to database server"),
        ("api", "ERROR", "Connection timeout to database server"),
        ("api", "ERROR", "Connection timeout to database server"),
        ("api", "ERROR", "Connection timeout to database server"),
        ("api", "ERROR", "Connection timeout to database server"),
        ("api", "WARN", "Slow query detected: SELECT * FROM orders took 2500ms"),
        ("api", "WARN", "Slow query detected: SELECT * FROM users took 1800ms"),
        ("api", "WARN", "Slow query detected: SELECT * FROM inventory took 3200ms"),
        ("worker", "ERROR", "Failed to process job batch-001: out of memory"),
        ("worker", "ERROR", "Failed to process job batch-002: out of memory"),
        ("worker", "ERROR", "Failed to process job batch-003: out of memory"),
        ("auth", "WARN", "Rate limit exceeded for IP 192.168.1.50"),
        ("auth", "WARN", "Rate limit exceeded for IP 10.0.0.100"),
        ("auth", "ERROR", "Invalid token: expired at 2024-01-15T09:00:00Z"),
        ("cache", "WARN", "Cache eviction: memory usage at 95%"),
        ("cache", "WARN", "Cache eviction: memory usage at 92%"),
        ("scheduler", "INFO", "Cron job backup_daily completed in 45s"),
        ("scheduler", "INFO", "Cron job cleanup_logs completed in 12s"),
    ]

    # Bulk generate with some normal entries
    for _i in range(50):
        if _i < len(patterns):
            _component, _level, _message = patterns[_i]
        else:
            _component = ["api", "worker", "auth", "cache", "scheduler"][_i % 5]
            _level = "INFO"
            _message = f"Processing request {_i}"

        logs.append(
            {
                "timestamp": (base_time + timedelta(seconds=_i)).isoformat(),
                "level": _level,
                "message": _message,
                "component": _component,
                "thread_id": f"worker-{_i % 4}",
            }
        )

    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "patterns.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries across 5 components")
    return log_file, logs, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Finding Patterns

    Use `find_patterns` to discover recurring log messages:
    """
    )
    return


@app.cell
def _(log_file):
    from logler.investigate import search

    # Find all entries to analyze patterns
    result = search(files=[str(log_file)], query="", limit=200)

    # Group by message to find patterns
    from collections import Counter

    messages = [_r["entry"]["message"] for _r in result.get("results", [])]
    pattern_counts = Counter(messages)

    print("=== Patterns Found ===\n")
    print(f"Total entries: {result['total_matches']}")
    print(f"Unique messages: {len(pattern_counts)}")
    print("\nTop patterns by frequency:")
    for _msg, _count in pattern_counts.most_common(10):
        print(f"  [{_count:>3}x] {_msg[:80]}")
    return pattern_counts, result


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Ranking the Most Frequent Issues
    """
    )
    return


@app.cell
def _(pattern_counts, result):
    # Filter for error/warning patterns only
    error_msgs = []
    for _r in result.get("results", []):
        if _r["entry"]["level"] in ("ERROR", "WARN", "WARNING"):
            error_msgs.append(_r["entry"]["message"])

    from collections import Counter as _Counter

    issue_counts = _Counter(error_msgs)

    print("=== Top 3 Most Frequent Issues ===\n")
    for _i, (_msg, _count) in enumerate(issue_counts.most_common(3), 1):
        severity = "HIGH" if _count >= 4 else "MEDIUM" if _count >= 2 else "LOW"
        print(f"{_i}. [{severity}] ({_count}x) {_msg[:70]}")
    print(f"\nTotal issues found: {len(issue_counts)}")
    return issue_counts


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Grouping by Component
    """
    )
    return


@app.cell
def _(result):
    from collections import defaultdict

    component_issues = defaultdict(list)
    for _r in result.get("results", []):
        if _r["entry"]["level"] in ("ERROR", "WARN", "WARNING"):
            _component = _r["entry"].get("fields", {}).get("component", "unknown")
            component_issues[_component].append(_r["entry"]["message"])

    print("=== Issues by Component ===\n")
    for _component, msgs in sorted(component_issues.items(), key=lambda x: -len(x[1])):
        unique = set(msgs)
        print(f"[{_component}] {len(msgs)} issues ({len(unique)} unique)")
        for _msg in sorted(unique):
            _count = msgs.count(_msg)
            print(f"  - ({_count}x) {_msg[:60]}")
        print()
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Severity Assessment
    """
    )
    return


@app.cell
def _(issue_counts, result):
    total = result["total_matches"]
    error_count = sum(
        1
        for _r in result.get("results", [])
        if _r["entry"]["level"] in ("ERROR", "CRITICAL", "FATAL")
    )
    warn_count = sum(
        1 for _r in result.get("results", []) if _r["entry"]["level"] in ("WARN", "WARNING")
    )

    print("=== Pattern Severity Assessment ===\n")
    print(f"Total entries analyzed: {total}")
    print(f"Error entries: {error_count} ({100 * error_count / total:.1f}%)")
    print(f"Warning entries: {warn_count} ({100 * warn_count / total:.1f}%)")
    print()

    # Assess recurring patterns
    recurring = {msg: cnt for msg, cnt in issue_counts.items() if cnt >= 2}
    print(f"Recurring patterns (2+ occurrences): {len(recurring)}")
    if recurring:
        worst = max(recurring.items(), key=lambda x: x[1])
        print(f"Most frequent: '{worst[0][:60]}' ({worst[1]}x)")
        print("Recommendation: Investigate root cause of recurring errors")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've learned how to detect and analyze log patterns:

    - **Pattern discovery** — Group messages by content to find recurring issues
    - **Frequency ranking** — Identify the most impactful problems
    - **Component grouping** — See which services produce the most issues
    - **Severity assessment** — Quantify error vs warning ratios

    **Next Steps:**
    - **Tour 06**: Flamegraph visualization
    - **Tour 07**: Error flow analysis
    """
    )
    return


@app.cell
def _(temp_dir):
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return


if __name__ == "__main__":
    app.run()
