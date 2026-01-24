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
    # Logler Tour: Hierarchy Visualization

    Complex distributed systems create hierarchical execution patterns.
    Logler can visualize these as trees and waterfall diagrams.

    **What you'll learn:**
    1. OpenTelemetry field conventions (trace_id, span_id, parent_span_id)
    2. How to add readable labels with `operation_name`
    3. Tree visualization
    4. Waterfall (timeline) diagrams
    5. Detecting bottlenecks and errors

    Let's dive in!
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. OpenTelemetry Field Conventions

    Logler follows **OpenTelemetry** conventions for distributed tracing.
    These fields enable automatic hierarchy detection:

    | Field | Purpose | Example |
    |-------|---------|---------|
    | `trace_id` | Groups all spans in one request | `"trace-abc123"` |
    | `span_id` | Unique ID for this operation | `"span-auth"` |
    | `parent_span_id` | Links to parent span | `"span-root"` |
    | `operation_name` | **Human-readable label** (displayed in tree) | `"Auth Check"` |
    | `duration_ms` | How long this span took | `25` |

    **Important:** Without `operation_name`, the tree shows raw span IDs like
    "span-root" which isn't helpful. Always add descriptive operation names!
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Creating Sample Trace Data

    We'll simulate a dashboard request that:
    - Authenticates the user
    - Fetches user data (with a DB query and cache lookup)
    - Fetches metrics (with a SLOW aggregation - our bottleneck)
    - Has an ERROR in the notification service
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

    def add_span(
        span_id,
        parent_span_id,
        operation_name,
        service,
        message,
        offset_ms,
        duration_ms,
        level="INFO",
    ):
        """Helper to create properly structured span logs."""
        logs.append(
            {
                "timestamp": (base_time + timedelta(milliseconds=offset_ms)).isoformat(),
                "level": level,
                "message": message,
                # OpenTelemetry standard fields
                "trace_id": "trace-001",
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                # Human-readable label (THIS IS KEY for nice tree output!)
                "operation_name": operation_name,
                # Additional context
                "service": service,
                "duration_ms": duration_ms,
            }
        )

    # Root span - API Gateway handles the request
    add_span(
        "span-root", None, "GET /api/dashboard", "api-gateway", "HTTP GET /api/dashboard", 0, 450
    )

    # Child: Auth check (fast)
    add_span("span-auth", "span-root", "Auth Check", "auth-service", "Validating JWT token", 5, 25)

    # Child: Fetch user data
    add_span(
        "span-user",
        "span-root",
        "Fetch User Profile",
        "user-service",
        "Loading user profile for user:123",
        35,
        80,
    )

    # Grandchild: Database query under user fetch
    add_span(
        "span-user-db",
        "span-user",
        "User DB Query",
        "postgres",
        "SELECT * FROM users WHERE id = 123",
        40,
        45,
        "DEBUG",
    )

    # Grandchild: Cache lookup under user fetch
    add_span(
        "span-user-cache",
        "span-user",
        "User Cache Lookup",
        "redis",
        "Cache HIT: user:123:preferences",
        90,
        5,
        "DEBUG",
    )

    # Child: Fetch metrics (parallel with user data)
    add_span(
        "span-metrics",
        "span-root",
        "Fetch Metrics",
        "metrics-service",
        "Loading dashboard metrics",
        35,
        200,
    )

    # Grandchild: SLOW aggregation - THIS IS THE BOTTLENECK
    add_span(
        "span-metrics-agg",
        "span-metrics",
        "Metrics Aggregation (SLOW)",
        "clickhouse",
        "Aggregating 1M rows - this is slow!",
        40,
        180,
        "WARN",
    )

    # Child: Fetch notifications - THIS WILL HAVE AN ERROR
    add_span(
        "span-notif",
        "span-root",
        "Fetch Notifications",
        "notification-service",
        "Loading notifications for user:123",
        240,
        60,
    )

    # Grandchild: Notification DB - ERROR!
    add_span(
        "span-notif-db",
        "span-notif",
        "Notification DB Query",
        "postgres",
        "Connection timeout to notifications DB",
        245,
        55,
        "ERROR",
    )

    # Child: Render response
    add_span(
        "span-render",
        "span-root",
        "Render Response",
        "api-gateway",
        "Building JSON response",
        320,
        25,
    )

    # Final response log (same span as root)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=450)).isoformat(),
            "level": "INFO",
            "message": "Response sent: 200 OK (450ms)",
            "trace_id": "trace-001",
            "span_id": "span-root",
            "parent_span_id": None,
            "operation_name": "GET /api/dashboard",
            "service": "api-gateway",
        }
    )

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "otel.log"
    with open(log_file, "w") as f:
        for log in logs:
            f.write(json.dumps(log) + "\n")

    print(f"Created {len(logs)} log entries with span hierarchy")
    print("Trace ID: trace-001")
    print("\nKey features of this trace:")
    print("  - Bottleneck: Metrics Aggregation (180ms)")
    print("  - Error: Notification DB Query (connection timeout)")
    print("  - Parallel operations: User fetch + Metrics fetch")
    return log_file, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Building the Hierarchy

    Use `Investigator.build_hierarchy(trace_id)` to reconstruct
    parent-child relationships from `span_id` and `parent_span_id` fields.
    """
    )
    return


@app.cell
def _():
    from logler.investigate import Investigator, get_hierarchy_summary
    from logler.tree_formatter import format_tree, format_waterfall

    return Investigator, format_tree, format_waterfall, get_hierarchy_summary


@app.cell
def _(Investigator, log_file):
    # Load logs and build hierarchy
    inv = Investigator()
    inv.load_files([str(log_file)])

    # Build hierarchy for trace-001
    hierarchy = inv.build_hierarchy("trace-001")

    print("=== Hierarchy Built ===")
    print(f"Total nodes: {hierarchy['total_nodes']}")
    print(f"Max depth: {hierarchy['max_depth']}")
    print(f"Total duration: {hierarchy.get('total_duration_ms', 'N/A')}ms")

    # Show detection method
    detection = hierarchy.get("detection_method", "Unknown")
    print(f"Detection method: {detection}")
    print("\n(Detection should be 'Explicit' since we used parent_span_id)")
    return (hierarchy,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Tree Visualization

    The tree view shows the hierarchical structure. Notice how nodes
    display the `operation_name` we provided, not raw span IDs!
    """
    )
    return


@app.cell
def _(format_tree, hierarchy):
    # Format as tree (compact mode)
    print("=== Compact Tree View ===\n")
    tree = format_tree(hierarchy, mode="compact", use_colors=False)
    print(tree)
    return


@app.cell
def _(format_tree, hierarchy):
    # Detailed mode shows duration and entry counts
    print("=== Detailed Tree View ===\n")
    detailed_tree = format_tree(hierarchy, mode="detailed", use_colors=False)
    print(detailed_tree)
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. Waterfall Diagram

    The waterfall shows **when** each span started and **how long** it took.
    This reveals:
    - Parallelism (spans starting at the same time)
    - Bottlenecks (wide bars)
    - Sequential dependencies
    """
    )
    return


@app.cell
def _(format_waterfall, hierarchy):
    # Format as waterfall (timeline view)
    print("=== Waterfall Timeline ===\n")
    waterfall = format_waterfall(hierarchy, width=70)
    print(waterfall)
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 6. Detecting Bottlenecks

    Logler automatically identifies the slowest span. In our trace,
    it should find the "Metrics Aggregation" span (180ms).
    """
    )
    return


@app.cell
def _(hierarchy):
    bottleneck = hierarchy.get("bottleneck")

    if bottleneck:
        print("=== Bottleneck Detected ===")
        print(f"Node: {bottleneck.get('node_id')}")
        print(f"Duration: {bottleneck.get('duration_ms', 0)}ms")
        total_ms = hierarchy.get("total_duration_ms", 1)
        if total_ms:
            pct = (bottleneck.get("duration_ms", 0) / total_ms) * 100
            print(f"Percentage of total: {pct:.1f}%")
        print("\nThis is where optimization efforts should focus!")
    else:
        print("No bottleneck detected")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 7. Error Detection

    Logler tracks which nodes have errors. In our trace, the
    "Notification DB Query" span has an ERROR level log.
    """
    )
    return


@app.cell
def _(hierarchy):
    error_nodes = hierarchy.get("error_nodes", [])

    print("=== Error Analysis ===\n")
    if error_nodes:
        print(f"Found {len(error_nodes)} node(s) with errors:")
        for node_id in error_nodes:
            print(f"  - {node_id}")
        print("\nThese nodes had ERROR level logs and may need investigation.")
    else:
        print("No errors detected in this hierarchy")

    # Show concurrent operations
    concurrent = hierarchy.get("concurrent_count", 0)
    if concurrent:
        print(f"\nConcurrent operations detected: {concurrent}")
        print("(Multiple spans running in parallel)")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 8. Hierarchy Summary

    Get a text summary suitable for reports or LLM context:
    """
    )
    return


@app.cell
def _(get_hierarchy_summary, hierarchy):
    summary = get_hierarchy_summary(hierarchy)
    print(summary)
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    **OpenTelemetry Fields for Hierarchy:**
    - `trace_id` - Groups all spans in a distributed trace
    - `span_id` - Unique identifier for each operation
    - `parent_span_id` - Links child spans to parents
    - `operation_name` - **Human-readable label** (use this for nice output!)
    - `duration_ms` - Time taken by this span

    **Visualization Functions:**
    - `build_hierarchy(trace_id)` - Reconstruct span relationships
    - `format_tree(hierarchy)` - Tree view (compact, detailed, full)
    - `format_waterfall(hierarchy)` - Timeline with bars
    - `get_hierarchy_summary(hierarchy)` - Text summary

    **Automatic Detection:**
    - Bottlenecks (slowest spans)
    - Errors (nodes with ERROR level logs)
    - Concurrent operations (parallel spans)

    **Next Steps:**
    - **Tour 04**: Investigation sessions
    - **Tour 05**: Pattern detection
    - **Tour 06**: Flamegraph visualization
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
