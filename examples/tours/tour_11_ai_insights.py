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
    # Logler Tour: AI Investigation Insights

    Demonstrate an LLM-powered investigation workflow: triage log entries,
    generate insights, explain errors, and suggest next actions.

    **What you'll learn:**
    1. Automatic triage of log data
    2. Generating structured insights
    3. Error explanation
    4. Suggesting actionable next steps
    """
    )
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    base_time = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
    logs = []

    # Simulate a cascading failure scenario
    scenario = [
        (0, "INFO", "api", "Health check passed"),
        (1, "INFO", "api", "Request GET /api/users processed in 45ms"),
        (2, "INFO", "database", "Connection pool: 10/10 available"),
        (5, "WARN", "database", "Connection pool: 3/10 available"),
        (8, "WARN", "database", "Connection pool: 1/10 available"),
        (10, "ERROR", "database", "Connection pool exhausted: 0/10 available"),
        (11, "ERROR", "api", "Database connection timeout after 5000ms"),
        (12, "ERROR", "api", "Request GET /api/orders failed: database unavailable"),
        (13, "ERROR", "api", "Request POST /api/checkout failed: database unavailable"),
        (14, "WARN", "loadbalancer", "Backend api-01 health check failed"),
        (15, "ERROR", "loadbalancer", "No healthy backends available"),
        (16, "ERROR", "api", "Circuit breaker OPEN for database-pool"),
        (20, "INFO", "database", "Connection pool recovering: 2/10 available"),
        (25, "INFO", "database", "Connection pool: 8/10 available"),
        (30, "INFO", "api", "Circuit breaker HALF-OPEN for database-pool"),
        (35, "INFO", "api", "Circuit breaker CLOSED for database-pool"),
        (36, "INFO", "api", "Request GET /api/users processed in 52ms"),
        (40, "INFO", "loadbalancer", "Backend api-01 health check passed"),
    ]

    for offset, _level, _component, _message in scenario:
        logs.append(
            {
                "timestamp": (base_time + timedelta(seconds=offset)).isoformat(),
                "level": _level,
                "message": _message,
                "component": _component,
                "service": _component,
                "thread_id": f"{_component}-main",
            }
        )

    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "cascading_failure.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries simulating cascading failure")
    return log_file, logs, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Automatic Analysis

    First, let's triage the log data automatically:
    """
    )
    return


@app.cell
def _(log_file, logs):
    from logler.investigate import search

    result = search(files=[str(log_file)], query="", limit=200)

    # Triage: count by level and component
    from collections import Counter, defaultdict

    level_counts = Counter()
    component_errors = defaultdict(list)

    for item in result.get("results", []):
        entry = item["entry"]
        level_counts[entry["level"]] += 1
        if entry["level"] in ("ERROR", "CRITICAL", "FATAL"):
            _component = entry.get("fields", {}).get("component", "unknown")
            component_errors[_component].append(entry["message"])

    print("=== Automatic Analysis ===\n")
    print(f"Total entries: {result['total_matches']}")
    print("\nLevel distribution:")
    for _level in ("ERROR", "WARN", "INFO", "DEBUG"):
        _count = level_counts.get(_level, 0)
        if _count:
            print(f"  {_level}: {_count}")

    print("\nError sources:")
    for _comp, msgs in sorted(component_errors.items(), key=lambda x: -len(x[1])):
        print(f"  {_comp}: {len(msgs)} errors")
    return component_errors, level_counts, result


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Generating Insights

    Analyze the timeline to extract structured insights:
    """
    )
    return


@app.cell
def _(result):
    # Build timeline analysis
    _entries = result.get("results", [])
    _errors = [
        item["entry"] for item in _entries if item["entry"]["level"] in ("ERROR", "CRITICAL")
    ]
    _warnings = [
        item["entry"] for item in _entries if item["entry"]["level"] in ("WARN", "WARNING")
    ]

    print("=== INSIGHTS ===\n")

    # Insight 1: Root cause identification
    if _errors:
        first_error = _errors[0]
        print(f"1. FIRST ERROR: '{first_error['message']}'")
        print(f"   at {first_error.get('timestamp', 'unknown')}")
        _component = first_error.get("fields", {}).get("component", "unknown")
        print(f"   Component: {_component}")
        print()

    # Insight 2: Warning-to-error escalation
    if _warnings and _errors:
        first_warn_ts = _warnings[0].get("timestamp", "")
        first_error_ts = _errors[0].get("timestamp", "")
        print(f"2. ESCALATION: Warnings started at {first_warn_ts}")
        print(f"   Errors began at {first_error_ts}")
        print(f"   {len(_warnings)} warnings preceded {len(_errors)} errors")
        print()

    # Insight 3: Affected components
    affected = set()
    for _e in _errors:
        _comp = _e.get("fields", {}).get("component", "unknown")
        affected.add(_comp)
    print(f"3. BLAST RADIUS: {len(affected)} components affected: {', '.join(sorted(affected))}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Error Explanation
    """
    )
    return


@app.cell
def _(result):
    _entries = result.get("results", [])
    _errors = [
        item["entry"] for item in _entries if item["entry"]["level"] in ("ERROR", "CRITICAL")
    ]

    print("=== Error Explanation ===\n")
    print("Root Cause Chain:")
    print("  1. Database connection pool started draining (WARN)")
    print("  2. Pool exhausted -> database timeout errors (ERROR)")
    print("  3. API could not serve requests -> 5xx responses (ERROR)")
    print("  4. Load balancer detected unhealthy backend (ERROR)")
    print()
    print("Mechanism: Connection pool exhaustion caused cascading failure")
    print(f"Evidence: {len(_errors)} error entries across multiple components")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Suggested Actions
    """
    )
    return


@app.cell
def _():
    print("=== Suggested Next Actions ===\n")
    actions = [
        "Increase database connection pool size (currently 10)",
        "Add connection pool monitoring with early warning at 50% utilization",
        "Configure circuit breaker with faster timeout (currently 5000ms)",
        "Add load balancer retry logic for transient database failures",
        "Review database query performance for slow queries",
    ]
    for _i, action in enumerate(actions, 1):
        print(f"  {_i}. {action}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. Complete Investigation Workflow
    """
    )
    return


@app.cell
def _(log_file):
    from logler.investigate import InvestigationSession

    session = InvestigationSession(files=[str(log_file)], name="cascading_failure")

    # Step 1: Find errors
    _errors = session.search(level="ERROR")
    # Step 2: Find warnings (precursors)
    _warnings = session.search(level="WARN")
    # Step 3: Follow database component
    db_logs = session.search(query="connection pool")

    print("=" * 60)
    print("INVESTIGATION WORKFLOW")
    print("=" * 60)
    print(f"\nStep 1: Found {_errors['total_matches']} errors")
    print(f"Step 2: Found {_warnings['total_matches']} warnings (precursors)")
    print(f"Step 3: Found {db_logs['total_matches']} connection pool entries")
    print(f"\nHistory: {len(session.get_history())} steps recorded")

    session.add_note("Cascading failure caused by connection pool exhaustion")
    print("Note added to investigation")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've seen the LLM investigation workflow:

    - **Automatic Analysis** — Triage by level and component
    - **Insights** — Root cause, escalation patterns, blast radius
    - **Error Explanation** — Chain of causation
    - **Next Actions** — Prioritized remediation steps
    - **Investigation Session** — Full tracking of the investigation process

    **Next Steps:**
    - **Tour 12**: Multi-file interleaving
    - **Tour 14**: Performance at scale
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
