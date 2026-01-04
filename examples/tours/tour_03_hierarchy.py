import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(r"""
    # Logler Tour: Hierarchy Visualization

    Complex distributed systems create hierarchical execution patterns.
    Logler can visualize these as trees and waterfall diagrams.

    **What you'll learn:**
    1. Building hierarchies from logs
    2. Tree visualization
    3. Waterfall (timeline) diagrams
    4. Detecting bottlenecks
    5. Error flow analysis

    Let's dive in!
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Setting Up - OpenTelemetry-Style Logs

    We'll create logs with parent-child span relationships,
    similar to what OpenTelemetry produces.
    """)
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    logs = []

    # Root span - API request
    logs.append({
        "timestamp": (base_time + timedelta(ms=0)).isoformat(),
        "level": "INFO",
        "message": "HTTP GET /api/dashboard",
        "trace_id": "trace-001",
        "span_id": "span-root",
        "parent_span_id": None,
        "service": "api-gateway",
        "duration_ms": 450
    })

    # Child: Auth check
    logs.append({
        "timestamp": (base_time + timedelta(ms=5)).isoformat(),
        "level": "INFO",
        "message": "Authenticating request",
        "trace_id": "trace-001",
        "span_id": "span-auth",
        "parent_span_id": "span-root",
        "service": "auth-service",
        "duration_ms": 25
    })

    # Child: Fetch user data (parallel with fetch metrics)
    logs.append({
        "timestamp": (base_time + timedelta(ms=35)).isoformat(),
        "level": "INFO",
        "message": "Fetching user profile",
        "trace_id": "trace-001",
        "span_id": "span-user",
        "parent_span_id": "span-root",
        "service": "user-service",
        "duration_ms": 80
    })

    # Grandchild: Database query under user fetch
    logs.append({
        "timestamp": (base_time + timedelta(ms=40)).isoformat(),
        "level": "DEBUG",
        "message": "SELECT * FROM users WHERE id = 123",
        "trace_id": "trace-001",
        "span_id": "span-user-db",
        "parent_span_id": "span-user",
        "service": "postgres",
        "duration_ms": 45
    })

    # Grandchild: Cache lookup under user fetch
    logs.append({
        "timestamp": (base_time + timedelta(ms=90)).isoformat(),
        "level": "DEBUG",
        "message": "Cache HIT: user:123:preferences",
        "trace_id": "trace-001",
        "span_id": "span-user-cache",
        "parent_span_id": "span-user",
        "service": "redis",
        "duration_ms": 5
    })

    # Child: Fetch metrics (parallel with user data)
    logs.append({
        "timestamp": (base_time + timedelta(ms=35)).isoformat(),
        "level": "INFO",
        "message": "Fetching dashboard metrics",
        "trace_id": "trace-001",
        "span_id": "span-metrics",
        "parent_span_id": "span-root",
        "service": "metrics-service",
        "duration_ms": 200
    })

    # Grandchild: Slow aggregation (BOTTLENECK)
    logs.append({
        "timestamp": (base_time + timedelta(ms=40)).isoformat(),
        "level": "WARN",
        "message": "Aggregating metrics (slow query)",
        "trace_id": "trace-001",
        "span_id": "span-metrics-agg",
        "parent_span_id": "span-metrics",
        "service": "clickhouse",
        "duration_ms": 180
    })

    # Child: Fetch notifications
    logs.append({
        "timestamp": (base_time + timedelta(ms=240)).isoformat(),
        "level": "INFO",
        "message": "Fetching notifications",
        "trace_id": "trace-001",
        "span_id": "span-notif",
        "parent_span_id": "span-root",
        "service": "notification-service",
        "duration_ms": 60
    })

    # Grandchild: Notification DB
    logs.append({
        "timestamp": (base_time + timedelta(ms=245)).isoformat(),
        "level": "DEBUG",
        "message": "SELECT * FROM notifications WHERE user_id = 123",
        "trace_id": "trace-001",
        "span_id": "span-notif-db",
        "parent_span_id": "span-notif",
        "service": "postgres",
        "duration_ms": 35
    })

    # Child: Render response
    logs.append({
        "timestamp": (base_time + timedelta(ms=320)).isoformat(),
        "level": "INFO",
        "message": "Rendering dashboard response",
        "trace_id": "trace-001",
        "span_id": "span-render",
        "parent_span_id": "span-root",
        "service": "api-gateway",
        "duration_ms": 25
    })

    # Final response
    logs.append({
        "timestamp": (base_time + timedelta(ms=450)).isoformat(),
        "level": "INFO",
        "message": "Response sent: 200 OK (450ms)",
        "trace_id": "trace-001",
        "span_id": "span-root",
        "parent_span_id": None,
        "service": "api-gateway"
    })

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "otel.log"
    with open(log_file, "w") as f:
        for log in logs:
            f.write(json.dumps(log) + "\n")

    print(f"Created {len(logs)} log entries with span hierarchy")
    print(f"Trace ID: trace-001")
    return Path, base_time, log_file, logs, temp_dir


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Building the Hierarchy

    The `Investigator.build_hierarchy()` method reconstructs
    parent-child relationships from span IDs.
    """)
    return


@app.cell
def _():
    from logler.investigate import Investigator
    from logler.tree_formatter import format_tree, format_waterfall, get_hierarchy_summary

    return Investigator, format_tree, format_waterfall, get_hierarchy_summary


@app.cell
def _(Investigator, log_file):
    # Load logs and build hierarchy
    inv = Investigator()
    inv.load_files([str(log_file)])

    # Build hierarchy for trace-001
    hierarchy = inv.build_hierarchy("trace-001")

    print(f"=== Hierarchy Built ===")
    print(f"Total nodes: {hierarchy['total_nodes']}")
    print(f"Max depth: {hierarchy['max_depth']}")
    print(f"Detection method: {hierarchy.get('detection_method', 'Unknown')}")
    print(f"Total duration: {hierarchy.get('total_duration_ms', 'N/A')}ms")
    return hierarchy, inv


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Tree Visualization

    The tree view shows the hierarchical structure of spans,
    making parent-child relationships clear.
    """)
    return


@app.cell
def _(format_tree, hierarchy):
    # Format as tree (compact mode)
    tree = format_tree(hierarchy, mode="compact", use_colors=False)
    print(tree)
    return (tree,)


@app.cell
def _(format_tree, hierarchy):
    # Detailed mode shows more information
    detailed_tree = format_tree(hierarchy, mode="detailed", use_colors=False)
    print(detailed_tree)
    return (detailed_tree,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Waterfall Diagram

    The waterfall view shows timing relationships - when each span
    started and how long it took. This reveals parallelism and bottlenecks.
    """)
    return


@app.cell
def _(format_waterfall, hierarchy):
    # Format as waterfall (timeline view)
    waterfall = format_waterfall(hierarchy, width=80)
    print(waterfall)
    return (waterfall,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Hierarchy Summary

    Get a quick text summary of the hierarchy for reports or LLM context:
    """)
    return


@app.cell
def _(get_hierarchy_summary, hierarchy):
    summary = get_hierarchy_summary(hierarchy)
    print(summary)
    return (summary,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Detecting Bottlenecks

    Logler automatically identifies the slowest span (bottleneck):
    """)
    return


@app.cell
def _(hierarchy):
    bottleneck = hierarchy.get('bottleneck')

    if bottleneck:
        print("=== Bottleneck Detected ===")
        print(f"Node ID: {bottleneck.get('node_id')}")
        print(f"Duration: {bottleneck.get('duration_ms')}ms")
        print(f"Percentage of total: {bottleneck.get('percentage', 0):.1f}%")
    else:
        print("No bottleneck information available")
    return (bottleneck,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Error Flow Analysis

    When errors occur in a hierarchy, you can trace which nodes failed:
    """)
    return


@app.cell
def _(hierarchy):
    error_nodes = hierarchy.get('error_nodes', [])

    if error_nodes:
        print(f"=== Error Nodes ({len(error_nodes)}) ===")
        for node_id in error_nodes:
            print(f"  - {node_id}")
    else:
        print("No errors in this hierarchy")

    # Show concurrent operations
    concurrent = hierarchy.get('concurrent_count', 0)
    print(f"\nConcurrent operations detected: {concurrent}")
    return concurrent, error_nodes


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Custom Hierarchy Options

    You can customize hierarchy detection with various options:
    """)
    return


@app.cell
def _(inv):
    # Build with custom options
    custom_hierarchy = inv.build_hierarchy(
        "trace-001",
        max_depth=3,  # Limit depth
        use_naming_patterns=True,  # Use naming conventions for relationships
        use_temporal_inference=True,  # Infer relationships from timing
        min_confidence=0.7  # Minimum confidence for inferred relationships
    )

    print(f"Custom hierarchy built:")
    print(f"  Max depth: {custom_hierarchy['max_depth']}")
    print(f"  Total nodes: {custom_hierarchy['total_nodes']}")
    return (custom_hierarchy,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've learned how to visualize hierarchies in Logler:

    - **`build_hierarchy(trace_id)`** - Reconstruct span relationships
    - **`format_tree(hierarchy)`** - Tree view (compact, detailed, full)
    - **`format_waterfall(hierarchy)`** - Timeline view with bars
    - **`get_hierarchy_summary(hierarchy)`** - Text summary

    **Key Insights:**
    - Hierarchies reveal the structure of distributed operations
    - Waterfall diagrams expose parallelism and bottlenecks
    - Error nodes help trace failure propagation

    **Next Steps:**
    - **Tour 04**: Investigation sessions (track your analysis)
    - **Tour 05**: Pattern detection (find recurring issues)
    """)
    return


@app.cell
def _(temp_dir):
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return (shutil,)


if __name__ == "__main__":
    app.run()
